"""SDN zone/vnet/subnet persistence tests."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request

from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.sdn import register_sdn_handlers


class SdnPool:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}
        self.nodes = {"pve1"}

    async def fetch(self, query: str, *_arguments: object) -> list[dict[str, Any]]:
        if "FROM nodes" in query:
            return [{"name": name} for name in sorted(self.nodes)]
        raise AssertionError(query)

    async def fetchrow(self, query: str, *_arguments: object) -> dict[str, Any] | None:
        if "FROM clusters WHERE id" in query:
            return {"metadata": json.dumps(self.metadata)}
        raise AssertionError(query)

    async def fetchval(self, query: str, *arguments: object) -> Any:
        if "EXISTS(SELECT 1 FROM nodes" in query:
            return str(arguments[0]) in self.nodes
        if "SELECT name FROM nodes ORDER BY name LIMIT 1" in query:
            return sorted(self.nodes)[0]
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "UPDATE clusters SET metadata" in query:
            self.metadata = json.loads(str(arguments[1]))
            return "UPDATE 1"
        raise AssertionError(query)


class FakeTaskRepository:
    def __init__(self, pool: SdnPool) -> None:
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


def request(pool: SdnPool) -> Request:
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


async def test_sdn_zone_vnet_subnet_and_node_views(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = HandlerRegistry()
    register_sdn_handlers(registry)
    pool = SdnPool()
    http = request(pool)
    repository = FakeTaskRepository(pool)
    monkeypatch.setattr("app.handlers.cluster_extra.TaskRepository", lambda _pool: repository)

    await call(
        registry,
        "/cluster/sdn/zones",
        "POST",
        http,
        {"values": {"zone": "localzone", "type": "simple"}, "provided": frozenset()},
    )
    await call(
        registry,
        "/cluster/sdn/vnets",
        "POST",
        http,
        {
            "values": {"vnet": "vnet0", "zone": "localzone", "type": "vnet"},
            "provided": frozenset(),
        },
    )
    await call(
        registry,
        "/cluster/sdn/vnets/{vnet}/subnets",
        "POST",
        http,
        {
            "values": {
                "vnet": "vnet0",
                "subnet": "10.0.0.0/24",
                "gateway": "10.0.0.1",
            },
            "provided": frozenset(),
        },
    )
    zones = await call(
        registry, "/cluster/sdn/zones", "GET", http, {"values": {}, "provided": frozenset()}
    )
    assert zones[0]["zone"] == "localzone"
    subnets = await call(
        registry,
        "/cluster/sdn/vnets/{vnet}/subnets",
        "GET",
        http,
        {"values": {"vnet": "vnet0"}, "provided": frozenset()},
    )
    assert subnets[0]["subnet"] == "10.0.0.0/24"
    node_zones = await call(
        registry,
        "/nodes/{node}/sdn/zones",
        "GET",
        http,
        {"values": {"node": "pve1"}, "provided": frozenset()},
    )
    assert node_zones[0]["zone"] == "localzone"
    assert pool.metadata["sdn"]["pending"] is True
    upid = await call(
        registry,
        "/cluster/sdn",
        "PUT",
        http,
        {"values": {"release-lock": 1}, "provided": frozenset()},
    )
    assert isinstance(upid, str) and upid.startswith("UPID:")
    assert pool.metadata["sdn"]["pending"] is False
    lock_token = await call(
        registry,
        "/cluster/sdn/lock",
        "POST",
        http,
        {"values": {}, "provided": frozenset()},
    )
    assert isinstance(lock_token, str) and len(lock_token) >= 8
