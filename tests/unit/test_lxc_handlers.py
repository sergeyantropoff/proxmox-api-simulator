"""Persistent LXC semantic handler tests."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.lxc import register_lxc_handlers


class LxcPool:
    def __init__(self) -> None:
        self.resource_exists = False
        self.missing = False
        self.running = False
        self.commands: list[str] = []
        self.resource_id = uuid.uuid4()

    async def fetchval(self, sql: str, *args: object) -> bool | int:
        del args
        if "pg_backend_pid" in sql:
            return 123
        if "extract(epoch" in sql:
            return 1_700_000_000
        if "FROM nodes" in sql:
            return True
        if "FROM resources" in sql:
            return self.resource_exists
        if "FROM snapshots" in sql:
            return False
        raise AssertionError(sql)

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        del args
        if "FROM resources" in sql and "kind='lxc'" in sql:
            return [{"vmid": 200, "state": '{"status":"stopped","name":"service"}'}]
        assert "FROM snapshots" in sql
        return [
            {
                "name": "baseline",
                "parent_name": None,
                "description": "stable",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        ]

    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None:
        del args
        if self.missing:
            return None
        if "SELECT r.id, r.version" in sql:
            return {
                "id": self.resource_id,
                "version": 1,
                "state": '{"name":"old","status":"stopped"}',
                "config": '{"name":"old"}',
            }
        if "SELECT r.id, r.state, c.config" in sql:
            return {"id": self.resource_id, "state": '{"status":"stopped"}', "config": "{}"}
        if "SELECT r.id, r.state FROM resources" in sql:
            status = "running" if self.running else "stopped"
            return {"id": self.resource_id, "state": f'{{"status":"{status}"}}'}
        if "SELECT s.* FROM snapshots" in sql:
            return {
                "id": uuid.uuid4(),
                "name": "baseline",
                "parent_name": None,
                "description": "stable",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "state": "{}",
            }
        raise AssertionError(sql)

    async def execute(self, sql: str, *args: object) -> str:
        del sql, args
        self.commands.append("execute")
        return "UPDATE 1"


class FakeDatabase:
    def __init__(self, pool: LxcPool) -> None:
        self.pool = pool


class FakeTaskRepository:
    def __init__(self, pool: LxcPool) -> None:
        self.pool = pool
        self.created: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.created.append(kwargs)
        return type(
            "Task", (), {"upid": "UPID:pve1:00000001:00000001:1700000000:pctcreate:201:root@pam:"}
        )()


def _request(pool: LxcPool) -> Request:
    app = type("App", (), {"state": type("State", (), {"database": FakeDatabase(pool)})()})()
    request = Request({"type": "http", "headers": [], "method": "POST", "path": "/"})
    request.scope["app"] = app
    request.state.principal = "root@pam"
    return request


@pytest.fixture
def registry() -> HandlerRegistry:
    handler_registry = HandlerRegistry()
    register_lxc_handlers(handler_registry)
    return handler_registry


async def test_lxc_list_returns_seeded_containers(registry: HandlerRegistry) -> None:
    pool = LxcPool()
    handler = registry.get("/nodes/{node}/lxc", "GET")
    assert handler is not None
    result = await handler(_request(pool), {"values": {"node": "pve1"}})
    assert result == [{"vmid": 200, "status": "stopped", "name": "service"}]


async def test_lxc_create_rejects_duplicate_vmid(registry: HandlerRegistry) -> None:
    pool = LxcPool()
    pool.resource_exists = True
    handler = registry.get("/nodes/{node}/lxc", "POST")
    assert handler is not None
    with pytest.raises(ApiError, match="VMID already exists"):
        await handler(
            _request(pool),
            {"values": {"node": "pve1", "vmid": 201, "hostname": "app"}},
        )


async def test_lxc_delete_requires_stopped_container(registry: HandlerRegistry) -> None:
    pool = LxcPool()
    pool.running = True
    handler = registry.get("/nodes/{node}/lxc/{vmid}", "DELETE")
    assert handler is not None
    with pytest.raises(ApiError, match="cannot delete a running container"):
        await handler(_request(pool), {"values": {"node": "pve1", "vmid": "200"}})


async def test_lxc_start_creates_task(
    monkeypatch: pytest.MonkeyPatch, registry: HandlerRegistry
) -> None:
    pool = LxcPool()
    repository = FakeTaskRepository(pool)
    monkeypatch.setattr("app.handlers.lxc.TaskRepository", lambda _pool: repository)
    handler = registry.get("/nodes/{node}/lxc/{vmid}/status/start", "POST")
    assert handler is not None
    upid = await handler(_request(pool), {"values": {"node": "pve1", "vmid": "200"}})
    assert upid.startswith("UPID:")
    assert repository.created[0]["task_type"] == "lxc-start"
