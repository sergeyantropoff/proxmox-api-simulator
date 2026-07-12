"""Determinism and validation checks for normalized contracts."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.contracts.model import Snapshot, canonical_json
from app.contracts.normalize import normalize_snapshot
from app.contracts.source import ApiViewerParser

FIXTURE = Path(__file__).parents[1] / "fixtures" / "api-viewer" / "pve-9.2.3-version.json"
RETRIEVED_AT = datetime(2026, 7, 12, 20, 8, 59, tzinfo=UTC)


def make_snapshot() -> Snapshot:
    raw = FIXTURE.read_bytes()
    parsed = ApiViewerParser().parse(raw)
    snapshot, _ = normalize_snapshot(
        parsed, raw=raw, source_version="9.2.3", retrieved_at=RETRIEVED_AT
    )
    return snapshot


def test_normalization_is_deterministic_and_round_trips() -> None:
    first = make_snapshot()
    second = make_snapshot()

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.checksum() == second.checksum()
    assert Snapshot.model_validate_json(first.canonical_bytes()) == first
    assert first.paths[0].methods[0].checksum == second.paths[0].methods[0].checksum


def test_snapshot_validates_declared_counts() -> None:
    data = make_snapshot().model_dump(mode="json")
    data["method_count"] = 99

    with pytest.raises(ValidationError, match="method_count"):
        Snapshot.model_validate(data)


def test_unknown_schema_fields_are_retained() -> None:
    raw = json.dumps(
        [
            {
                "path": "/future",
                "info": {
                    "GET": {
                        "name": "future",
                        "returns": {"type": "string", "futureKeyword": {"x": 1}},
                    }
                },
            }
        ]
    ).encode()
    snapshot, _ = normalize_snapshot(
        ApiViewerParser().parse(raw),
        raw=raw,
        source_version="test",
        retrieved_at=RETRIEVED_AT,
    )

    assert snapshot.paths[0].methods[0].returns.extra["futureKeyword"] == {"x": 1}


@given(st.dictionaries(st.text(min_size=1), st.integers(), max_size=10))
def test_canonical_json_is_independent_of_mapping_order(values: dict[str, int]) -> None:
    reversed_values = dict(reversed(tuple(values.items())))

    assert canonical_json(values) == canonical_json(reversed_values)
