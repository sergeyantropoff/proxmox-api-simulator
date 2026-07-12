"""Persistent QEMU CRUD semantic handler tests."""

import uuid
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.db.primitives import ConflictError
from app.handlers.qemu import register_qemu_handlers
from app.tasks.repository import Task


class QemuPool:
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
        raise AssertionError(sql)

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
        if "SELECT r.id, r.state" in sql:
            status = "running" if self.running else "stopped"
            return {"id": self.resource_id, "state": f'{{"status":"{status}"}}'}
        raise AssertionError(sql)

    async def execute(self, sql: str, *args: object) -> str:
        del args
        self.commands.append(sql)
        return "UPDATE 1"


class FakeDatabase:
    def __init__(self, pool: QemuPool) -> None:
        self.pool = pool


def request(pool: QemuPool) -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, FakeDatabase(pool))
    result = Request(
        {
            "type": "http",
            "app": app,
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 123),
            "scheme": "http",
        }
    )
    result.state.principal = "root@pam"
    return result


def inputs(**values: object) -> dict[str, Any]:
    return {"values": values, "provided": tuple(values)}


async def test_qemu_create_sync_async_update_and_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_payloads: list[dict[str, Any]] = []

    class FakeTaskRepository:
        def __init__(self, pool: object) -> None:
            del pool

        async def create(self, **kwargs: Any) -> Task:
            created_payloads.append(kwargs)
            return Task(
                uuid.uuid4(),
                str(kwargs["upid"]),
                str(kwargs["task_type"]),
                "queued",
                dict(kwargs["payload"]),
                0,
                False,
                0,
            )

    monkeypatch.setattr("app.handlers.qemu.TaskRepository", FakeTaskRepository)
    registry = HandlerRegistry()
    register_qemu_handlers(registry)
    pool = QemuPool()
    http_request = request(pool)
    create = registry.get("/nodes/{node}/qemu", "POST")
    update_sync = registry.get("/nodes/{node}/qemu/{vmid}/config", "PUT")
    update_async = registry.get("/nodes/{node}/qemu/{vmid}/config", "POST")
    delete = registry.get("/nodes/{node}/qemu/{vmid}", "DELETE")
    assert create and update_sync and update_async and delete

    create_upid = await create(
        http_request,
        inputs(node="pve1", vmid=150, name="new", cores=2),
    )
    assert create_upid.startswith("UPID:pve1:")
    assert created_payloads[-1]["task_type"] == "qemu-create"

    assert (
        await update_sync(
            http_request,
            inputs(node="pve1", vmid=150, name="sync", delete="unused"),
        )
        is None
    )
    assert len(pool.commands) == 2

    update_upid = await update_async(
        http_request,
        inputs(node="pve1", vmid=150, memory="2048"),
    )
    assert update_upid.startswith("UPID:pve1:")
    assert created_payloads[-1]["task_type"] == "qemu-update"

    delete_upid = await delete(http_request, inputs(node="pve1", vmid=150))
    assert delete_upid.startswith("UPID:pve1:")
    assert created_payloads[-1]["task_type"] == "qemu-delete"


async def test_qemu_crud_conflicts_and_missing_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConflictingRepository:
        def __init__(self, pool: object) -> None:
            del pool

        async def create(self, **_kwargs: object) -> Task:
            raise ConflictError("resource is locked")

    monkeypatch.setattr("app.handlers.qemu.TaskRepository", ConflictingRepository)
    registry = HandlerRegistry()
    register_qemu_handlers(registry)
    pool = QemuPool()
    http_request = request(pool)
    create = registry.get("/nodes/{node}/qemu", "POST")
    update = registry.get("/nodes/{node}/qemu/{vmid}/config", "PUT")
    delete = registry.get("/nodes/{node}/qemu/{vmid}", "DELETE")
    assert create and update and delete

    with pytest.raises(ApiError) as locked:
        await create(http_request, inputs(node="pve1", vmid=150))
    assert locked.value.status_code == 409

    pool.resource_exists = True
    with pytest.raises(ApiError) as duplicate:
        await create(http_request, inputs(node="pve1", vmid=150))
    assert duplicate.value.status_code == 409

    pool.missing = True
    with pytest.raises(ApiError) as missing:
        await update(http_request, inputs(node="pve1", vmid=150, name="missing"))
    assert missing.value.status_code == 404

    pool.missing = False
    pool.running = True
    with pytest.raises(ApiError) as running:
        await delete(http_request, inputs(node="pve1", vmid=150))
    assert running.value.status_code == 409
