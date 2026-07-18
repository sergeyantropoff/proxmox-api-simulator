"""Tests for cluster, storage, pool and ceph handlers."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.ceph import register_ceph_handlers
from app.handlers.cluster import register_cluster_handlers
from app.handlers.pools import register_pool_handlers
from app.handlers.storage import register_storage_handlers


class HandlerPool:
    def __init__(self) -> None:
        self.node_exists = True

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        del args
        if "FROM nodes" in sql and "ORDER BY name" in sql:
            return [{"id": uuid.uuid4(), "name": "pve01", "status": "online"}]
        if "FROM storages" in sql and "DISTINCT storage_id" in sql:
            return [{"storage_id": "local-lvm-pve01"}]
        if "FROM storages s" in sql:
            return [
                {
                    "storage_id": "local-lvm-pve01",
                    "storage_type": "lvmthin",
                    "shared": False,
                    "capacity_bytes": 1_000_000,
                    "used_bytes": 250_000,
                    "config": '{"content":["images"]}',
                }
            ]
        if "ceph-osd" in sql:
            return [
                {
                    "external_id": "osd.0",
                    "state": '{"osd_id":0,"status":"up","in":true,"weight":1.0}',
                }
            ]
        if "FROM pools" in sql:
            return [
                {
                    "id": uuid.uuid4(),
                    "pool_id": "production",
                    "comment": "prod",
                    "metadata": '{"members":["100"]}',
                }
            ]
        if "FROM pool_members" in sql:
            return [{"external_id": "100"}]
        if "FROM task_logs" in sql:
            return [{"message": "seeded task", "sequence": 1}]
        if "FROM tasks" in sql:
            return [{"upid": "UPID:pve01:1:1:1:qmstart:100:root@pam:"}]
        if "FROM storage_contents" in sql or "FROM backups" in sql:
            return []
        raise AssertionError(sql)

    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None:
        del args
        if "FROM nodes WHERE name" in sql:
            if not self.node_exists:
                return None
            if "metadata" in sql:
                return {"metadata": "{}"}
            return {"name": "pve01", "status": "online"}
        if "FROM clusters" in sql:
            return {"metadata": '{"options":{"keyboard":"de-ch"}}'}
        if "FROM storages" in sql:
            return {
                "storage_id": "local-lvm-pve01",
                "storage_type": "lvmthin",
                "shared": False,
                "capacity_bytes": 1_000_000,
                "used_bytes": 250_000,
                "config": '{"content":["images"]}',
                "node_name": "pve01",
                "resource_id": uuid.uuid4(),
            }
        if "ceph-osd" in sql:
            return {
                "external_id": "osd.0",
                "state": '{"osd_id":0,"status":"up","in":true,"weight":1.0,"size_bytes":1000}',
            }
        if "storage_type='ceph'" in sql:
            return {"capacity_bytes": 5_000_000, "used_bytes": 3_000_000}
        raise AssertionError(sql)

    async def fetchval(self, sql: str, *args: object) -> Any:
        del args
        if "EXISTS(SELECT 1 FROM nodes" in sql:
            return self.node_exists
        if "MAX(external_id::integer)" in sql:
            return 150
        if "count(*)::int FROM resources WHERE kind='ceph-osd'" in sql:
            return 300
        if "SELECT resource_id FROM storages" in sql:
            return uuid.uuid4()
        return False

    async def execute(self, sql: str, *args: object) -> str:
        del sql, args
        return "UPDATE 1"


def _request(pool: HandlerPool) -> Request:
    app = type("App", (), {})()
    app.state = type("State", (), {"database": type("DB", (), {"pool": pool})()})()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": ("test", 1234),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
        "app": app,
    }
    request = Request(scope)
    request.state.principal = "root@pam"
    return request


async def _call(handler: Any, values: dict[str, Any], pool: HandlerPool | None = None) -> Any:
    return await handler(_request(pool or HandlerPool()), {"values": values})


@pytest.mark.asyncio
async def test_cluster_status_and_nextid() -> None:
    registry = HandlerRegistry()
    register_cluster_handlers(registry)
    status = await _call(registry.get("/cluster/status", "GET"), {})
    assert status[0]["name"] == "pve01"
    nextid = await _call(registry.get("/cluster/nextid", "GET"), {})
    assert nextid == 151


@pytest.mark.asyncio
async def test_storage_and_ceph_handlers() -> None:
    registry = HandlerRegistry()
    register_storage_handlers(registry)
    register_ceph_handlers(registry)
    storage = await _call(
        registry.get("/nodes/{node}/storage", "GET"),
        {"node": "pve01"},
    )
    assert storage[0]["storage"] == "local-lvm-pve01"
    osds = await _call(
        registry.get("/nodes/{node}/ceph/osd", "GET"),
        {"node": "pve01"},
    )
    assert osds[0]["status"] == "up"
    ceph_status = await _call(registry.get("/cluster/ceph/status", "GET"), {})
    assert ceph_status["osdmap"]["num_osds"] == 1


@pytest.mark.asyncio
async def test_pools_list() -> None:
    registry = HandlerRegistry()
    register_pool_handlers(registry)
    pools = await _call(registry.get("/pools", "GET"), {})
    assert pools[0]["poolid"] == "production"
    assert pools[0]["members"] == ["100"]


@pytest.mark.asyncio
async def test_missing_node_returns_404() -> None:
    registry = HandlerRegistry()
    register_storage_handlers(registry)
    pool = HandlerPool()
    pool.node_exists = False
    handler = registry.get("/nodes/{node}/storage", "GET")
    assert handler is not None
    with pytest.raises(ApiError, match="node does not exist"):
        await handler(_request(pool), {"values": {"node": "missing"}})
