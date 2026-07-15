"""Mapping / ACME / cluster-config durable handlers."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, Request

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


async def call(
    registry: HandlerRegistry, path: str, verb: str, http: Request, inputs: dict[str, Any]
) -> Any:
    handler = registry.get(path, verb)
    assert handler is not None
    return await handler(http, inputs)


def request(pool: MetaPool) -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, type("DB", (), {"pool": pool})())
    return Request(
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


async def test_mapping_acme_config_persist() -> None:
    registry = HandlerRegistry()
    register_mapping_handlers(registry)
    register_acme_handlers(registry)
    register_cluster_config_handlers(registry)
    pool = MetaPool()
    http = request(pool)

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
    assert account["name"] == "default"
    assert "eab-hmac-key" not in account

    await call(
        registry,
        "/cluster/config",
        "POST",
        http,
        {"values": {"clustername": "lab"}, "provided": frozenset()},
    )
    assert pool.metadata["cluster_config"]["clustername"] == "lab"
    assert pool.cluster_name == "lab"
    totem = await call(
        registry, "/cluster/config/totem", "GET", http, {"values": {}, "provided": frozenset()}
    )
    assert totem["cluster_name"] == "lab"
    assert uuid4()
