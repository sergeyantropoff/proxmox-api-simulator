"""Contract-driven route registry tests."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.registry import HandlerRegistry, RouteCollisionError
from app.config import Settings
from app.contracts.model import Method, PathContract, Schema, Snapshot
from app.main import create_app
from tests.unit.test_health import FakeDatabase


def contract_snapshot(*methods: Method) -> Snapshot:
    paths = (PathContract(path="/version", methods=methods),)
    return Snapshot(
        source_version="test",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_sha256="0" * 64,
        paths=paths,
        path_count=1,
        method_count=len(methods),
    )


def get_method() -> Method:
    return Method(
        verb="GET",
        name="version",
        returns=Schema(type="object", properties={"version": Schema(type="string")}),
        checksum="1" * 64,
    )


async def request_app(
    tmp_path: Path, fallback: str, handlers: HandlerRegistry | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_bytes(contract_snapshot(get_method()).canonical_bytes())
    settings = Settings(contract_snapshot=snapshot_path, contract_fallback=fallback)
    database = FakeDatabase(True)
    app = create_app(
        settings,
        lambda _settings: database,
        handlers if handlers is not None else HandlerRegistry(),
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            json_response = await client.get("/api2/json/version")
            extjs_response = await client.get("/api2/extjs/version")
    return json_response.json(), extjs_response.json()


async def test_registered_handler_serves_both_renderers(tmp_path: Path) -> None:
    handlers = HandlerRegistry()

    async def version(_request: Request, _inputs: dict[str, Any]) -> dict[str, str]:
        return {"version": "9.2.3"}

    handlers.register("/version", "GET", version)

    json_body, extjs_body = await request_app(tmp_path, "error", handlers)

    assert json_body == {"data": {"version": "9.2.3"}}
    assert extjs_body == {"data": {"version": "9.2.3"}, "success": True}


async def test_explicit_fallback_modes(tmp_path: Path) -> None:
    error_body, _ = await request_app(tmp_path, "error")
    default_body, _ = await request_app(tmp_path, "schema-default")

    assert error_body["errors"] == "method semantics are not implemented"
    assert default_body == {"data": {"version": None}}


def test_duplicate_snapshot_routes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        contract_snapshot(get_method(), get_method())


def test_duplicate_semantic_handlers_are_rejected() -> None:
    handlers = HandlerRegistry()

    async def handler(_request: Request, _inputs: dict[str, Any]) -> None:
        return None

    handlers.register("/version", "GET", handler)
    with pytest.raises(RouteCollisionError, match="duplicate"):
        handlers.register("/version", "GET", handler)
