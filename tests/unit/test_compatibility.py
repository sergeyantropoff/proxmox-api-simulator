"""Compatibility accounting tests."""

from datetime import UTC, datetime

import pytest

from app.compatibility import build_report
from app.contracts.model import Method, PathContract, Schema, Snapshot


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
