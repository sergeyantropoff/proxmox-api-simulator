"""Ceph pool/OSD mutation persistence tests."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.ceph import register_ceph_handlers
from app.simulation.seed import CLUSTER_ID


class CephPool:
    def __init__(self) -> None:
        self.cluster_metadata: dict[str, Any] = {}
        self.nodes = {"pve1": {"id": uuid4(), "metadata": {}}}
        self.resources: dict[Any, dict[str, Any]] = {}

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, Any]]:
        if "r.kind='ceph-osd'" in query and "ORDER BY" in query:
            node = str(arguments[0])
            node_id = self.nodes[node]["id"]
            return [
                {"external_id": item["external_id"], "state": item["state"]}
                for item in self.resources.values()
                if item["node_id"] == node_id
            ]
        raise AssertionError(query)

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "FROM clusters WHERE id" in query:
            return {"metadata": json.dumps(self.cluster_metadata)}
        if "SELECT metadata FROM nodes WHERE name" in query:
            node = self.nodes.get(str(arguments[0]))
            return None if node is None else {"metadata": json.dumps(node["metadata"])}
        if "storage_type='ceph'" in query:
            return {"capacity_bytes": 1000, "used_bytes": 100}
        if "r.kind='ceph-osd'" in query:
            node_name = str(arguments[0])
            osdid = str(arguments[1])
            node_id = self.nodes[node_name]["id"]
            for item in self.resources.values():
                if item["node_id"] == node_id and item["external_id"] in {
                    osdid,
                    f"osd.{osdid}",
                    arguments[2] if len(arguments) > 2 else "",
                }:
                    return item
            return None
        raise AssertionError(query)

    async def fetchval(self, query: str, *arguments: object) -> Any:
        if "EXISTS(SELECT 1 FROM nodes" in query:
            return str(arguments[0]) in self.nodes
        if "SELECT id FROM nodes WHERE name" in query:
            node = self.nodes.get(str(arguments[0]))
            return None if node is None else node["id"]
        if "count(*)::int FROM resources WHERE kind='ceph-osd'" in query:
            return len(self.resources)
        if "COALESCE" in query and "ceph-osd" in query:
            return len(self.resources)
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "jsonb_set" in query and "'{ceph}'" in query:
            self.cluster_metadata["ceph"] = json.loads(str(arguments[1]))
            return "UPDATE 1"
        if "UPDATE nodes SET metadata" in query:
            self.nodes[str(arguments[0])]["metadata"] = json.loads(str(arguments[1]))
            return "UPDATE 1"
        if "INSERT INTO resources" in query:
            resource_id = uuid4()
            self.resources[resource_id] = {
                "id": resource_id,
                "node_id": arguments[0],
                "external_id": arguments[1],
                "state": arguments[2],
            }
            return "INSERT 0 1"
        if "UPDATE resources SET state" in query:
            existing_id = arguments[0]
            self.resources[existing_id]["state"] = arguments[1]
            return "UPDATE 1"
        if "DELETE FROM resources WHERE id" in query:
            self.resources.pop(arguments[0], None)
            return "DELETE 1"
        raise AssertionError(query)


def request(pool: CephPool) -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, type("DB", (), {"pool": pool})())
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


async def test_ceph_pool_and_osd_mutations_persist() -> None:
    registry = HandlerRegistry()
    register_ceph_handlers(registry)
    pool = CephPool()
    http = request(pool)

    create_pool = registry.get("/nodes/{node}/ceph/pool", "POST")
    list_pool = registry.get("/nodes/{node}/ceph/pool", "GET")
    create_osd = registry.get("/nodes/{node}/ceph/osd", "POST")
    osd_out = registry.get("/nodes/{node}/ceph/osd/{osdid}/out", "POST")
    assert create_pool and list_pool and create_osd and osd_out

    await create_pool(http, {"values": {"node": "pve1", "name": "vms"}, "provided": frozenset()})
    pools = await list_pool(http, {"values": {"node": "pve1"}, "provided": frozenset()})
    assert any(item["pool"] == "vms" for item in pools)
    assert "vms" in pool.cluster_metadata["ceph"]["pools"]

    await create_osd(http, {"values": {"node": "pve1", "dev": "/dev/sdb"}, "provided": frozenset()})
    assert len(pool.resources) == 1
    resource_id = next(iter(pool.resources))
    osdid = "0"
    await osd_out(
        http,
        {"values": {"node": "pve1", "osdid": osdid}, "provided": frozenset()},
    )
    assert json.loads(pool.resources[resource_id]["state"])["in"] is False
    assert CLUSTER_ID
