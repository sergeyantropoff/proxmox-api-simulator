"""Deterministic semantic differences between normalized snapshots."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.contracts.model import Method, Parameter, PathContract, Snapshot


class Severity(StrEnum):
    BREAKING = "breaking"
    NON_BREAKING = "non-breaking"
    DOCUMENTATION = "documentation"


@dataclass(frozen=True, slots=True, order=True)
class Change:
    path: str
    method: str
    category: str
    severity: Severity
    detail: str
    before: str | None = None
    after: str | None = None


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _methods(snapshot: Snapshot) -> dict[tuple[str, str], Method]:
    return {(path.path, method.verb): method for path in snapshot.paths for method in path.methods}


def _paths(snapshot: Snapshot) -> dict[str, PathContract]:
    return {path.path: path for path in snapshot.paths}


def compare_snapshots(before: Snapshot, after: Snapshot) -> tuple[Change, ...]:
    changes: list[Change] = []
    old_paths, new_paths = _paths(before), _paths(after)
    for path in sorted(old_paths.keys() - new_paths.keys()):
        changes.append(Change(path, "", "path", Severity.BREAKING, "path removed"))
    for path in sorted(new_paths.keys() - old_paths.keys()):
        changes.append(Change(path, "", "path", Severity.NON_BREAKING, "path added"))

    old_methods, new_methods = _methods(before), _methods(after)
    for path, verb in sorted(old_methods.keys() - new_methods.keys()):
        changes.append(Change(path, verb, "method", Severity.BREAKING, "method removed"))
    for path, verb in sorted(new_methods.keys() - old_methods.keys()):
        changes.append(Change(path, verb, "method", Severity.NON_BREAKING, "method added"))
    for key in sorted(old_methods.keys() & new_methods.keys()):
        _compare_method(key, old_methods[key], new_methods[key], changes)
    return tuple(sorted(changes))


def _compare_method(
    key: tuple[str, str], before: Method, after: Method, changes: list[Change]
) -> None:
    path, verb = key
    if before.description != after.description:
        changes.append(
            Change(
                path,
                verb,
                "documentation",
                Severity.DOCUMENTATION,
                "description changed",
                before.description,
                after.description,
            )
        )
    if before.permissions != after.permissions:
        changes.append(
            Change(
                path,
                verb,
                "permissions",
                Severity.BREAKING,
                "permissions changed",
                _stable(before.permissions.model_dump(mode="json") if before.permissions else None),
                _stable(after.permissions.model_dump(mode="json") if after.permissions else None),
            )
        )
    _compare_parameters(path, verb, before.parameters, after.parameters, changes)
    _compare_schema(
        path,
        verb,
        "returns",
        before.returns.model_dump(mode="json"),
        after.returns.model_dump(mode="json"),
        changes,
    )


def _compare_parameters(
    path: str,
    verb: str,
    before: tuple[Parameter, ...],
    after: tuple[Parameter, ...],
    changes: list[Change],
) -> None:
    old = {parameter.name: parameter for parameter in before}
    new = {parameter.name: parameter for parameter in after}
    for name in sorted(old.keys() - new.keys()):
        changes.append(Change(path, verb, "parameter", Severity.BREAKING, f"removed: {name}"))
    for name in sorted(new.keys() - old.keys()):
        severity = Severity.NON_BREAKING if new[name].definition.optional else Severity.BREAKING
        changes.append(Change(path, verb, "parameter", severity, f"added: {name}"))
    for name in sorted(old.keys() & new.keys()):
        _compare_schema(
            path,
            verb,
            f"parameter:{name}",
            old[name].definition.model_dump(mode="json"),
            new[name].definition.model_dump(mode="json"),
            changes,
        )


def _compare_schema(
    path: str,
    verb: str,
    label: str,
    before: dict[str, Any],
    after: dict[str, Any],
    changes: list[Change],
) -> None:
    groups = {
        "schema": {"type", "properties", "items", "enum", "format", "pattern"},
        "default": {"default", "optional"},
        "constraint": {"minimum", "maximum", "min_length", "max_length"},
        "documentation": {"description"},
    }
    for category, fields in groups.items():
        old = {field: before.get(field) for field in fields}
        new = {field: after.get(field) for field in fields}
        if old != new:
            severity = Severity.DOCUMENTATION if category == "documentation" else Severity.BREAKING
            changes.append(
                Change(
                    path,
                    verb,
                    category,
                    severity,
                    f"{label} {category} changed",
                    _stable(old),
                    _stable(new),
                )
            )


def render_json(changes: tuple[Change, ...]) -> str:
    return json.dumps(
        [
            {
                "after": change.after,
                "before": change.before,
                "category": change.category,
                "detail": change.detail,
                "method": change.method,
                "path": change.path,
                "severity": change.severity,
            }
            for change in changes
        ],
        ensure_ascii=False,
        indent=2,
    )


def render_text(changes: tuple[Change, ...]) -> str:
    return "\n".join(
        (
            f"{change.severity}: {change.method} {change.path} [{change.category}] {change.detail}"
        ).strip()
        for change in changes
    )


def render_markdown(changes: tuple[Change, ...]) -> str:
    lines = [
        "# API contract diff",
        "",
        "| Severity | Method | Path | Category | Detail |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        (
            f"| {change.severity} | {change.method} | `{change.path}` | "
            f"{change.category} | {change.detail} |"
        )
        for change in changes
    )
    return "\n".join(lines)


def render_html(changes: tuple[Change, ...]) -> str:
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(value))}</td>"
            for value in (
                change.severity,
                change.method,
                change.path,
                change.category,
                change.detail,
            )
        )
        + "</tr>"
        for change in changes
    )
    return (
        f"<!doctype html><meta charset=utf-8><title>API contract diff</title><table>{rows}</table>"
    )


def has_breaking_changes(changes: tuple[Change, ...]) -> bool:
    return any(change.severity is Severity.BREAKING for change in changes)
