"""Catalog-scoped compatibility payload tests."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient

from app.compatibility import CompatibilityDimension, build_report
from app.config import Settings
from app.contracts.model import Method, PathContract, Schema, Snapshot
from app.main import create_app
from app.web.compatibility_catalog import compatibility_payload
from tests.unit.test_health import FakeDatabase

_BUNDLED = Path(
    "contracts/e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1/snapshot.json"
)
_PVE7 = Path(
    "contracts/2cf632fa6ea4939ca9cb7998ade688150db25b0684600f53ac0ca95730f1d99f/snapshot.json"
)


def _snapshot(source_version: str, path: str) -> Snapshot:
    method = Method(
        verb="GET",
        name="index",
        returns=Schema(type="object"),
        checksum="1" * 64,
    )
    return Snapshot(
        source_version=source_version,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_sha256="0" * 64,
        paths=(PathContract(path=path, methods=(method,)),),
        path_count=1,
        method_count=1,
    )


def test_catalog_compatibility_uses_selected_snapshot_version() -> None:
    runtime_snapshot = _snapshot("9.2.3", "/version")
    catalog_snapshot = _snapshot("7.4-16", "/nodes")
    runtime_report = build_report(
        runtime_snapshot,
        implemented=frozenset({("/version", "GET")}),
        dimensions={CompatibilityDimension.ROUTE_METHOD: frozenset({("/version", "GET")})},
    )
    payload = compatibility_payload(
        catalog_snapshot,
        7,
        implemented_methods=frozenset({("/nodes", "GET"), ("/version", "GET")}),
        runtime_report=runtime_report,
        runtime_version="9.2.3",
        settings=None,
    )
    assert payload["catalog_version"] == "7.4-16"
    assert payload["runtime_version"] == "9.2.3"
    assert payload["evidence_scope"] == "catalog"
    assert payload["total_declared"] == 1
    levels = cast(dict[str, dict[str, object]], payload["levels"])
    assert levels["implemented"]["count"] == 1


def test_catalog_compatibility_reuses_runtime_report_for_matching_version() -> None:
    runtime_snapshot = _snapshot("9.2.3", "/version")
    runtime_report = build_report(
        runtime_snapshot,
        implemented=frozenset({("/version", "GET")}),
        dimensions={CompatibilityDimension.ROUTE_METHOD: frozenset({("/version", "GET")})},
    )
    payload = compatibility_payload(
        runtime_snapshot,
        9,
        implemented_methods=frozenset({("/version", "GET")}),
        runtime_report=runtime_report,
        runtime_version="9.2.3",
        settings=None,
    )
    assert payload["catalog_version"] == "9.2.3"
    assert payload["evidence_scope"] == "full"


async def test_ui_compatibility_endpoint_follows_selected_major() -> None:
    if not _PVE7.is_file():
        pytest.skip("PVE 7 bundled contract is unavailable")
    settings = Settings(contract_snapshot=_BUNDLED)
    app = create_app(
        settings=settings,
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            major7 = await client.get("/ui/api/compatibility", params={"major": 7})
            major9 = await client.get("/ui/api/compatibility", params={"major": 9})
    assert major7.status_code == 200
    assert major9.status_code == 200
    body7 = major7.json()
    body9 = major9.json()
    pve7_snapshot = Snapshot.model_validate_json(_PVE7.read_bytes())
    assert body7["catalog_version"] == pve7_snapshot.source_version
    assert body9["catalog_version"] == "9.2.3"
    assert body7["total_declared"] == pve7_snapshot.method_count
    bundled = Snapshot.model_validate_json(_BUNDLED.read_bytes())
    assert body9["total_declared"] == bundled.method_count
    assert body7["major"] == 7
    assert body9["major"] == 9
    # Legacy aliases are kept in implemented_methods so older majors report full coverage.
    assert body7["levels"]["implemented"]["count"] == body7["total_declared"]
    assert body9["levels"]["implemented"]["count"] == body9["total_declared"]


async def test_ui_compatibility_covers_all_bundled_majors() -> None:
    settings = Settings(contract_snapshot=_BUNDLED, compatibility_evidence=None)
    app = create_app(
        settings=settings,
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for major in (6, 7, 8, 9):
                response = await client.get("/ui/api/compatibility", params={"major": major})
                assert response.status_code == 200
                body = response.json()
                assert body["levels"]["implemented"]["count"] == body["total_declared"]
