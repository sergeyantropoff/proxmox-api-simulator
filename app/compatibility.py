"""Evidence-based compatibility accounting and reporting."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from html import escape
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.contracts.model import Snapshot

MethodKey = tuple[str, str]


class CompatibilityDimension(StrEnum):
    ROUTE_METHOD = "route_method"
    INPUT_PARAMETERS = "input_parameters"
    PARAMETER_REQUIREDNESS = "parameter_requiredness"
    TYPES_CONSTRAINTS = "types_constraints"
    HTTP_STATUS = "http_status"
    JSON_STRUCTURE = "json_structure"
    RESPONSE_FIELD_TYPES = "response_field_types"
    RESPONSE_REQUIRED_FIELDS = "response_required_fields"
    HEADERS_COOKIES = "headers_cookies"
    STATE_SEMANTICS = "state_semantics"
    LONG_TASK_BEHAVIOR = "long_task_behavior"
    ERRORS_PROHIBITIONS = "errors_prohibitions"
    PERMISSIONS = "permissions"


EMPTY_DIMENSION_EVIDENCE: Mapping[CompatibilityDimension, frozenset[MethodKey]] = MappingProxyType(
    {dimension: frozenset() for dimension in CompatibilityDimension}
)


class MethodEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    verb: str
    dimensions: tuple[CompatibilityDimension, ...]
    sources: tuple[str, ...]
    observed: bool = True
    verified: bool = True

    @field_validator("sources")
    @classmethod
    def require_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("evidence record requires at least one source")
        return value

    @field_validator("verb")
    @classmethod
    def normalize_verb(cls, value: str) -> str:
        return value.upper()


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    format_version: int = 1
    profile: str
    source_version: str
    records: tuple[MethodEvidence, ...]

    @model_validator(mode="after")
    def reject_duplicate_methods(self) -> EvidenceManifest:
        keys = [(record.path, record.verb) for record in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("evidence manifest contains duplicate methods")
        return self

    def dimension_map(self) -> Mapping[CompatibilityDimension, frozenset[MethodKey]]:
        evidence: dict[CompatibilityDimension, set[MethodKey]] = {
            dimension: set() for dimension in CompatibilityDimension
        }
        for record in self.records:
            key = (record.path, record.verb.upper())
            for dimension in record.dimensions:
                evidence[dimension].add(key)
        return MappingProxyType(
            {dimension: frozenset(methods) for dimension, methods in evidence.items()}
        )

    def observed_methods(self) -> frozenset[MethodKey]:
        return frozenset(
            (record.path, record.verb.upper()) for record in self.records if record.observed
        )

    def verified_methods(self) -> frozenset[MethodKey]:
        return frozenset(
            (record.path, record.verb.upper()) for record in self.records if record.verified
        )


def load_evidence_manifest(path: Path) -> EvidenceManifest:
    return EvidenceManifest.model_validate_json(path.read_bytes())


def evidence_dir(settings: object | None = None) -> Path:
    """Directory that holds per-version ``pve-{version}.json`` ledgers."""

    evidence = getattr(settings, "compatibility_evidence", None) if settings is not None else None
    if isinstance(evidence, Path) and evidence.name:
        return evidence.resolve().parent
    return Path("evidence")


def resolve_evidence_path(source_version: str, settings: object | None = None) -> Path | None:
    """Resolve the evidence manifest for a contract ``source_version``.

    Preference order:
    1. ``evidence/pve-{source_version}.json`` next to the configured evidence file
       (or ``./evidence`` when unset)
    2. ``settings.compatibility_evidence`` when its embedded ``source_version`` matches
    """

    candidate = evidence_dir(settings) / f"pve-{source_version}.json"
    if candidate.is_file():
        return candidate
    configured = getattr(settings, "compatibility_evidence", None) if settings is not None else None
    if not isinstance(configured, Path) or not configured.is_file():
        return None
    manifesto = load_evidence_manifest(configured)
    if manifesto.source_version == source_version:
        return configured
    return None


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    source_version: str
    declared: frozenset[MethodKey]
    schema_only: frozenset[MethodKey]
    implemented: frozenset[MethodKey]
    observed: frozenset[MethodKey]
    verified: frozenset[MethodKey]
    dimensions: Mapping[CompatibilityDimension, frozenset[MethodKey]]
    incompatible: frozenset[MethodKey]
    regressions: frozenset[MethodKey]

    def as_json(self) -> dict[str, object]:
        levels = {
            "declared": self.declared,
            "schema_only": self.schema_only,
            "implemented": self.implemented,
            "observed": self.observed,
            "verified": self.verified,
        }
        total = len(self.declared)
        dimension_sets = tuple(self.dimensions.values())
        fully_evidenced = (
            dimension_sets[0].intersection(*dimension_sets[1:]) if dimension_sets else frozenset()
        )
        evidenced = frozenset().union(*dimension_sets)
        fully_compatible = fully_evidenced & self.implemented
        partially_compatible = (evidenced & self.implemented) - fully_compatible - self.incompatible
        return {
            "source_version": self.source_version,
            "total_declared": total,
            "levels": {
                name: {
                    "count": len(methods),
                    "score": len(methods) / total if total else 1.0,
                    "methods": [f"{verb} {path}" for path, verb in sorted(methods)],
                }
                for name, methods in levels.items()
            },
            "groups": self._groups(),
            "dimension_groups": self._dimension_groups(),
            "classifications": {
                "fully_compatible": self._method_names(fully_compatible),
                "partially_compatible": self._method_names(partially_compatible),
                "incompatible": self._method_names(self.incompatible),
                "regressions": self._method_names(self.regressions),
                "unsupported": self._method_names(self.schema_only),
            },
            "dimensions": {
                dimension.value: {
                    "count": len(methods),
                    "score": len(methods) / total if total else 1.0,
                    "methods": [f"{verb} {path}" for path, verb in sorted(methods)],
                }
                for dimension, methods in self.dimensions.items()
            },
        }

    @staticmethod
    def _method_names(methods: frozenset[MethodKey]) -> list[str]:
        return [f"{verb} {path}" for path, verb in sorted(methods)]

    def canonical_json(self) -> str:
        return json.dumps(self.as_json(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def _groups(self) -> dict[str, dict[str, int]]:
        groups: dict[str, dict[str, int]] = {}
        for path, verb in self.declared:
            group = path.strip("/").split("/", 1)[0] or "root"
            counters = groups.setdefault(group, {"declared": 0, "implemented": 0, "verified": 0})
            counters["declared"] += 1
            counters["implemented"] += int((path, verb) in self.implemented)
            counters["verified"] += int((path, verb) in self.verified)
        return dict(sorted(groups.items()))

    def _dimension_groups(self) -> dict[str, dict[str, int]]:
        groups: dict[str, dict[str, int]] = {}
        for dimension, methods in self.dimensions.items():
            for path, _verb in methods:
                group = path.strip("/").split("/", 1)[0] or "root"
                counters = groups.setdefault(
                    group, {item.value: 0 for item in CompatibilityDimension}
                )
                counters[dimension.value] += 1
        return dict(sorted(groups.items()))

    def as_markdown(self) -> str:
        levels = {
            "declared": self.declared,
            "schema_only": self.schema_only,
            "implemented": self.implemented,
            "observed": self.observed,
            "verified": self.verified,
        }
        total = len(self.declared)
        lines = [
            "# Compatibility report",
            "",
            "| Level | Count | Score |",
            "|---|---:|---:|",
        ]
        for name, methods in levels.items():
            score = len(methods) / total if total else 1.0
            lines.append(f"| {name} | {len(methods)} | {score:.2%} |")
        lines.extend(
            [
                "",
                "## Compatibility dimensions",
                "",
                "| Dimension | Verified methods | Score |",
                "|---|---:|---:|",
            ]
        )
        for dimension, methods in self.dimensions.items():
            score = len(methods) / total if total else 1.0
            lines.append(f"| {dimension.value} | {len(methods)} | {score:.2%} |")
        return "\n".join(lines)

    def as_html(self) -> str:
        rows = "".join(
            "<tr>"
            f"<td>{escape(dimension.value)}</td>"
            f"<td>{len(methods)}</td>"
            f"<td>{(len(methods) / len(self.declared) if self.declared else 1.0):.2%}</td>"
            "</tr>"
            for dimension, methods in self.dimensions.items()
        )
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            "<title>Compatibility report</title><body>"
            f"<h1>PVE {escape(self.source_version)} compatibility</h1>"
            "<table><thead><tr><th>Dimension</th><th>Verified methods</th>"
            f"<th>Score</th></tr></thead><tbody>{rows}</tbody></table></body></html>"
        )


def build_report(
    snapshot: Snapshot,
    *,
    implemented: frozenset[MethodKey] = frozenset(),
    observed: frozenset[MethodKey] = frozenset(),
    verified: frozenset[MethodKey] = frozenset(),
    dimensions: Mapping[CompatibilityDimension, frozenset[MethodKey]] = EMPTY_DIMENSION_EVIDENCE,
    incompatible: frozenset[MethodKey] = frozenset(),
    regressions: frozenset[MethodKey] = frozenset(),
) -> CompatibilityReport:
    declared = frozenset(
        (path.path, method.verb.upper()) for path in snapshot.paths for method in path.methods
    )
    for name, evidence in {
        "implemented": implemented,
        "observed": observed,
        "verified": verified,
        "incompatible": incompatible,
        "regressions": regressions,
    }.items():
        if not evidence <= declared:
            raise ValueError(f"{name} evidence references undeclared methods")
    resolved_dimensions = {
        dimension: frozenset(dimensions.get(dimension, frozenset()))
        for dimension in CompatibilityDimension
    }
    for dimension, evidence in resolved_dimensions.items():
        if not evidence <= declared:
            raise ValueError(f"{dimension.value} evidence references undeclared methods")
    return CompatibilityReport(
        source_version=snapshot.source_version,
        declared=declared,
        schema_only=declared - implemented,
        implemented=implemented,
        observed=observed,
        verified=verified,
        dimensions=MappingProxyType(resolved_dimensions),
        incompatible=incompatible,
        regressions=regressions,
    )
