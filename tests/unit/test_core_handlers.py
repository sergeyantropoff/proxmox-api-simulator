"""First vertical read/login handler tests."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.contracts.model import Method, Parameter, PathContract, Schema, Snapshot
from app.main import create_app
from app.security.auth import hash_secret
from app.tasks.repository import Task


class FakePool:
    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None:
        if "principals" in sql and args[0] == "root@pam":
            return {
                "name": "root@pam",
                "password_hash": hash_secret("secret", salt=b"pve-simulator-v1"),
            }
        if "FROM nodes" in sql and "metadata" in sql and args and args[0] == "pve1":
            return {"metadata": '{"ops":{"status":{"uptime":100}}}'}
        if "FROM nodes" in sql and args and args[0] == "pve1":
            return {"name": "pve1", "status": "online"}
        if "FROM resources r" in sql and args == ("pve1", "100"):
            if "SELECT r.id" in sql:
                return {
                    "id": uuid.UUID("00000000-0000-0000-0000-000000000100"),
                    "state": '{"name":"demo","status":"stopped"}',
                }
            return {
                "config": '{"name":"demo"}',
                "state": '{"name":"demo","status":"stopped"}',
            }
        return None

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        del args
        if "FROM pool_members" in sql or "kind='ha'" in sql:
            return []
        if "FROM nodes" in sql:
            return [{"node": "pve1", "name": "pve1", "status": "online"}]
        if "r.kind='qemu'" in sql:
            return [
                {
                    "vmid": 100,
                    "state": '{"name":"demo","status":"stopped"}',
                    "config": '{"name":"demo","memory":2048,"cores":2}',
                }
            ]
        if "r.kind = ANY" in sql or "r.kind AS type" in sql:
            return [
                {
                    "type": "qemu",
                    "external_id": "100",
                    "state": '{"status":"stopped","name":"demo"}',
                    "node": "pve1",
                }
            ]
        return []

    async def fetchval(self, sql: str, *args: object) -> object:
        del args
        if "SELECT name FROM clusters" in sql:
            return "pve-simulator"
        return 100 if "pg_backend_pid" in sql else 1_700_000_000


class FakeDatabase:
    pool = FakePool()

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def is_ready(self) -> bool:
        return True


def method(verb: str, name: str, parameters: tuple[Parameter, ...] = ()) -> Method:
    return Method(
        verb=verb,
        name=name,
        parameters=parameters,
        returns=Schema(type="object"),
        checksum=(name[0] * 64),
    )


def write_snapshot(path: Path) -> None:
    string = Schema(type="string")
    paths = (
        PathContract(path="/version", methods=(method("GET", "version"),)),
        PathContract(
            path="/access/ticket",
            methods=(
                method(
                    "POST",
                    "ticket",
                    (
                        Parameter(name="username", definition=string),
                        Parameter(name="password", definition=string),
                    ),
                ),
            ),
        ),
        PathContract(path="/nodes", methods=(method("GET", "nodes"),)),
        PathContract(
            path="/nodes/{node}/status",
            methods=(method("GET", "status", (Parameter(name="node", definition=string),)),),
        ),
        PathContract(path="/cluster/resources", methods=(method("GET", "resources"),)),
        PathContract(
            path="/nodes/{node}/qemu",
            methods=(method("GET", "qemu", (Parameter(name="node", definition=string),)),),
        ),
        PathContract(
            path="/nodes/{node}/qemu/{vmid}/config",
            methods=(
                method(
                    "GET",
                    "config",
                    (
                        Parameter(name="node", definition=string),
                        Parameter(name="vmid", definition=Schema(type="integer")),
                    ),
                ),
            ),
        ),
        PathContract(
            path="/nodes/{node}/qemu/{vmid}/status/start",
            methods=(
                method(
                    "POST",
                    "start",
                    (
                        Parameter(name="node", definition=string),
                        Parameter(name="vmid", definition=Schema(type="integer")),
                    ),
                ),
            ),
        ),
    )
    snapshot = Snapshot(
        source_version="test",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_sha256="0" * 64,
        paths=paths,
        path_count=len(paths),
        method_count=sum(len(item.methods) for item in paths),
    )
    path.write_bytes(snapshot.canonical_bytes())


async def test_core_login_and_read_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeTaskRepository:
        def __init__(self, pool: object) -> None:
            del pool

        async def create(self, **kwargs: object) -> Task:
            return Task(
                uuid.uuid4(),
                str(kwargs["upid"]),
                str(kwargs["task_type"]),
                "queued",
                {},
                0,
                False,
                0,
            )

    monkeypatch.setattr("app.handlers.qemu.TaskRepository", FakeTaskRepository)
    snapshot_path = tmp_path / "snapshot.json"
    write_snapshot(snapshot_path)
    database = FakeDatabase()
    app = create_app(
        Settings(contract_snapshot=snapshot_path, compatibility_evidence=None),
        lambda _settings: database,
        worker_factories=(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post(
                "/api2/json/access/ticket",
                content="username=root%40pam&password=secret",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            csrf = login.json()["data"]["CSRFPreventionToken"]
            version = await client.get("/api2/json/version")
            nodes = await client.get("/api2/json/nodes")
            status = await client.get("/api2/json/nodes/pve1/status")
            resources = await client.get("/api2/json/cluster/resources")
            qemu = await client.get("/api2/json/nodes/pve1/qemu")
            config = await client.get("/api2/json/nodes/pve1/qemu/100/config")
            start = await client.post(
                "/api2/json/nodes/pve1/qemu/100/status/start",
                headers={"CSRFPreventionToken": csrf},
            )

    assert login.status_code == 200
    assert login.json()["data"]["username"] == "root@pam"
    assert "ticket" in login.json()["data"]
    assert login.json()["data"]["clustername"] == "pve-simulator"
    assert version.json()["data"]["version"] == "test"
    assert version.json()["data"]["release"] == "test"
    assert nodes.json()["data"][0]["node"] == "pve1"
    assert "uptime" in status.json()["data"]
    assert "memory" in status.json()["data"]
    assert "cpuinfo" in status.json()["data"]
    resource_types = {item["type"] for item in resources.json()["data"]}
    assert "qemu" in resource_types
    qemu_resources = [item for item in resources.json()["data"] if item["type"] == "qemu"]
    assert qemu_resources
    assert isinstance(qemu_resources[0]["cpu"], int | float)
    assert qemu_resources[0]["vmid"] == 100
    assert qemu.json()["data"][0]["vmid"] == 100
    assert config.json()["data"]["name"] == "demo"
    assert start.json()["data"].startswith("UPID:pve1:")
