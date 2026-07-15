"""Runtime contract hot-swap tests."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.unit.test_health import FakeDatabase

_BUNDLED_9 = Path(
    "contracts/e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1/snapshot.json"
)
_EVIDENCE_9 = Path("evidence/pve-9.2.3.json")


def _app() -> FastAPI:
    settings = Settings(
        contract_snapshot=_BUNDLED_9,
        compatibility_evidence=_EVIDENCE_9,
    )
    return create_app(
        settings=settings,
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )


async def test_contract_apply_swaps_version_and_routes() -> None:
    app = _app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            before = await client.get("/api2/json/version")
            assert before.status_code == 200
            assert before.json()["data"]["version"] == "9.2.3"
            assert before.json()["data"]["release"] == "9.2"

            versions = await client.get("/ui/api/versions")
            assert versions.status_code == 200
            assert versions.json()["runtime_version"] == "9.2.3"

            applied = await client.post("/ui/api/contract/apply", params={"major": 7})
            assert applied.status_code == 200
            payload = applied.json()
            assert payload["ok"] is True
            assert payload["major"] == 7
            assert payload["runtime_version"] == "7.4-16"
            assert payload["path_count"] > 0
            assert payload["method_count"] > 0

            after = await client.get("/api2/json/version")
            assert after.status_code == 200
            assert after.json()["data"]["version"] == "7.4-16"
            assert after.json()["data"]["release"] == "7.4"

            versions_after = await client.get("/ui/api/versions")
            assert versions_after.json()["runtime_version"] == "7.4-16"

            # Still routed (handler or 501), not a missing route / 404.
            nodes = await client.get("/api2/json/nodes")
            assert nodes.status_code in {200, 401, 501}

            restored = await client.post("/ui/api/contract/apply", params={"major": 9})
            assert restored.status_code == 200
            assert restored.json()["runtime_version"] == "9.2.3"
            assert (await client.get("/api2/json/version")).json()["data"]["version"] == "9.2.3"


@pytest.mark.parametrize("major,version", [(6, "6.4-15"), (7, "7.4-16"), (8, "8.4.5")])
async def test_contract_apply_loads_per_major_verified_evidence(major: int, version: str) -> None:
    app = _app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            applied = await client.post("/ui/api/contract/apply", params={"major": major})
            assert applied.status_code == 200
            assert applied.json()["runtime_version"] == version
            report = await client.get("/admin/compatibility")
            body = report.json()
            assert body["source_version"] == version
            assert body["levels"]["verified"]["count"] == body["total_declared"]
            assert body["levels"]["verified"]["count"] > 0


async def test_contract_apply_requires_bootstrapped_contract() -> None:
    app = create_app(
        settings=Settings(contract_snapshot=None),
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/ui/api/contract/apply", params={"major": 7})
    assert response.status_code == 503
