"""Sync contract surface probe against a live simulator (majors 6–9).

Mirrors ``app/surface_probe.py`` classification and path/body synthesis, but
talks HTTP to ``API_URL`` instead of an in-process ASGI app.

Layer A matrix:
- every declared path+verb (GET/PUT/POST/DELETE)
- synthetic HEAD on each GET path (histogram only; not counted in declared)
- ticket + CSRF on mutations; form-urlencoded bodies
- Proxmox ``{ "data": … }`` envelope checks on 2xx
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

# Bundled revisions — keep in sync with app/web/contract_catalog.py
MAJOR_REVISIONS: dict[int, tuple[str, str]] = {
    6: ("6.4-15", "96cd7121e75cdb3efd58f79ca988f6b235a2f28e6f7eae276ae243f65d8a6724"),
    7: ("7.4-16", "2cf632fa6ea4939ca9cb7998ade688150db25b0684600f53ac0ca95730f1d99f"),
    8: ("8.4.5", "fce6db0a784b3a9b447895895fc6ff4b4437c2dce82e5f3db99227af217726fa"),
    9: ("9.2.3", "e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1"),
}

_PATH_RE = re.compile(r"\{([^{}]+)\}")
_FORBIDDEN = re.compile(
    r"not supported in the emulator|not implemented in the simulator|"
    r"handler pending for this contract method|is not supported in the (emulator|simulator)",
    re.I,
)
_UPID_RE = re.compile(
    r"^UPID:[A-Za-z0-9][A-Za-z0-9_-]*:"
    r"[0-9A-Fa-f]{8}:[0-9A-Fa-f]{8}:[0-9A-Fa-f]{8}:"
    r"[A-Za-z0-9_-]+:[^:]*:[^:]+:$"
)

_PATH_PARAM_EXAMPLES: dict[str, object] = {
    "node": "pve01",
    "vmid": 100,
    "storage": "local",
    "pool": "testpool",
    "userid": "root@pam",
    "tokenid": "automation",
    "realm": "pam",
    "group": "admins",
    "role": "Administrator",
    "upid": "UPID:pve01:00000001:00000001:65000001:qmstart:100:root@pam:",
    "snapname": "snap1",
    "volume": "local:100/vm-100-disk-0.qcow2",
    "disk": "scsi0",
    "iface": "net0",
    "key": "cpu",
    "digest": "00000000",
    "name": "example",
    "size": "1G",
    "filename": "vm-100-disk-0.raw",
    "certificates": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n",
    "contact": "mailto:admin@example.com",
    "clustername": "lab",
}

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

CRITICAL_BUCKETS = frozenset(
    {
        "unimplemented_501",
        "unsupported_message",
        "server_5xx",
        "exception",
        "empty_success_body",
        "wrong_returns_envelope",
    }
)

# Path suffixes that real PVE usually runs via fork_worker → UPID string.
_WORKER_SUFFIXES = (
    "/status/start",
    "/status/stop",
    "/status/shutdown",
    "/status/reboot",
    "/status/reset",
    "/status/suspend",
    "/status/resume",
    "/clone",
    "/migrate",
    "/remote_migrate",
    "/snapshot",
    "/rollback",
    "/template",
    "/resize",
    "/move_disk",
    "/move_volume",
    "/vzdump",
    "/apt/update",
)


def contracts_root() -> Path:
    env = os.environ.get("CONTRACTS_ROOT")
    if env:
        return Path(env)
    # Runner mounts repo at /workspace; local runs use repo-relative path.
    here = Path(__file__).resolve()
    candidates = [
        Path("/workspace/contracts"),
        here.parents[3] / "contracts",  # pulumi-tests/pulumi/pvelib → repo
        Path.cwd() / "contracts",
        Path.cwd().parent / "contracts",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    raise FileNotFoundError("contracts/ directory not found; set CONTRACTS_ROOT")


def load_snapshot(major: int) -> dict[str, Any]:
    version, revision = MAJOR_REVISIONS[major]
    path = contracts_root() / revision / "snapshot.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source_version") != version:
        # Still usable; keep declared version from manifest pairing.
        pass
    return data


def _path_value(name: str) -> str:
    value = _PATH_PARAM_EXAMPLES.get(name)
    if value is None:
        value = _EXTRA_PATH.get(name, "example")
    return str(value)


def render_path(template: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return quote(str(_path_value(match.group(1))), safe="@._-")

    return _PATH_RE.sub(replace, template)


def _schema_example(schema: dict[str, Any] | None, *, name: str | None = None) -> Any:
    if not schema:
        return "example"
    if schema.get("default") is not None:
        return schema["default"]
    enum = schema.get("enum") or []
    if enum:
        return enum[0]
    if name is not None:
        hinted = _PATH_PARAM_EXAMPLES.get(name)
        if hinted is not None:
            return hinted
    typ = schema.get("type")
    if typ == "array":
        items = schema.get("items")
        return [_schema_example(items)] if items else []
    if typ == "object":
        props = schema.get("properties") or {}
        return {
            key: _schema_example(defn, name=key)
            for key, defn in props.items()
            if not (isinstance(defn, dict) and defn.get("optional"))
        }
    if typ == "boolean":
        return False
    if typ == "integer":
        minimum = schema.get("minimum")
        return int(minimum) if minimum is not None else 1
    if typ == "number":
        minimum = schema.get("minimum")
        return float(minimum) if minimum is not None else 1.0
    return "example"


def body_for(method: dict[str, Any], path_template: str) -> dict[str, Any]:
    path_names = set(_PATH_RE.findall(path_template))
    payload: dict[str, Any] = {}
    for parameter in method.get("parameters") or []:
        name = parameter.get("name")
        if not name or name in path_names:
            continue
        definition = parameter.get("definition") or {}
        if definition.get("optional"):
            continue
        payload[name] = _schema_example(definition, name=name)
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


def returns_type(method: dict[str, Any]) -> str:
    returns = method.get("returns") or {}
    if isinstance(returns, dict):
        return str(returns.get("type") or "")
    return ""


def looks_like_worker(path_template: str, verb: str) -> bool:
    if verb.upper() not in {"POST", "PUT"}:
        return False
    lowered = path_template.lower()
    return any(lowered.endswith(suffix) for suffix in _WORKER_SUFFIXES)


def classify_envelope(
    *,
    status: int,
    text: str,
    method: dict[str, Any],
    path_template: str,
    verb: str,
) -> str | None:
    """Return an extra critical bucket for 2xx envelope/returns mismatches, else None."""

    if not (200 <= status < 300) or verb.upper() == "HEAD":
        return None
    returns = method.get("returns") or {}
    rtype = returns_type(method)
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        return "empty_success_body"
    if not isinstance(payload, dict) or "data" not in payload:
        return "empty_success_body"
    data = payload.get("data")
    if rtype == "null":
        return None
    if rtype == "string":
        if data is None:
            return "wrong_returns_envelope"
        if looks_like_worker(path_template, verb):
            if not isinstance(data, str) or not _UPID_RE.fullmatch(data):
                return "wrong_returns_envelope"
            return None
        if isinstance(data, str):
            return None
        # Older PVE schemas sometimes mark list endpoints as opaque ``string``
        # (empty properties, no description). Accept non-null structured data.
        if isinstance(returns, dict) and not (
            returns.get("description") or returns.get("properties") or returns.get("enum")
        ):
            return None
        return "wrong_returns_envelope"
    if rtype in {"array", "object"} and data is None:
        return "wrong_returns_envelope"
    return None


def probe_major(
    client: httpx.Client,
    csrf: str,
    major: int,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    started = time.monotonic()
    apply = client.post("/ui/api/contract/apply", params={"major": major})
    apply.raise_for_status()
    applied = apply.json()

    by_verb: dict[str, Counter[str]] = defaultdict(Counter)
    failures: list[dict[str, Any]] = []
    method_results: list[dict[str, Any]] = []
    head_results: list[dict[str, Any]] = []
    get_paths: set[str] = set()

    methods: list[tuple[str, dict[str, Any]]] = [
        (path["path"], method)
        for path in snapshot.get("paths") or []
        for method in path.get("methods") or []
    ]
    order = {"GET": 0, "PUT": 1, "POST": 2, "DELETE": 3}
    methods.sort(key=lambda item: (order.get(str(item[1].get("verb", "")).upper(), 9), item[0]))

    for path_template, method in methods:
        verb = str(method.get("verb", "")).upper()
        url = f"/api2/json{render_path(path_template)}"
        headers = {"CSRFPreventionToken": csrf} if verb != "GET" else {}
        params = body_for(method, path_template)
        try:
            if verb == "GET":
                get_paths.add(path_template)
                response = client.get(url, headers=headers, params=params or None)
            elif verb == "PUT":
                response = client.put(url, data=params or {}, headers=headers)
            elif verb == "POST":
                response = client.post(url, data=params or {}, headers=headers)
            elif verb == "DELETE":
                # Proxmox accepts delete identifiers as form or query params.
                response = client.request("DELETE", url, data=params or {}, headers=headers)
            else:
                by_verb[verb or "UNKNOWN"]["exception"] += 1
                item = {
                    "verb": verb or "UNKNOWN",
                    "path": path_template,
                    "error": f"unsupported HTTP verb {verb!r}",
                    "bucket": "exception",
                    "ok": False,
                }
                failures.append(item)
                method_results.append(item)
                continue
        except Exception as exc:  # noqa: BLE001
            by_verb[verb]["exception"] += 1
            item = {
                "verb": verb,
                "path": path_template,
                "error": str(exc)[:200],
                "bucket": "exception",
                "ok": False,
            }
            failures.append(item)
            method_results.append(item)
            continue

        text = response.text
        bucket = classify(response.status_code, text)
        envelope = classify_envelope(
            status=response.status_code,
            text=text,
            method=method,
            path_template=path_template,
            verb=verb,
        )
        if envelope is not None:
            bucket = envelope
        by_verb[verb][bucket] += 1
        ok = bucket not in CRITICAL_BUCKETS
        item = {
            "verb": verb,
            "path": path_template,
            "status": response.status_code,
            "bucket": bucket,
            "ok": ok,
            "returns": returns_type(method),
        }
        if not ok:
            item["body"] = text[:240]
            failures.append(item)
        method_results.append(item)

    # Synthetic HEAD for every GET path (Starlette mirrors GET handlers).
    for path_template in sorted(get_paths):
        url = f"/api2/json{render_path(path_template)}"
        try:
            response = client.request("HEAD", url)
            text = response.text
            bucket = classify(response.status_code, text)
        except Exception as exc:  # noqa: BLE001
            bucket = "exception"
            text = str(exc)[:200]
            response = None
        by_verb["HEAD"][bucket] += 1
        ok = bucket not in CRITICAL_BUCKETS
        item = {
            "verb": "HEAD",
            "path": path_template,
            "status": getattr(response, "status_code", None),
            "bucket": bucket,
            "ok": ok,
            "synthetic": True,
        }
        if not ok:
            item["body"] = text[:240]
            item["error"] = text[:200]
            failures.append(item)
        head_results.append(item)

    version, _ = MAJOR_REVISIONS[major]
    declared = int(snapshot.get("method_count") or len(method_results))
    critical = len(failures)
    success_2xx = sum(c.get("success_2xx", 0) for c in by_verb.values())
    probed = len(method_results)
    empty_reasons: list[str] = []
    if not isinstance(applied, dict) or not applied:
        empty_reasons.append("apply response empty")
    elif applied.get("ok") is False:
        empty_reasons.append(f"apply not ok: {applied!r}")
    if declared <= 0:
        empty_reasons.append("declared method_count is 0")
    if probed <= 0:
        empty_reasons.append("no methods probed")
    if probed != declared:
        empty_reasons.append(
            f"incomplete coverage: probed {probed} of {declared} declared methods"
        )
    if success_2xx <= 0:
        empty_reasons.append("success_2xx count is 0")
    if empty_reasons:
        for reason in empty_reasons:
            failures.append(
                {
                    "verb": "META",
                    "path": f"major/{major}",
                    "bucket": "exception",
                    "ok": False,
                    "error": reason,
                }
            )
        critical = len(failures)

    verb_histogram = {
        verb: {
            "total": sum(counter.values()),
            "buckets": dict(counter),
        }
        for verb, counter in sorted(by_verb.items())
    }

    return {
        "major": major,
        "version": snapshot.get("source_version") or version,
        "apply": applied,
        "declared": declared,
        "probed": probed,
        "head_probed": len(head_results),
        "by_verb": {verb: dict(counter) for verb, counter in by_verb.items()},
        "verb_histogram": verb_histogram,
        "success_2xx": success_2xx,
        "client_4xx": sum(
            c.get("client_4xx", 0) + c.get("auth_401_403", 0) for c in by_verb.values()
        ),
        "failure_count": critical,
        "failures": failures,
        "ok": critical == 0,
        "time": time.monotonic() - started,
        "methods": method_results,
        "head_methods": head_results,
    }


def run_surface(
    *,
    majors: tuple[int, ...] = (6, 7, 8, 9),
    api_url: str | None = None,
) -> list[dict[str, Any]]:
    base = (api_url or os.environ.get("API_URL", "http://simulator:8006")).rstrip("/")
    user = os.environ.get("API_USER", "root@pam")
    password = os.environ.get("API_PASSWORD", "secret")
    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=base, timeout=60.0) as client:
        # Prefer env credentials over hard-coded login body.
        ticket = client.post(
            "/api2/json/access/ticket",
            data={"username": user, "password": password},
        )
        ticket.raise_for_status()
        data = ticket.json()["data"]
        client.cookies.set("PVEAuthCookie", data["ticket"])
        csrf = str(data["CSRFPreventionToken"])
        for major in majors:
            snapshot = load_snapshot(major)
            results.append(probe_major(client, csrf, major, snapshot))
    return results
