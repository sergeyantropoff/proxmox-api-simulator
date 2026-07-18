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
from app.contracts.examples import path_param_example, schema_example, wire_param_name
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


def _parameter_payload(parameter: Parameter, *, wire_name: str | None = None) -> dict[str, object]:
    schema = parameter.definition
    name = wire_name or parameter.name
    typetext = schema.extra.get("typetext")
    payload: dict[str, object] = {
        "name": name,
        "type": schema.type,
        "description": schema.description,
        "optional": bool(schema.optional),
        "enum": list(schema.enum),
        "example": schema_example(schema, name=parameter.name),
    }
    if wire_name and wire_name != parameter.name:
        payload["template"] = parameter.name
    if isinstance(schema.format, str):
        payload["format"] = schema.format
    if isinstance(typetext, str) and typetext:
        payload["typetext"] = typetext
    return payload


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
    contract_body_fields = [
        _parameter_payload(parameter)
        for parameter in method.parameters
        if parameter.name not in path_params and "[n]" not in parameter.name
    ]
    # Contract uses foo[n]; the wire form is foo0..fooN — seed the console with foo0.
    indexed_fields = [
        _parameter_payload(parameter, wire_name=wire_param_name(parameter.name))
        for parameter in method.parameters
        if "[n]" in parameter.name
    ]
    body_example = _body_example(method, path_params)
    # Flatten nested scalars from body_example (and nested field examples) into PARAMS.
    body_fields = _body_fields_with_nested(contract_body_fields, body_example)
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
    """Minimal request body: required parameters only, Proxmox wire names/values."""

    body: dict[str, object] = {}
    for parameter in method.parameters:
        if parameter.name in path_params:
            continue
        if parameter.definition.optional:
            continue
        wire = wire_param_name(parameter.name)
        body[wire] = schema_example(parameter.definition, name=parameter.name)
    return body


def _leaf_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _body_fields_from_example(body_example: dict[str, object] | None) -> list[dict[str, object]]:
    """PARAM inputs derived from body_example, including nested scalar paths."""

    if not isinstance(body_example, dict) or not body_example:
        return []
    inner: object = body_example
    # Soft unwrap a single root object envelope (Engine-style), never a scalar/list.
    if len(body_example) == 1:
        only = next(iter(body_example.values()))
        if isinstance(only, dict):
            inner = only
    if not isinstance(inner, dict):
        return []

    fields: list[dict[str, object]] = []

    def _walk(prefix: str, value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                _walk(path, child)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                path = f"{prefix}.{index}" if prefix else str(index)
                _walk(path, child)
            return
        fields.append(
            {
                "name": prefix,
                "type": _leaf_type(value),
                "description": prefix,
                "optional": True,
                "enum": [],
                "example": value,
            }
        )

    _walk("", inner)
    return fields


def _body_fields_with_nested(
    contract_fields: list[dict[str, object]],
    body_example: dict[str, object],
) -> list[dict[str, object]]:
    """Merge contract PARAMS with nested scalar paths from body_example."""

    example_fields = _body_fields_from_example(body_example)
    nested_tops = {
        str(item["name"]).split(".", 1)[0] for item in example_fields if "." in str(item["name"])
    }
    contract_by_name = {str(item["name"]): item for item in contract_fields}
    merged: list[dict[str, object]] = []
    seen: set[str] = set()

    for item in example_fields:
        name = str(item["name"])
        top = name.split(".", 1)[0]
        parent = contract_by_name.get(name) or contract_by_name.get(top)
        row = dict(item)
        if parent is not None:
            row["optional"] = bool(parent.get("optional"))
            description = parent.get("description")
            if isinstance(description, str) and description:
                row["description"] = description
            typetext = parent.get("typetext")
            if isinstance(typetext, str) and typetext:
                row["typetext"] = typetext
            fmt = parent.get("format")
            if isinstance(fmt, str) and fmt:
                row["format"] = fmt
        else:
            # body_example is required-only — treat uncovered leaves as required.
            row["optional"] = False
        merged.append(row)
        seen.add(name)

    for field in contract_fields:
        name = str(field["name"])
        if name in nested_tops or name in seen:
            continue
        example = field.get("example")
        if isinstance(example, dict | list):
            nested = _body_fields_from_example({name: example})
            if nested:
                for item in nested:
                    nested_name = str(item["name"])
                    if nested_name in seen:
                        continue
                    row = dict(item)
                    row["optional"] = bool(field.get("optional"))
                    description = field.get("description")
                    if isinstance(description, str) and description:
                        row["description"] = description
                    merged.append(row)
                    seen.add(nested_name)
                continue
            # Empty object/array examples stay as a top-level PARAM.
        merged.append(field)
        seen.add(name)
    return merged


@lru_cache(maxsize=1)
def default_store_root() -> Path:
    return _DEFAULT_STORE
