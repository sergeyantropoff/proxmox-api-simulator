"""Catalog-scoped compatibility summaries for the web console."""

from __future__ import annotations

from app.compatibility import CompatibilityDimension, CompatibilityReport, build_report
from app.config import Settings
from app.contracts.model import Snapshot
from app.web.contract_catalog import major_release

MethodKey = tuple[str, str]


def compatibility_payload(
    snapshot: Snapshot,
    major: int,
    *,
    implemented_methods: frozenset[MethodKey] | None,
    runtime_report: CompatibilityReport | None,
    runtime_version: str | None,
    settings: Settings | None,
) -> dict[str, object]:
    """Build a compatibility summary for the selected catalog major."""

    declared = frozenset(
        (contract_path.path, method.verb.upper())
        for contract_path in snapshot.paths
        for method in contract_path.methods
    )
    implemented = (implemented_methods or frozenset()) & declared

    if runtime_report is not None and runtime_report.source_version == snapshot.source_version:
        payload = runtime_report.as_json()
        evidence_scope = "full"
    else:
        dimensions: dict[CompatibilityDimension, frozenset[MethodKey]] = {
            CompatibilityDimension.ROUTE_METHOD: declared,
        }
        if runtime_report is not None:
            for dimension, methods in runtime_report.dimensions.items():
                if dimension == CompatibilityDimension.ROUTE_METHOD:
                    continue
                dimensions[dimension] = methods & declared
        else:
            for dimension in CompatibilityDimension:
                if dimension != CompatibilityDimension.ROUTE_METHOD:
                    dimensions[dimension] = frozenset()

        empty: frozenset[MethodKey] = frozenset()
        if runtime_report is None:
            observed = empty
            verified = empty
            incompatible = empty
            regressions = empty
        else:
            observed = runtime_report.observed & declared
            verified = runtime_report.verified & declared
            incompatible = runtime_report.incompatible & declared
            regressions = runtime_report.regressions & declared
        catalog_report = build_report(
            snapshot,
            implemented=implemented,
            observed=observed,
            verified=verified,
            dimensions=dimensions,
            incompatible=incompatible,
            regressions=regressions,
        )
        payload = catalog_report.as_json()
        evidence_scope = "catalog"

    release = major_release(major, settings)
    payload["major"] = major
    payload["catalog_version"] = snapshot.source_version
    payload["latest_version"] = release.latest_version
    payload["runtime_version"] = runtime_version
    payload["evidence_scope"] = evidence_scope
    return payload
