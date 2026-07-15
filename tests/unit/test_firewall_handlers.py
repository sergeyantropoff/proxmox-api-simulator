"""Firewall aliases/ipset/group persistence tests."""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import FastAPI, Request

from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.firewall import register_firewall_handlers
from app.simulation.seed import CLUSTER_ID


class FirewallPool:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "FROM clusters WHERE id" in query:
            return {"metadata": json.dumps(self.metadata)}
        raise AssertionError(query)

    async def fetchval(self, query: str, *arguments: object) -> Any:
        if "EXISTS(SELECT 1 FROM nodes" in query:
            return True
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "jsonb_set" in query:
            # args: CLUSTER_ID, firewall json
            self.metadata["firewall"] = json.loads(str(arguments[1]))
            return "UPDATE 1"
        raise AssertionError(query)


def request(pool: FirewallPool) -> Request:
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


async def test_firewall_alias_and_ipset_persist() -> None:
    registry = HandlerRegistry()
    register_firewall_handlers(registry)
    pool = FirewallPool()
    http = request(pool)
    create_alias = registry.get("/cluster/firewall/aliases", "POST")
    list_alias = registry.get("/cluster/firewall/aliases", "GET")
    create_ipset = registry.get("/cluster/firewall/ipset", "POST")
    add_ip = registry.get("/cluster/firewall/ipset/{name}", "POST")
    get_ipset = registry.get("/cluster/firewall/ipset/{name}", "GET")
    assert create_alias and list_alias and create_ipset and add_ip and get_ipset

    await create_alias(
        http, {"values": {"name": "lan", "cidr": "10.0.0.0/8"}, "provided": frozenset()}
    )
    aliases = await list_alias(http, {"values": {}, "provided": frozenset()})
    assert aliases[0]["name"] == "lan"
    await create_ipset(http, {"values": {"name": "blacklist"}, "provided": frozenset()})
    await add_ip(
        http,
        {"values": {"name": "blacklist", "cidr": "203.0.113.10"}, "provided": frozenset()},
    )
    entries = await get_ipset(http, {"values": {"name": "blacklist"}, "provided": frozenset()})
    assert entries[0]["cidr"] == "203.0.113.10"
    assert "scopes" in pool.metadata["firewall"]
    assert CLUSTER_ID
