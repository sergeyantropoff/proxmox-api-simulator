"""Immutable normalized representation of Proxmox API contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


def canonical_json(value: BaseModel | Mapping[str, Any] | Sequence[Any]) -> bytes:
    """Serialize a JSON-compatible value deterministically as UTF-8."""

    data: Any
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json", exclude_none=True)
    else:
        data = value
    return json.dumps(
        data,
        default=_json_default,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _json_default(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Schema(FrozenModel):
    """Proxmox's JSON-Schema-like dialect with retained extensions."""

    type: str | None = None
    description: str | None = None
    properties: dict[str, Schema] = Field(default_factory=dict)
    items: Schema | None = None
    enum: tuple[JsonValue, ...] = ()
    optional: bool | None = None
    default: JsonValue = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    format: str | dict[str, JsonValue] | None = None
    extra: dict[str, JsonValue] = Field(default_factory=dict)


class Parameter(FrozenModel):
    name: str
    definition: Schema


class Permissions(FrozenModel):
    user: str | None = None
    description: str | None = None
    expression: dict[str, JsonValue] = Field(default_factory=dict)
    extra: dict[str, JsonValue] = Field(default_factory=dict)


class Method(FrozenModel):
    verb: str
    name: str
    description: str | None = None
    parameters: tuple[Parameter, ...] = ()
    returns: Schema = Field(default_factory=Schema)
    permissions: Permissions | None = None
    protected: bool = False
    allow_token: bool | None = None
    extra: dict[str, JsonValue] = Field(default_factory=dict)
    checksum: str


class PathContract(FrozenModel):
    path: str
    methods: tuple[Method, ...]
    extra: dict[str, JsonValue] = Field(default_factory=dict)


class Snapshot(FrozenModel):
    format_version: int = 1
    source_version: str
    retrieved_at: datetime
    raw_sha256: str
    paths: tuple[PathContract, ...]
    path_count: int
    method_count: int
    extra: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_counts_and_uniqueness(self) -> Self:
        if self.path_count != len(self.paths):
            raise ValueError("path_count does not match paths")
        methods = sum(len(path.methods) for path in self.paths)
        if self.method_count != methods:
            raise ValueError("method_count does not match methods")
        keys = [(path.path, method.verb) for path in self.paths for method in path.methods]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate path and method")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json(self)

    def checksum(self) -> str:
        return sha256(self.canonical_bytes())


class Manifest(FrozenModel):
    source_version: str
    raw_sha256: str
    snapshot_sha256: str
    path_count: int
    method_count: int
