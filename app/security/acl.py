"""Capability-driven ACL evaluation with token privilege separation."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.model import Permissions


@dataclass(frozen=True, slots=True)
class Realm:
    name: str
    kind: str


@dataclass(frozen=True, slots=True)
class Principal:
    name: str
    realm: str


@dataclass(frozen=True, slots=True)
class Role:
    name: str
    privileges: frozenset[str]


@dataclass(frozen=True, slots=True)
class AclEntry:
    principal: str
    path: str
    privileges: frozenset[str]
    propagate: bool = True


def _ancestors(path: str) -> tuple[str, ...]:
    parts = [part for part in path.split("/") if part]
    return tuple(["/"] + ["/" + "/".join(parts[:index]) for index in range(1, len(parts) + 1)])


def effective_privileges(
    principal: str, path: str, entries: tuple[AclEntry, ...]
) -> frozenset[str]:
    privileges: set[str] = set()
    for entry in entries:
        if entry.principal != principal or entry.path not in _ancestors(path):
            continue
        if entry.path == path or entry.propagate:
            privileges.update(entry.privileges)
    return frozenset(privileges)


def authorize(
    principal: str,
    path: str,
    required: frozenset[str],
    entries: tuple[AclEntry, ...],
    *,
    token_privileges: frozenset[str] | None = None,
    require_all: bool = True,
) -> bool:
    privileges = effective_privileges(principal, path, entries)
    if token_privileges is not None:
        privileges &= token_privileges
    return required <= privileges if require_all else bool(required & privileges)


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    path: str
    privileges: frozenset[str]
    require_all: bool = True


def requirement_from_contract(
    permissions: Permissions | None, parameters: dict[str, str]
) -> CapabilityRequirement | None:
    if permissions is None or not permissions.expression:
        return None
    check = permissions.expression.get("check")
    if not isinstance(check, list) or len(check) < 3 or check[0] != "perm":
        return None
    raw_path = str(check[1])
    for name, value in parameters.items():
        raw_path = raw_path.replace(f"{{{name}}}", value).replace(f"<{name}>", value)
    raw_privileges = check[2]
    if not isinstance(raw_privileges, list):
        return None
    require_all = not (len(check) >= 4 and check[3] == "any")
    return CapabilityRequirement(
        raw_path, frozenset(str(item) for item in raw_privileges), require_all
    )
