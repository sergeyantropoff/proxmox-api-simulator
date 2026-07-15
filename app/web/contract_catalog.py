"""Lazy-loaded Proxmox API contract catalog grouped by major PVE release."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.api.openapi import contract_openapi_tag
from app.config import Settings
from app.contracts.examples import path_param_example, schema_example
from app.contracts.importer import RemoteSourceImporter
from app.contracts.model import Method, Parameter, Snapshot
from app.contracts.normalize import normalize_snapshot
from app.contracts.source import ApiViewerParser
from app.contracts.store import RevisionStore

_PATH_PARAM = re.compile(r"\{([^{}]+)\}")


@dataclass(frozen=True, slots=True)
class MajorReleaseMeta:
    major: int
    latest_version: str
    bundled_revision: str | None = None


@dataclass(frozen=True, slots=True)
class MajorRelease:
    major: int
    latest_version: str
    artifact_url: str
    bundled_revision: str | None = None


_MAJOR_METADATA: tuple[MajorReleaseMeta, ...] = (
    MajorReleaseMeta(
        major=6,
        latest_version="6.4-15",
        bundled_revision="96cd7121e75cdb3efd58f79ca988f6b235a2f28e6f7eae276ae243f65d8a6724",
    ),
    MajorReleaseMeta(
        major=7,
        latest_version="7.4-16",
        bundled_revision="2cf632fa6ea4939ca9cb7998ade688150db25b0684600f53ac0ca95730f1d99f",
    ),
    MajorReleaseMeta(
        major=8,
        latest_version="8.4.5",
        bundled_revision="fce6db0a784b3a9b447895895fc6ff4b4437c2dce82e5f3db99227af217726fa",
    ),
    MajorReleaseMeta(
        major=9,
        latest_version="9.2.3",
        bundled_revision="e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1",
    ),
)

_DEFAULT_ARTIFACT_URLS: dict[int, str] = {
    6: "https://pve.proxmox.com/pve-docs-6/api-viewer/apidoc.js",
    7: "https://pve.proxmox.com/pve-docs-7/api-viewer/apidoc.js",
    8: "https://pve.proxmox.com/pve-docs-8/api-viewer/apidoc.js",
    9: "https://pve.proxmox.com/pve-docs/api-viewer/apidoc.js",
}

_SNAPSHOT_CACHE: dict[int, Snapshot] = {}
_SNAPSHOT_LOCK = asyncio.Lock()
_DEFAULT_STORE = Path("contracts")


def _artifact_urls(settings: Settings | None) -> dict[int, str]:
    if settings is None:
        return dict(_DEFAULT_ARTIFACT_URLS)
    return settings.catalog_artifact_urls()


def get_major_releases(settings: Settings | None = None) -> tuple[MajorRelease, ...]:
    urls = _artifact_urls(settings)
    return tuple(
        MajorRelease(
            major=meta.major,
            latest_version=meta.latest_version,
            artifact_url=urls[meta.major],
            bundled_revision=meta.bundled_revision,
        )
        for meta in _MAJOR_METADATA
    )


def major_release(major: int, settings: Settings | None = None) -> MajorRelease:
    releases = {release.major: release for release in get_major_releases(settings)}
    try:
        return releases[major]
    except KeyError as error:
        raise ValueError(f"unsupported major version: {major}") from error


def list_majors(
    *,
    runtime_version: str | None,
    settings: Settings | None = None,
) -> dict[str, object]:
    return {
        "runtime_version": runtime_version,
        "majors": [
            {
                "major": release.major,
                "latest_version": release.latest_version,
                "artifact_url": release.artifact_url,
                "bundled": release.bundled_revision is not None,
            }
            for release in get_major_releases(settings)
        ],
    }


async def load_snapshot(
    major: int,
    store_root: Path | None = None,
    *,
    settings: Settings | None = None,
) -> Snapshot:
    if major in _SNAPSHOT_CACHE:
        return _SNAPSHOT_CACHE[major]
    async with _SNAPSHOT_LOCK:
        if major in _SNAPSHOT_CACHE:
            return _SNAPSHOT_CACHE[major]
        release = major_release(major, settings)
        store = RevisionStore(store_root or _DEFAULT_STORE)
        if release.bundled_revision is not None:
            snapshot_path = store.root / release.bundled_revision / "snapshot.json"
            if snapshot_path.is_file():
                snapshot = Snapshot.model_validate_json(snapshot_path.read_bytes())
                _SNAPSHOT_CACHE[major] = snapshot
                return snapshot
        existing = _find_cached_revision(store, release.latest_version)
        if existing is not None:
            snapshot = Snapshot.model_validate_json(existing.read_bytes())
            _SNAPSHOT_CACHE[major] = snapshot
            return snapshot
        raw = await RemoteSourceImporter(release.artifact_url).load()
        parsed = ApiViewerParser().parse(raw)
        snapshot, manifest = normalize_snapshot(
            parsed,
            raw=raw,
            source_version=release.latest_version,
            retrieved_at=datetime.now(UTC),
        )
        try:
            store.save(raw, snapshot, manifest)
        except OSError:
            pass
        _SNAPSHOT_CACHE[major] = snapshot
        return snapshot


def _find_cached_revision(store: RevisionStore, source_version: str) -> Path | None:
    if not store.root.is_dir():
        return None
    for revision in store.list():
        manifest = store.manifest(revision)
        if manifest.source_version == source_version:
            return store.root / revision / "snapshot.json"
    return None


def _catalog_entry_path(entry: dict[str, object]) -> str:
    return str(entry["path"])


def catalog_payload(
    snapshot: Snapshot,
    major: int,
    *,
    implemented_methods: frozenset[tuple[str, str]] | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for contract_path in snapshot.paths:
        tag = contract_openapi_tag(contract_path.path)
        methods = [
            {
                "verb": method.verb,
                "name": method.name,
                "description": method.description,
                "protected": method.protected,
                "implemented": (
                    (contract_path.path, method.verb.upper()) in implemented_methods
                    if implemented_methods is not None
                    else None
                ),
            }
            for method in contract_path.methods
        ]
        entry: dict[str, object] = {
            "path": contract_path.path,
            "methods": methods,
        }
        grouped.setdefault(tag, []).append(entry)
    categories: list[dict[str, object]] = []
    for tag in sorted(grouped):
        entries = grouped[tag]
        categories.append(
            {
                "tag": tag,
                "paths": sorted(entries, key=_catalog_entry_path),
            }
        )
    release = major_release(major, settings)
    return {
        "major": major,
        "source_version": snapshot.source_version,
        "latest_version": release.latest_version,
        "artifact_url": release.artifact_url,
        "bundled": release.bundled_revision is not None,
        "path_count": snapshot.path_count,
        "method_count": snapshot.method_count,
        "categories": categories,
    }


def _path_param_names(path: str) -> tuple[str, ...]:
    return tuple(match.group(1) for match in _PATH_PARAM.finditer(path))


def _parameter_payload(parameter: Parameter) -> dict[str, object]:
    schema = parameter.definition
    return {
        "name": parameter.name,
        "type": schema.type,
        "description": schema.description,
        "optional": bool(schema.optional),
        "enum": list(schema.enum),
        "example": schema_example(schema, name=parameter.name),
    }


def method_payload(
    snapshot: Snapshot,
    *,
    major: int,
    path: str,
    verb: str,
    runtime_version: str | None,
    implemented_methods: frozenset[tuple[str, str]] | None,
) -> dict[str, object]:
    contract_path = next((item for item in snapshot.paths if item.path == path), None)
    if contract_path is None:
        raise KeyError(path)
    method = next(
        (item for item in contract_path.methods if item.verb.upper() == verb.upper()),
        None,
    )
    if method is None:
        raise KeyError(verb)
    path_params = _path_param_names(path)
    path_fields = [
        _parameter_payload(parameter)
        for parameter in method.parameters
        if parameter.name in path_params
    ]
    for name in path_params:
        if name not in {field["name"] for field in path_fields}:
            path_fields.append(
                {
                    "name": name,
                    "type": "string",
                    "description": None,
                    "optional": False,
                    "enum": [],
                    "example": path_param_example(name) or name,
                }
            )
    body_fields = [
        _parameter_payload(parameter)
        for parameter in method.parameters
        if parameter.name not in path_params and "[n]" not in parameter.name
    ]
    indexed_fields = [
        _parameter_payload(parameter) for parameter in method.parameters if "[n]" in parameter.name
    ]
    body_example = _body_example(method, path_params)
    resolved_path = _resolve_path(path, path_fields)
    implemented = (
        (path, method.verb.upper()) in implemented_methods
        if implemented_methods is not None
        else None
    )
    return {
        "major": major,
        "source_version": snapshot.source_version,
        "runtime_version": runtime_version,
        "path": path,
        "verb": method.verb.upper(),
        "name": method.name,
        "description": method.description,
        "resolved_path": resolved_path,
        "path_fields": path_fields,
        "body_fields": body_fields,
        "indexed_fields": indexed_fields,
        "body_example": body_example,
        "implemented": implemented,
    }


def _resolve_path(path: str, path_fields: list[dict[str, object]]) -> str:
    resolved = path
    for field in path_fields:
        name = str(field["name"])
        example = field.get("example", name)
        resolved = resolved.replace(f"{{{name}}}", str(example))
    return resolved


def _body_example(method: Method, path_params: tuple[str, ...]) -> dict[str, object]:
    body: dict[str, object] = {}
    for parameter in method.parameters:
        if parameter.name in path_params:
            continue
        if "[n]" in parameter.name:
            concrete = parameter.name.replace("[n]", "0")
            if not parameter.definition.optional:
                body[concrete] = schema_example(parameter.definition, name=concrete)
            continue
        if parameter.definition.optional:
            continue
        body[parameter.name] = schema_example(parameter.definition, name=parameter.name)
    return body


@lru_cache(maxsize=1)
def default_store_root() -> Path:
    return _DEFAULT_STORE
