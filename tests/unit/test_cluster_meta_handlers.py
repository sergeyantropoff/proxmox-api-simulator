"""Mapping / ACME / cluster-config durable handlers."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.acme import register_acme_handlers
from app.handlers.cluster_config import register_cluster_config_handlers
from app.handlers.mapping import register_mapping_handlers


class MetaPool:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}
        self.nodes = {"pve1": {"status": "online"}}
        self.cluster_name = "pve-simulator"

    async def fetch(self, query: str, *_arguments: object) -> list[dict[str, Any]]:
        if "FROM nodes" in query:
            return [{"name": name, "status": data["status"]} for name, data in self.nodes.items()]
        raise AssertionError(query)

    async def fetchrow(self, query: str, *_arguments: object) -> dict[str, Any] | None:
        if "FROM clusters WHERE id" in query:
            return {"metadata": json.dumps(self.metadata)}
        raise AssertionError(query)

    async def fetchval(self, query: str, *arguments: object) -> Any:
        if "EXISTS(SELECT 1 FROM nodes" in query:
            return str(arguments[0]) in self.nodes
        if "SELECT name FROM nodes ORDER BY name LIMIT 1" in query:
            return sorted(self.nodes)[0] if self.nodes else None
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "UPDATE clusters SET metadata" in query:
            self.metadata = json.loads(str(arguments[1]))
            return "UPDATE 1"
        if "UPDATE clusters" in query and "SET name" in query:
            self.cluster_name = str(arguments[0])
            return "UPDATE 1"
        if "INSERT INTO nodes" in query:
            self.nodes[str(arguments[0])] = {"status": "online"}
            return "INSERT 0 1"
        if "UPDATE nodes SET status" in query:
            self.nodes[str(arguments[0])]["status"] = "offline"
            return "UPDATE 1"
        raise AssertionError(query)


class FakeTaskRepository:
    def __init__(self, pool: MetaPool) -> None:
        self.pool = pool
        self.created: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.created.append(kwargs)
        return type("Task", (), {"upid": kwargs["upid"]})()


async def call(
    registry: HandlerRegistry, path: str, verb: str, http: Request, inputs: dict[str, Any]
) -> Any:
    handler = registry.get(path, verb)
    assert handler is not None
    return await handler(http, inputs)


def request(pool: MetaPool) -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, type("DB", (), {"pool": pool})())
    http = Request(
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
    http.state.principal = "root@pam"
    return http


async def test_mapping_acme_config_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = HandlerRegistry()
    register_mapping_handlers(registry)
    register_acme_handlers(registry)
    register_cluster_config_handlers(registry)
    pool = MetaPool()
    http = request(pool)
    repository = FakeTaskRepository(pool)
    monkeypatch.setattr("app.handlers.cluster_config.TaskRepository", lambda _pool: repository)

    await call(
        registry,
        "/cluster/mapping/pci",
        "POST",
        http,
        {"values": {"id": "gpu0", "map": "0000:01:00.0"}, "provided": frozenset()},
    )
    pci = await call(
        registry,
        "/cluster/mapping/pci/{id}",
        "GET",
        http,
        {"values": {"id": "gpu0"}, "provided": frozenset()},
    )
    assert pci["map"] == "0000:01:00.0"

    await call(
        registry,
        "/cluster/acme/account",
        "POST",
        http,
        {
            "values": {"name": "default", "contact": "admin@example.com", "eab-hmac-key": "x"},
            "provided": frozenset(),
        },
    )
    account = await call(
        registry,
        "/cluster/acme/account/{name}",
        "GET",
        http,
        {"values": {"name": "default"}, "provided": frozenset()},
    )
    assert account["account"]["name"] == "default"
    assert account["directory"]
    assert "eab-hmac-key" not in account
    assert "eab-hmac-key" not in account["account"]

    upid = await call(
        registry,
        "/cluster/config",
        "POST",
        http,
        {"values": {"clustername": "lab", "link0": "10.0.0.1"}, "provided": frozenset()},
    )
    assert isinstance(upid, str)
    assert upid.startswith("UPID:pve1:")
    assert ":clustercreate:" in upid
    assert repository.created[0]["task_type"] == "cluster-create"
    assert pool.metadata["cluster_config"]["clustername"] == "lab"
    assert pool.cluster_name == "lab"
    assert pool.metadata["cluster_config"]["corosync_conf"]
    assert pool.metadata["cluster_config"]["config_digest"]
    totem = await call(
        registry, "/cluster/config/totem", "GET", http, {"values": {}, "provided": frozenset()}
    )
    assert totem["cluster_name"] == "lab"
    assert uuid4()


async def test_cluster_config_index_uses_name_links() -> None:
    registry = HandlerRegistry()
    register_cluster_config_handlers(registry)
    pool = MetaPool()
    index = await call(
        registry, "/cluster/config", "GET", request(pool), {"values": {}, "provided": frozenset()}
    )
    assert index == [
        {"name": "nodes"},
        {"name": "totem"},
        {"name": "join"},
        {"name": "qdevice"},
        {"name": "apiversion"},
    ]


async def test_cluster_join_info_shape_and_stable_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = HandlerRegistry()
    register_cluster_config_handlers(registry)
    pool = MetaPool()
    http = request(pool)
    monkeypatch.setattr(
        "app.handlers.cluster_config.TaskRepository",
        lambda _pool: FakeTaskRepository(pool),
    )
    await call(
        registry,
        "/cluster/config",
        "POST",
        http,
        {"values": {"clustername": "lab", "link0": "10.0.0.1"}, "provided": frozenset()},
    )
    first = await call(
        registry,
        "/cluster/config/join",
        "GET",
        http,
        {"values": {}, "provided": frozenset()},
    )
    second = await call(
        registry,
        "/cluster/config/join",
        "GET",
        http,
        {"values": {"node": "pve1"}, "provided": frozenset()},
    )
    assert set(first) == {"nodelist", "preferred_node", "totem", "config_digest"}
    assert first["config_digest"] == second["config_digest"]
    assert first["preferred_node"] == "pve1"
    defaulted = await call(
        registry,
        "/cluster/config/join",
        "GET",
        http,
        {
            "values": {"node": "current connected node"},
            "provided": frozenset(),
        },
    )
    assert defaulted["preferred_node"] == "pve1"
    node = first["nodelist"][0]
    assert node["name"] == "pve1"
    assert node["pve_addr"]
    assert node["ring0_addr"]
    assert node["pve_fp"].count(":") == 31
    assert "password" not in json.dumps(first)


async def test_cluster_join_returns_upid(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = HandlerRegistry()
    register_cluster_config_handlers(registry)
    pool = MetaPool()
    http = request(pool)
    repository = FakeTaskRepository(pool)
    monkeypatch.setattr("app.handlers.cluster_config.TaskRepository", lambda _pool: repository)
    fingerprint = ":".join(["AB"] * 32)
    upid = await call(
        registry,
        "/cluster/config/join",
        "POST",
        http,
        {
            "values": {
                "hostname": "10.0.0.1",
                "fingerprint": fingerprint,
                "password": "secret",
            },
            "provided": frozenset(),
        },
    )
    assert upid.startswith("UPID:")
    assert ":clusterjoin:" in upid
    assert repository.created[0]["task_type"] == "cluster-join"
    join = pool.metadata["cluster_config"]["join_info"]["10.0.0.1"]
    assert join["password_set"] is True
    assert "password" not in join


async def test_cluster_join_requires_contract_params() -> None:
    registry = HandlerRegistry()
    register_cluster_config_handlers(registry)
    pool = MetaPool()
    http = request(pool)
    with pytest.raises(ApiError, match="hostname"):
        await call(
            registry,
            "/cluster/config/join",
            "POST",
            http,
            {"values": {"password": "x", "fingerprint": "y"}, "provided": frozenset()},
        )


async def test_cluster_create_rejects_existing_corosync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = HandlerRegistry()
    register_cluster_config_handlers(registry)
    pool = MetaPool()
    http = request(pool)
    monkeypatch.setattr(
        "app.handlers.cluster_config.TaskRepository",
        lambda _pool: FakeTaskRepository(pool),
    )
    await call(
        registry,
        "/cluster/config",
        "POST",
        http,
        {"values": {"clustername": "lab", "link0": "10.0.0.1"}, "provided": frozenset()},
    )
    with pytest.raises(ApiError, match="cluster config already exists"):
        await call(
            registry,
            "/cluster/config",
            "POST",
            http,
            {"values": {"clustername": "other"}, "provided": frozenset()},
        )


async def test_cluster_addnode_returns_corosync_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = HandlerRegistry()
    register_cluster_config_handlers(registry)
    pool = MetaPool()
    http = request(pool)
    monkeypatch.setattr(
        "app.handlers.cluster_config.TaskRepository",
        lambda _pool: FakeTaskRepository(pool),
    )
    await call(
        registry,
        "/cluster/config",
        "POST",
        http,
        {"values": {"clustername": "lab", "link0": "10.0.0.1"}, "provided": frozenset()},
    )
    result = await call(
        registry,
        "/cluster/config/nodes/{node}",
        "POST",
        http,
        {
            "values": {"node": "pve2", "new_node_ip": "10.0.0.2", "votes": 1},
            "provided": frozenset(),
        },
    )
    assert set(result) == {"corosync_authkey", "corosync_conf", "warnings"}
    assert "nodelist" in result["corosync_conf"]
    assert "pve2" in result["corosync_conf"]
    assert result["warnings"] == []
    assert "pve2" in pool.nodes
    nodes = await call(
        registry,
        "/cluster/config/nodes",
        "GET",
        http,
        {"values": {}, "provided": frozenset()},
    )
    assert {item["node"] for item in nodes} == {"pve1", "pve2"}
