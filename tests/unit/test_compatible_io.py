"""Golden HTTP input/output compatibility checks."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.api.registry import HandlerRegistry
from app.config import Settings
from app.contracts.model import Method, Parameter, PathContract, Schema, Snapshot
from app.main import create_app
from tests.unit.test_health import FakeDatabase


async def client_for(tmp_path: Path) -> AsyncClient:
    method = Method(
        verb="POST",
        name="update",
        parameters=(
            Parameter(name="node", definition=Schema(type="string")),
            Parameter(name="count", definition=Schema(type="integer", minimum=1)),
            Parameter(name="force", definition=Schema(type="boolean", optional=True)),
        ),
        returns=Schema(type="null"),
        checksum="1" * 64,
    )
    snapshot = Snapshot(
        source_version="test",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_sha256="0" * 64,
        paths=(PathContract(path="/nodes/{node}/test", methods=(method,)),),
        path_count=1,
        method_count=1,
    )
    path = tmp_path / "snapshot.json"
    path.write_bytes(snapshot.canonical_bytes())
    handlers = HandlerRegistry()

    async def handler(_request: Request, inputs: dict[str, Any]) -> None:
        assert inputs["values"]["count"] >= 1
        return None

    handlers.register("/nodes/{node}/test", "POST", handler)
    app = create_app(
        Settings(contract_snapshot=path), lambda _settings: FakeDatabase(True), handlers
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_json_input_and_null_envelope(tmp_path: Path) -> None:
    async with await client_for(tmp_path) as client:
        response = await client.post("/api2/json/nodes/pve/test", json={"count": 2, "force": True})

    assert response.status_code == 200
    assert response.json() == {"data": None}


async def test_form_input_and_validation_error_shape(tmp_path: Path) -> None:
    async with await client_for(tmp_path) as client:
        valid = await client.post(
            "/api2/json/nodes/pve/test",
            content="count=1&force=yes",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        invalid = await client.post("/api2/json/nodes/pve/test", json={"count": 0, "unknown": "x"})

    assert valid.status_code == 200
    assert invalid.status_code == 400
    assert invalid.json() == {
        "data": None,
        "message": "parameter verification failed",
        "errors": {
            "count": "value must be at least 1",
            "unknown": "property is not defined in schema",
        },
    }


async def test_non_object_json_is_rejected_without_fastapi_body(tmp_path: Path) -> None:
    async with await client_for(tmp_path) as client:
        response = await client.post("/api2/json/nodes/pve/test", json=[1, 2])

    assert response.status_code == 400
    assert response.json()["errors"] == {"body": "expected an object"}
    assert "detail" not in response.json()
