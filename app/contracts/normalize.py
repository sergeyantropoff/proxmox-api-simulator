"""Normalize parsed API Viewer trees into stable contract models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from app.contracts.model import (
    JsonValue,
    Manifest,
    Method,
    Parameter,
    PathContract,
    Permissions,
    Schema,
    Snapshot,
    canonical_json,
    sha256,
)
from app.contracts.source import ParsedSource

SCHEMA_FIELDS = {
    "type",
    "description",
    "properties",
    "items",
    "enum",
    "optional",
    "default",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "format",
}
METHOD_FIELDS = {
    "allowtoken",
    "description",
    "method",
    "name",
    "parameters",
    "permissions",
    "protected",
    "returns",
}


def _json(value: Any) -> JsonValue:
    return cast(JsonValue, value)


def normalize_schema(raw: Mapping[str, Any] | None) -> Schema:
    source = raw or {}
    properties = source.get("properties", {})
    normalized_properties = {
        str(name): normalize_schema(cast(Mapping[str, Any], schema))
        for name, schema in cast(Mapping[str, Any], properties).items()
    }
    items = source.get("items")
    extra = {key: _json(value) for key, value in source.items() if key not in SCHEMA_FIELDS}
    return Schema(
        type=source.get("type"),
        description=source.get("description"),
        properties=normalized_properties,
        items=normalize_schema(cast(Mapping[str, Any], items))
        if isinstance(items, Mapping)
        else None,
        enum=tuple(_json(value) for value in source.get("enum", ())),
        optional=bool(source["optional"]) if "optional" in source else None,
        default=_json(source.get("default")),
        minimum=source.get("minimum"),
        maximum=source.get("maximum"),
        min_length=source.get("minLength"),
        max_length=source.get("maxLength"),
        pattern=source.get("pattern"),
        format=_json(source.get("format")),
        extra=extra,
    )


def normalize_permissions(raw: Mapping[str, Any] | None) -> Permissions | None:
    if raw is None:
        return None
    known = {"user", "description"}
    expression_keys = {"and", "or", "check", "userParam"}
    return Permissions(
        user=raw.get("user"),
        description=raw.get("description"),
        expression={key: _json(raw[key]) for key in expression_keys if key in raw},
        extra={
            key: _json(value) for key, value in raw.items() if key not in known | expression_keys
        },
    )


def normalize_method(verb: str, raw: Mapping[str, Any]) -> Method:
    parameters_raw = cast(Mapping[str, Any], raw.get("parameters", {})).get("properties", {})
    parameters = tuple(
        Parameter(name=str(name), definition=normalize_schema(cast(Mapping[str, Any], schema)))
        for name, schema in sorted(cast(Mapping[str, Any], parameters_raw).items())
    )
    values: dict[str, Any] = {
        "verb": verb.upper(),
        "name": str(raw.get("name", verb.lower())),
        "description": raw.get("description"),
        "parameters": parameters,
        "returns": normalize_schema(cast(Mapping[str, Any] | None, raw.get("returns"))),
        "permissions": normalize_permissions(
            cast(Mapping[str, Any] | None, raw.get("permissions"))
        ),
        "protected": bool(raw.get("protected", False)),
        "allow_token": bool(raw["allowtoken"]) if "allowtoken" in raw else None,
        "extra": {key: _json(value) for key, value in raw.items() if key not in METHOD_FIELDS},
    }
    checksum = sha256(canonical_json(values))
    return Method(**values, checksum=checksum)


def _walk(nodes: tuple[dict[str, Any], ...]) -> list[PathContract]:
    paths: list[PathContract] = []

    def visit(node: Mapping[str, Any]) -> None:
        info = node.get("info")
        path = node.get("path")
        if isinstance(info, Mapping) and isinstance(path, str):
            methods = tuple(
                normalize_method(str(verb), cast(Mapping[str, Any], method))
                for verb, method in sorted(info.items())
                if isinstance(method, Mapping)
            )
            extra = {
                key: _json(value)
                for key, value in node.items()
                if key not in {"children", "info", "leaf", "path", "text"}
            }
            paths.append(PathContract(path=path, methods=methods, extra=extra))
        for child in node.get("children", ()):
            if isinstance(child, Mapping):
                visit(child)

    for root in nodes:
        visit(root)
    return sorted(paths, key=lambda item: item.path)


def normalize_snapshot(
    parsed: ParsedSource, *, raw: bytes, source_version: str, retrieved_at: datetime
) -> tuple[Snapshot, Manifest]:
    paths = tuple(_walk(parsed.nodes))
    snapshot = Snapshot(
        source_version=source_version,
        retrieved_at=retrieved_at,
        raw_sha256=sha256(raw),
        paths=paths,
        path_count=len(paths),
        method_count=sum(len(path.methods) for path in paths),
        extra={"warning_count": len(parsed.warnings)},
    )
    manifest = Manifest(
        source_version=source_version,
        raw_sha256=snapshot.raw_sha256,
        snapshot_sha256=snapshot.checksum(),
        path_count=snapshot.path_count,
        method_count=snapshot.method_count,
    )
    return snapshot, manifest
