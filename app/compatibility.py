"""Evidence-based compatibility accounting and reporting."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.model import Snapshot

MethodKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    source_version: str
    declared: frozenset[MethodKey]
    schema_only: frozenset[MethodKey]
    implemented: frozenset[MethodKey]
    observed: frozenset[MethodKey]
    verified: frozenset[MethodKey]

    def as_json(self) -> dict[str, object]:
        levels = {
            "declared": self.declared,
            "schema_only": self.schema_only,
            "implemented": self.implemented,
            "observed": self.observed,
            "verified": self.verified,
        }
        total = len(self.declared)
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
        }

    def _groups(self) -> dict[str, dict[str, int]]:
        groups: dict[str, dict[str, int]] = {}
        for path, verb in self.declared:
            group = path.strip("/").split("/", 1)[0] or "root"
            counters = groups.setdefault(group, {"declared": 0, "implemented": 0, "verified": 0})
            counters["declared"] += 1
            counters["implemented"] += int((path, verb) in self.implemented)
            counters["verified"] += int((path, verb) in self.verified)
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
        return "\n".join(lines)


def build_report(
    snapshot: Snapshot,
    *,
    implemented: frozenset[MethodKey] = frozenset(),
    observed: frozenset[MethodKey] = frozenset(),
    verified: frozenset[MethodKey] = frozenset(),
) -> CompatibilityReport:
    declared = frozenset(
        (path.path, method.verb) for path in snapshot.paths for method in path.methods
    )
    for name, evidence in {
        "implemented": implemented,
        "observed": observed,
        "verified": verified,
    }.items():
        if not evidence <= declared:
            raise ValueError(f"{name} evidence references undeclared methods")
    return CompatibilityReport(
        source_version=snapshot.source_version,
        declared=declared,
        schema_only=declared - implemented,
        implemented=implemented,
        observed=observed,
        verified=verified,
    )
