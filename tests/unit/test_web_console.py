"""Web console route tests."""

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.unit.test_health import FakeDatabase

_BUNDLED = Path(
    "contracts/e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1/snapshot.json"
)


async def test_root_console_is_served() -> None:
    app = create_app(database_factory=lambda _settings: FakeDatabase(True), worker_factories=())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/")
    assert response.status_code == 200
    assert "Proxmox API Emulator" in response.text
    assert 'id="catalog-drawer"' in response.text
    assert "catalog-drawer" in response.text
    assert 'id="help-drawer"' in response.text
    assert 'id="help-badge"' in response.text
    assert 'id="data-badge"' in response.text
    assert 'id="data-drawer"' in response.text
    assert "data-badge-btn" in response.text
    assert 'id="endpoints-badge-count"' in response.text
    assert 'id="endpoints-drawer-count"' in response.text
    assert 'id="ui-modal"' in response.text
    assert 'role="alertdialog"' in response.text
    assert "Request body" in response.text


async def test_ui_method_nodes_is_implemented() -> None:
    settings = Settings(contract_snapshot=_BUNDLED)
    app = create_app(
        settings=settings,
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            method = await client.get(
                "/ui/api/method",
                params={"major": 7, "path": "/nodes", "verb": "GET"},
            )
            assert method.status_code == 200
            assert method.json()["implemented"] is True


async def test_ui_method_read_group_is_implemented() -> None:
    settings = Settings(contract_snapshot=_BUNDLED)
    app = create_app(
        settings=settings,
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            method = await client.get(
                "/ui/api/method",
                params={"major": 9, "path": "/access/groups/{groupid}", "verb": "GET"},
            )
            assert method.status_code == 200
            payload = method.json()
            assert payload["name"] == "read_group"
            assert payload["implemented"] is True


async def test_ui_catalog_read_group_is_implemented() -> None:
    settings = Settings(contract_snapshot=_BUNDLED)
    app = create_app(
        settings=settings,
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            catalog = await client.get("/ui/api/catalog", params={"major": 9})
            assert catalog.status_code == 200
            methods = {
                (path["path"], method["name"]): method["implemented"]
                for category in catalog.json()["categories"]
                for path in category["paths"]
                for method in path["methods"]
            }
            assert methods[("/access/groups/{groupid}", "read_group")] is True


async def test_demo_api_requires_database() -> None:
    app = create_app(database_factory=lambda _settings: FakeDatabase(True), worker_factories=())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            state = await client.get("/ui/api/demo/state")
            load = await client.post("/ui/api/demo/load")
    assert state.status_code == 503
    assert load.status_code == 503


async def test_ui_versions_and_catalog_endpoints() -> None:
    settings = Settings(contract_snapshot=_BUNDLED)
    app = create_app(
        settings=settings,
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            versions = await client.get("/ui/api/versions")
            assert versions.status_code == 200
            assert {item["major"] for item in versions.json()["majors"]} == {6, 7, 8, 9}
            catalog = await client.get("/ui/api/catalog", params={"major": 9})
            assert catalog.status_code == 200
            assert catalog.json()["source_version"] == "9.2.3"
            method = await client.get(
                "/ui/api/method",
                params={"major": 9, "path": "/version", "verb": "GET"},
            )
            assert method.status_code == 200
            assert method.json()["path"] == "/version"
