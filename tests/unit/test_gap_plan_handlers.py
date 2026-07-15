"""Tests for gap-plan handler implementations."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.access import register_access_handlers
from app.handlers.cluster import register_cluster_handlers
from app.handlers.ha import register_ha_handlers
from app.handlers.storage import register_storage_handlers


class GapPool:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {
            "options": {"keyboard": "en-us"},
            "replication": [],
            "ha_groups": {},
        }
        self.node_metadata: dict[str, Any] = {}
        self.node_exists = True
        self.storage_resource_id = uuid.uuid4()
        self.storage_contents: list[dict[str, object]] = []
        self.principals = {"root@pam": {"enabled": True, "realm": "pam"}}
        self.groups = {"operators": {"comment": "ops", "users": ["root@pam"]}}

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        del args
        if "FROM nodes" in sql and "ORDER BY name" in sql:
            return [{"id": uuid.uuid4(), "name": "pve01", "status": "online"}]
        if "FROM tasks" in sql:
            return []
        if "FROM task_logs" in sql:
            return []
        if "FROM resources r JOIN nodes" in sql and "kind='ha'" in sql:
            return []
        if "FROM storage_contents" in sql and "ORDER BY" in sql:
            return list(self.storage_contents)
        if "FROM backups" in sql and "ORDER BY created_at DESC" in sql and "OFFSET" not in sql:
            return []
        if "FROM principals p" in sql and "ORDER BY p.name" in sql:
            return [
                {
                    "name": name,
                    "realm_name": data["realm"],
                    "enabled": data["enabled"],
                    "realm_kind": data["realm"],
                }
                for name, data in self.principals.items()
            ]
        if "FROM identity_groups g" in sql and "GROUP BY" in sql:
            return [
                {
                    "group_id": group_id,
                    "comment": data["comment"],
                    "users": data["users"],
                }
                for group_id, data in self.groups.items()
            ]
        raise AssertionError(sql)

    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None:
        if "FROM clusters WHERE id" in sql:
            return {"metadata": json.dumps(self.metadata)}
        if "FROM nodes WHERE name" in sql and "metadata" in sql:
            name = str(args[0])
            return {"metadata": json.dumps(self.node_metadata.get(name, {}))}
        if "FROM nodes WHERE name" in sql:
            return {"name": "pve01", "id": uuid.uuid4()} if self.node_exists else None
        if "FROM storages WHERE storage_id" in sql and "resource_id" in sql:
            return {"resource_id": self.storage_resource_id}
        if "FROM storages s" in sql and "JOIN" in sql:
            return {
                "storage_id": "local-lvm",
                "storage_type": "lvmthin",
                "shared": False,
                "capacity_bytes": 1_000_000,
                "used_bytes": 250_000,
                "config": '{"content":["images"]}',
                "node_name": "pve01",
                "resource_id": self.storage_resource_id,
            }
        if "FROM storage_contents" in sql and "volume_id=$2" in sql:
            volume = str(args[1])
            for item in self.storage_contents:
                if item["volume_id"] == volume:
                    return item
            return {
                "volume_id": "local-lvm:100/vm-100-disk-0.raw",
                "content_type": "images",
                "size_bytes": 1024,
                "metadata": '{"format":"raw"}',
                "created_at": type("TS", (), {"timestamp": lambda self: 1_700_000_000})(),
            }
        if "FROM principals" in sql and "WHERE" in sql and "name" in sql:
            userid = str(args[0])
            if userid not in self.principals:
                return None
            data = self.principals[userid]
            return {
                "name": userid,
                "realm_name": data["realm"],
                "enabled": data["enabled"],
                "realm_kind": data["realm"],
                "id": uuid.uuid4(),
            }
        if "FROM identity_groups WHERE group_id" in sql:
            groupid = str(args[0])
            if groupid not in self.groups:
                return None
            return {"id": uuid.uuid4(), "group_id": groupid}
        if "FROM identity_groups g" in sql and "WHERE g.group_id" in sql:
            groupid = str(args[0])
            if groupid not in self.groups:
                return None
            group_data = self.groups[groupid]
            return {
                "group_id": groupid,
                "comment": group_data["comment"],
                "users": group_data["users"],
            }
        if "count(*) FILTER" in sql and "kind='ha'" in sql:
            return {"started": 0, "total": 0}
        raise AssertionError(sql)

    async def fetchval(self, sql: str, *args: object) -> Any:
        if "EXISTS(SELECT 1 FROM nodes" in sql:
            return self.node_exists
        if "MAX(external_id::integer)" in sql:
            return 150
        if "SELECT resource_id FROM storages" in sql:
            return self.storage_resource_id
        if "EXISTS(SELECT 1 FROM principals" in sql:
            return False
        if "EXISTS(SELECT 1 FROM realms" in sql:
            return True
        if "EXISTS(SELECT 1 FROM identity_groups" in sql:
            return False
        if "EXISTS(SELECT 1 FROM resources WHERE kind='ha'" in sql:
            return False
        if "SELECT metadata FROM nodes" in sql:
            return json.dumps(self.node_metadata.get(str(args[0]), {}))
        if "SELECT name FROM nodes WHERE status" in sql:
            return "pve01"
        return False

    async def execute(self, sql: str, *args: object) -> str:
        if "UPDATE clusters SET metadata" in sql:
            self.metadata = json.loads(str(args[1]))
            return "UPDATE 1"
        if "UPDATE nodes SET metadata" in sql:
            self.node_metadata[str(args[0])] = json.loads(str(args[1]))
            return "UPDATE 1"
        if "INSERT INTO storage_contents" in sql:
            self.storage_contents.append(
                {
                    "volume_id": str(args[1]),
                    "content_type": str(args[2]),
                    "size_bytes": int(str(args[3])),
                    "metadata": str(args[4]),
                    "created_at": type("TS", (), {"timestamp": lambda self: 1_700_000_000})(),
                }
            )
            return "INSERT 0 1"
        if "INSERT INTO resources" in sql and "kind='ha'" in sql:
            return "INSERT 0 1"
        if "DELETE FROM" in sql:
            return "DELETE 1"
        return "UPDATE 1"


def _request(pool: GapPool) -> Request:
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


async def _call(handler: Any, values: dict[str, Any], pool: GapPool | None = None) -> Any:
    return await handler(
        _request(pool or GapPool()),
        {"values": values, "provided": tuple(values)},
    )


@pytest.mark.asyncio
async def test_cluster_index_and_replication_crud() -> None:
    registry = HandlerRegistry()
    register_cluster_handlers(registry)
    pool = GapPool()
    index = await _call(registry.get("/cluster", "GET"), {}, pool)
    assert any(item["subdir"] == "replication" for item in index)
    created = await _call(
        registry.get("/cluster/replication", "POST"),
        {"guest": "100", "target": "pve02"},
        pool,
    )
    assert created["id"] == "repl-100"
    jobs = await _call(registry.get("/cluster/replication", "GET"), {}, pool)
    assert jobs[0]["guest"] == "100"
    fetched = await _call(
        registry.get("/cluster/replication/{id}", "GET"), {"id": "repl-100"}, pool
    )
    assert fetched["target"] == "pve02"


@pytest.mark.asyncio
async def test_ha_group_create_and_index() -> None:
    registry = HandlerRegistry()
    register_ha_handlers(registry)
    pool = GapPool()
    index = await _call(registry.get("/cluster/ha", "GET"), {}, pool)
    assert any(item["subdir"] == "groups" for item in index)
    await _call(
        registry.get("/cluster/ha/groups", "POST"),
        {"group": "lab", "nodes": "pve01,pve02"},
        pool,
    )
    assert "lab" in pool.metadata["ha_groups"]
    groups = await _call(registry.get("/cluster/ha/groups", "GET"), {}, pool)
    assert groups[0]["group"] == "lab"


@pytest.mark.asyncio
async def test_access_user_and_group_detail() -> None:
    registry = HandlerRegistry()
    register_access_handlers(registry)
    pool = GapPool()
    user = await _call(registry.get("/access/users/{userid}", "GET"), {"userid": "root@pam"}, pool)
    assert user["userid"] == "root@pam"
    group = await _call(
        registry.get("/access/groups/{groupid}", "GET"),
        {"groupid": "operators"},
        pool,
    )
    assert group["users"] == ["root@pam"]


@pytest.mark.asyncio
async def test_storage_content_get_and_upload() -> None:
    registry = HandlerRegistry()
    register_storage_handlers(registry)
    pool = GapPool()
    item = await _call(
        registry.get("/nodes/{node}/storage/{storage}/content/{volume}", "GET"),
        {
            "node": "pve01",
            "storage": "local-lvm",
            "volume": "local-lvm:100/vm-100-disk-0.raw",
        },
        pool,
    )
    assert item["content"] == "images"
    upload = await _call(
        registry.get("/nodes/{node}/storage/{storage}/upload", "POST"),
        {"node": "pve01", "storage": "local-lvm", "filename": "image.iso"},
        pool,
    )
    assert "uploadid" in upload


@pytest.mark.asyncio
async def test_replication_missing_returns_404() -> None:
    registry = HandlerRegistry()
    register_cluster_handlers(registry)
    handler = registry.get("/cluster/replication/{id}", "GET")
    with pytest.raises(ApiError, match="replication job does not exist"):
        await _call(handler, {"id": "missing"}, GapPool())
