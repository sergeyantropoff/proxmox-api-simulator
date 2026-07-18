"""Probe every declared contract method across majors 6-9.

Order: GET, then PUT, then POST, then DELETE. Critical buckets
(``unimplemented_501``, ``unsupported_message``, ``server_5xx``,
``exception``) must stay empty — this module backs the CI surface gate.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.contracts.examples import path_param_example, schema_example
from app.contracts.model import Method, Snapshot
from app.db.migrations import migrate
from app.db.pool import AsyncpgDatabase
from app.main import create_app
from app.simulation.seed import apply_seed, lab_profile
from app.web.contract_catalog import get_major_releases

_BUNDLED_9 = Path(
    "contracts/e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1/snapshot.json"
)
_EVIDENCE_9 = Path("evidence/pve-9.2.3.json")
_PATH_RE = re.compile(r"\{([^{}]+)\}")
_FORBIDDEN = re.compile(
    r"not supported in the emulator|not implemented in the simulator|"
    r"handler pending for this contract method|is not supported in the (emulator|simulator)",
    re.I,
)
_EXTRA_PATH: dict[str, object] = {
    "groupid": "admins",
    "roleid": "Administrator",
    "zone": "localnet",
    "vnet": "vnet0",
    "subnet": "10.0.0.0-24",
    "controller": "evpn1",
    "dns": "dns1",
    "ipam": "pve",
    "flag": "noout",
    "osdid": "0",
    "monid": "0",
    "id": "example",
    "cputype": "custom1",
    "pci-id-or-mapping": "0000:00:1f.0",
    "rule": "rule1",
    "sid": "vm:100",
    "pos": "0",
    "cidr": "10.0.0.0/24",
    "tokenid": "automation",
    "fabric_id": "fab1",
    "node_id": "pve01",
    "url_seq": "1",
    "route-map-id": "rm1",
    "order": "10",
    "userid": "root@pam",
    "realm": "pam",
    "name": "example",
    "plugin": "example",
    "target": "example",
}


def _path_value(name: str) -> str:
    value = path_param_example(name)
    if value is None:
        value = _EXTRA_PATH.get(name, "example")
    return str(value)


def render_path(template: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return quote(str(_path_value(match.group(1))), safe="@._-")

    return _PATH_RE.sub(replace, template)


def body_for(method: Method, path_template: str) -> dict[str, Any]:
    path_names = set(_PATH_RE.findall(path_template))
    payload: dict[str, Any] = {}
    for parameter in method.parameters:
        if parameter.name in path_names:
            continue
        if parameter.definition.optional:
            continue
        payload[parameter.name] = schema_example(parameter.definition, name=parameter.name)
    return payload


def classify(status: int, text: str) -> str:
    if _FORBIDDEN.search(text or ""):
        return "unsupported_message"
    if status == 501:
        return "unimplemented_501"
    if 200 <= status < 300:
        return "success_2xx"
    if status in {401, 403}:
        return "auth_401_403"
    if status in {400, 404, 405, 409, 412, 422, 423}:
        return "client_4xx"
    if status >= 500:
        return "server_5xx"
    return f"other_{status}"


async def prepare_db(url: str) -> None:
    connection = await asyncpg.connect(url)
    try:
        await migrate(connection)
        await apply_seed(connection, lab_profile())
    finally:
        await connection.close()


async def login(client: AsyncClient) -> str:
    response = await client.post(
        "/api2/json/access/ticket",
        content="username=root%40pam&password=secret",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    data = response.json()["data"]
    client.cookies.set("PVEAuthCookie", data["ticket"])
    return str(data["CSRFPreventionToken"])


async def probe_major(
    client: AsyncClient,
    csrf: str,
    major: int,
    snapshot: Snapshot,
) -> dict[str, Any]:
    apply = await client.post("/ui/api/contract/apply", params={"major": major})
    apply.raise_for_status()
    applied = apply.json()
    report = (await client.get("/admin/compatibility")).json()

    by_verb: dict[str, Counter[str]] = defaultdict(Counter)
    failures: list[dict[str, Any]] = []
    samples_ok: dict[str, int] = Counter()

    methods = [(path.path, method) for path in snapshot.paths for method in path.methods]
    order = {"GET": 0, "PUT": 1, "POST": 2, "DELETE": 3}
    methods.sort(key=lambda item: (order.get(item[1].verb.upper(), 9), item[0]))

    for path_template, method in methods:
        verb = method.verb.upper()
        url = f"/api2/json{render_path(path_template)}"
        headers = {"CSRFPreventionToken": csrf} if verb != "GET" else {}
        payload = body_for(method, path_template)
        try:
            if verb == "GET":
                response = await client.get(url, headers=headers, params=payload or None)
            elif verb == "PUT":
                response = await client.put(url, data=payload or {}, headers=headers)
            elif verb == "POST":
                response = await client.post(url, data=payload or {}, headers=headers)
            elif verb == "DELETE":
                response = await client.request("DELETE", url, data=payload or {}, headers=headers)
            else:
                continue
        except Exception as exc:
            by_verb[verb]["exception"] += 1
            failures.append(
                {
                    "verb": verb,
                    "path": path_template,
                    "error": str(exc)[:200],
                    "bucket": "exception",
                }
            )
            continue

        text = response.text
        bucket = classify(response.status_code, text)
        by_verb[verb][bucket] += 1
        samples_ok[verb] += int(bucket == "success_2xx")
        if bucket in {"unimplemented_501", "unsupported_message", "server_5xx", "exception"}:
            failures.append(
                {
                    "verb": verb,
                    "path": path_template,
                    "status": response.status_code,
                    "bucket": bucket,
                    "body": text[:240],
                }
            )

    levels = report.get("levels") or {}
    dims = report.get("dimensions") or {}
    return {
        "major": major,
        "version": snapshot.source_version,
        "apply": applied,
        "declared": report.get("total_declared"),
        "implemented": (levels.get("implemented") or {}).get("count"),
        "verified": (levels.get("verified") or {}).get("count"),
        "dimensions_min": min((item.get("count") or 0) for item in dims.values()) if dims else 0,
        "by_verb": {verb: dict(counter) for verb, counter in by_verb.items()},
        "success_by_verb": dict(samples_ok),
        "failure_count": len(failures),
        "failures": failures[:40],
    }


async def run_probe(*, database_url: str | None = None) -> list[dict[str, Any]]:
    """Run the full surface probe and return per-major result dicts."""

    url = database_url or os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("TEST_DATABASE_URL / DATABASE_URL required")
    await prepare_db(url)
    settings = Settings(
        database_url=SecretStr(url),
        contract_snapshot=_BUNDLED_9,
        compatibility_evidence=_EVIDENCE_9,
        ticket_signing_key=SecretStr("development-only-signing-key-change-me"),
    )
    app = create_app(settings=settings, database_factory=lambda s: AsyncpgDatabase(s))

    releases = {release.major: release for release in get_major_releases()}
    results: list[dict[str, Any]] = []
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            csrf = await login(client)
            for major in (6, 7, 8, 9):
                release = releases[major]
                if release.bundled_revision is None:
                    raise RuntimeError(f"missing bundled revision for major {major}")
                snapshot = Snapshot.model_validate_json(
                    (Path("contracts") / release.bundled_revision / "snapshot.json").read_bytes()
                )
                # Keep a single DB seed for the whole run to avoid deadlocks with
                # the live app pool during DELETE FROM cascades.
                results.append(await probe_major(client, csrf, major, snapshot))
    return results


async def main() -> int:
    try:
        results = await run_probe()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    out = Path("evidence/_api_surface_probe.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(out), "majors": len(results)}))
    for item in results:
        print(
            f"PVE {item['version']}: declared={item['declared']} "
            f"impl={item['implemented']} ver={item['verified']} "
            f"fail={item['failure_count']}"
        )
        for verb in ("GET", "PUT", "POST", "DELETE"):
            buckets = item["by_verb"].get(verb) or {}
            if not buckets:
                continue
            total = sum(buckets.values())
            print(f"  {verb}: total={total} {buckets}")
    critical = sum(int(item["failure_count"]) for item in results)
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
