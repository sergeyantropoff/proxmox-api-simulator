"""Node ops handlers persist network/disks/services into nodes.metadata."""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import FastAPI, Request

from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.nodes import register_node_ops_handlers


class NodePool:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "SELECT metadata FROM nodes" in query:
            return {"metadata": json.dumps(self.metadata)}
        raise AssertionError(query)

    async def fetchval(self, query: str, *arguments: object) -> Any:
        if "EXISTS(SELECT 1 FROM nodes" in query:
            return True
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "UPDATE nodes SET metadata" in query:
            self.metadata = json.loads(str(arguments[1]))
            return "UPDATE 1"
        raise AssertionError(query)


class FakeDatabase:
    def __init__(self, pool: NodePool) -> None:
        self.pool = pool


def request(pool: NodePool, *, method: str = "GET", path: str = "/") -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, FakeDatabase(pool))
    result = Request(
        {
            "type": "http",
            "app": app,
            "method": method,
            "path": path,
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 123),
            "scheme": "http",
        }
    )
    result.state.principal = "root@pam"
    return result


async def test_network_and_service_mutations_persist() -> None:
    registry = HandlerRegistry()
    register_node_ops_handlers(registry)
    pool = NodePool()

    create = registry.get("/nodes/{node}/network", "POST")
    listing = registry.get("/nodes/{node}/network", "GET")
    delete = registry.get("/nodes/{node}/network/{iface}", "DELETE")
    stop = registry.get("/nodes/{node}/services/{service}/stop", "POST")
    state = registry.get("/nodes/{node}/services/{service}/state", "GET")
    assert create and listing and delete and stop and state

    await create(
        request(pool, method="POST", path="/api2/json/nodes/pve01/network"),
        {"values": {"node": "pve01", "iface": "vmbr9", "type": "bridge"}, "provided": frozenset()},
    )
    items = await listing(
        request(pool),
        {"values": {"node": "pve01"}, "provided": frozenset()},
    )
    assert any(item["iface"] == "vmbr9" for item in items)

    await delete(
        request(pool, method="DELETE", path="/api2/json/nodes/pve01/network/vmbr9"),
        {"values": {"node": "pve01", "iface": "vmbr9"}, "provided": frozenset()},
    )
    items = await listing(
        request(pool),
        {"values": {"node": "pve01"}, "provided": frozenset()},
    )
    assert all(item["iface"] != "vmbr9" for item in items)

    await stop(
        request(pool, method="POST", path="/api2/json/nodes/pve01/services/pveproxy/stop"),
        {"values": {"node": "pve01", "service": "pveproxy"}, "provided": frozenset()},
    )
    service = await state(
        request(pool),
        {"values": {"node": "pve01", "service": "pveproxy"}, "provided": frozenset()},
    )
    assert service["state"] == "stopped"
    assert "ops" in pool.metadata


async def test_disk_init_and_wipe_persist() -> None:
    registry = HandlerRegistry()
    register_node_ops_handlers(registry)
    pool = NodePool()
    initgpt = registry.get("/nodes/{node}/disks/initgpt", "POST")
    wipe = registry.get("/nodes/{node}/disks/wipedisk", "PUT")
    listing = registry.get("/nodes/{node}/disks/list", "GET")
    assert initgpt and wipe and listing

    await initgpt(
        request(pool, method="POST"),
        {"values": {"node": "pve01", "disk": "/dev/sdb"}, "provided": frozenset()},
    )
    await wipe(
        request(pool, method="PUT"),
        {"values": {"node": "pve01", "disk": "/dev/sdb"}, "provided": frozenset()},
    )
    disks = await listing(
        request(pool),
        {"values": {"node": "pve01"}, "provided": frozenset()},
    )
    target = next(item for item in disks if item["devpath"] == "/dev/sdb")
    assert target["wiped"] == 1
    assert target["gpt"] == 0
