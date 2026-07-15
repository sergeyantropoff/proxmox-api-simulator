"""Compatibility accounting tests."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr

from app.compatibility import (
    CompatibilityDimension,
    EvidenceManifest,
    build_report,
    resolve_evidence_path,
)
from app.config import Settings
from app.contracts.model import Method, PathContract, Schema, Snapshot
from app.contracts.runtime import build_compatibility_for_snapshot
from app.handlers.core import build_core_handlers


def snapshot() -> Snapshot:
    methods = (
        Method(
            verb="GET",
            name="version",
            returns=Schema(type="object"),
            checksum="1" * 64,
        ),
        Method(
            verb="POST",
            name="update",
            returns=Schema(type="null"),
            checksum="2" * 64,
        ),
    )
    return Snapshot(
        source_version="9.2.3",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_sha256="0" * 64,
        paths=(PathContract(path="/nodes/{node}", methods=methods),),
        path_count=1,
        method_count=2,
    )


def test_report_scores_levels_and_groups_independently() -> None:
    report = build_report(
        snapshot(),
        implemented=frozenset({("/nodes/{node}", "GET")}),
        observed=frozenset({("/nodes/{node}", "GET"), ("/nodes/{node}", "POST")}),
        verified=frozenset({("/nodes/{node}", "GET")}),
    )
    data = report.as_json()

    assert data["total_declared"] == 2
    levels = data["levels"]
    assert isinstance(levels, dict)
    assert levels["implemented"]["score"] == 0.5
    assert levels["observed"]["score"] == 1.0
    assert data["groups"] == {"nodes": {"declared": 2, "implemented": 1, "verified": 1}}
    assert "| implemented | 1 | 50.00% |" in report.as_markdown()


def test_report_rejects_unbound_evidence() -> None:
    with pytest.raises(ValueError, match="undeclared"):
        build_report(snapshot(), verified=frozenset({("/missing", "GET")}))


def test_all_thirteen_dimensions_have_independent_evidence_and_renderers() -> None:
    method = frozenset({("/nodes/{node}", "GET")})
    report = build_report(
        snapshot(),
        implemented=method,
        dimensions={dimension: method for dimension in CompatibilityDimension},
    )

    payload = report.as_json()
    dimensions = cast(dict[str, dict[str, object]], payload["dimensions"])
    assert list(dimensions) == [dimension.value for dimension in CompatibilityDimension]
    assert len(dimensions) == 13
    assert all(item["count"] == 1 for item in dimensions.values())
    assert payload["dimension_groups"]
    classifications = cast(dict[str, list[str]], payload["classifications"])
    assert classifications["fully_compatible"] == ["GET /nodes/{node}"]
    assert not classifications["partially_compatible"]
    assert "| permissions | 1 |" in report.as_markdown()
    assert "<td>long_task_behavior</td><td>1</td>" in report.as_html()
    assert report.canonical_json() == report.canonical_json()


def test_dimension_evidence_must_reference_declared_method() -> None:
    with pytest.raises(ValueError, match="permissions evidence"):
        build_report(
            snapshot(),
            dimensions={CompatibilityDimension.PERMISSIONS: frozenset({("/missing", "GET")})},
        )


def test_evidence_manifest_requires_provenance_and_unique_methods() -> None:
    manifest = EvidenceManifest.model_validate(
        {
            "profile": "pve-9.2",
            "source_version": "9.2.3",
            "records": [
                {
                    "path": "/nodes/{node}",
                    "verb": "GET",
                    "dimensions": ["http_status", "json_structure"],
                    "sources": ["tests/compatibility/test_proxmoxer.py"],
                }
            ],
        }
    )
    evidence = manifest.dimension_map()
    assert evidence[CompatibilityDimension.HTTP_STATUS] == frozenset({("/nodes/{node}", "GET")})
    assert not evidence[CompatibilityDimension.PERMISSIONS]
    assert manifest.verified_methods() == frozenset({("/nodes/{node}", "GET")})
    assert manifest.observed_methods() == frozenset({("/nodes/{node}", "GET")})

    duplicate = manifest.model_dump(mode="json")
    duplicate["records"].append(duplicate["records"][0])
    with pytest.raises(ValueError, match="duplicate methods"):
        EvidenceManifest.model_validate(duplicate)


def test_resolve_evidence_path_prefers_per_version_ledger() -> None:
    settings = Settings(compatibility_evidence=Path("evidence/pve-9.2.3.json"))
    assert resolve_evidence_path("7.4-16", settings) == Path("evidence/pve-7.4-16.json").resolve()
    assert resolve_evidence_path("9.2.3", settings) == Path("evidence/pve-9.2.3.json").resolve()


def test_build_compatibility_wires_verified_from_version_ledger() -> None:
    snapshot = Snapshot.model_validate_json(
        Path(
            "contracts/e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1/"
            "snapshot.json"
        ).read_bytes()
    )
    settings = Settings(
        contract_snapshot=Path(
            "contracts/e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1/"
            "snapshot.json"
        ),
        compatibility_evidence=Path("evidence/pve-9.2.3.json"),
        ticket_signing_key=SecretStr("x" * 32),
    )
    handlers = build_core_handlers(settings)
    report = build_compatibility_for_snapshot(snapshot, handlers, settings)
    data = report.as_json()
    levels = cast(dict[str, dict[str, object]], data["levels"])
    assert levels["verified"]["count"] == data["total_declared"]
    assert levels["observed"]["count"] == data["total_declared"]
    assert levels["implemented"]["count"] == data["total_declared"]
