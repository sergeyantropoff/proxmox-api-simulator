"""Persistence tests for remaining gap handlers (nodes_extra / cluster_extra)."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request

from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.cluster_extra import register_cluster_extra_handlers
from app.handlers.nodes_extra import register_nodes_extra_handlers


class GapRemainingPool:
    def __init__(self) -> None:
        self.cluster_metadata: dict[str, Any] = {}
        self.node_metadata: dict[str, Any] = {}

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "SELECT metadata FROM clusters" in query:
            return {"metadata": json.dumps(self.cluster_metadata)}
        if "SELECT metadata FROM nodes" in query:
            name = str(arguments[0])
            return {"metadata": json.dumps(self.node_metadata.get(name, {}))}
        raise AssertionError(query)

    async def fetchval(self, query: str, *arguments: object) -> Any:
        if "EXISTS(SELECT 1 FROM nodes" in query:
            return True
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "UPDATE clusters SET metadata" in query:
            self.cluster_metadata = json.loads(str(arguments[1]))
            return "UPDATE 1"
        if "UPDATE nodes SET metadata" in query:
            self.node_metadata[str(arguments[0])] = json.loads(str(arguments[1]))
            return "UPDATE 1"
        raise AssertionError(query)


class FakeDatabase:
    def __init__(self, pool: GapRemainingPool) -> None:
        self.pool = pool


def _request(pool: GapRemainingPool, *, method: str = "GET") -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, FakeDatabase(pool))
    result = Request(
        {
            "type": "http",
            "app": app,
            "method": method,
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


@pytest.mark.asyncio
async def test_disks_directory_create_persists() -> None:
    registry = HandlerRegistry()
    register_nodes_extra_handlers(registry)
    pool = GapRemainingPool()
    create = registry.get("/nodes/{node}/disks/directory", "POST")
    assert create is not None
    created = await create(
        _request(pool, method="POST"),
        {
            "values": {"node": "pve01", "name": "tank", "device": "/dev/sdb"},
            "provided": frozenset(),
        },
    )
    assert created["name"] == "tank"
    ops = pool.node_metadata["pve01"]["ops"]
    assert any(item["name"] == "tank" for item in ops["disks"]["directory"])


@pytest.mark.asyncio
async def test_certificates_custom_create_does_not_echo_key() -> None:
    registry = HandlerRegistry()
    register_nodes_extra_handlers(registry)
    pool = GapRemainingPool()
    create = registry.get("/nodes/{node}/certificates/custom", "POST")
    info = registry.get("/nodes/{node}/certificates/info", "GET")
    assert create is not None and info is not None
    await create(
        _request(pool, method="POST"),
        {
            "values": {
                "node": "pve01",
                "certificates": "-----BEGIN CERTIFICATE-----\nSIM\n-----END CERTIFICATE-----",
                "key": "-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----",
            },
            "provided": frozenset(),
        },
    )
    stored = pool.node_metadata["pve01"]["ops"]["certificates"]["custom"]
    assert stored["key"].startswith("-----BEGIN PRIVATE KEY-----")
    listing = await info(
        _request(pool),
        {"values": {"node": "pve01"}, "provided": frozenset()},
    )
    blob = json.dumps(listing)
    assert "PRIVATE KEY" not in blob
    assert "SECRET" not in blob


@pytest.mark.asyncio
async def test_realm_sync_job_create_persists() -> None:
    registry = HandlerRegistry()
    register_cluster_extra_handlers(registry)
    pool = GapRemainingPool()
    create = registry.get("/cluster/jobs/realm-sync/{id}", "POST")
    listing = registry.get("/cluster/jobs/realm-sync", "GET")
    assert create is not None and listing is not None
    created = await create(
        _request(pool, method="POST"),
        {
            "values": {"id": "pam-nightly", "realm": "pam", "schedule": "0 2 * * *"},
            "provided": frozenset(),
        },
    )
    assert created["id"] == "pam-nightly"
    assert pool.cluster_metadata["jobs"]["realm_sync"]["pam-nightly"]["realm"] == "pam"
    items = await listing(_request(pool), {"values": {}, "provided": frozenset()})
    assert items[0]["id"] == "pam-nightly"


@pytest.mark.asyncio
async def test_metrics_server_create_persists() -> None:
    registry = HandlerRegistry()
    register_cluster_extra_handlers(registry)
    pool = GapRemainingPool()
    create = registry.get("/cluster/metrics/server/{id}", "POST")
    listing = registry.get("/cluster/metrics/server", "GET")
    assert create is not None and listing is not None
    created = await create(
        _request(pool, method="POST"),
        {
            "values": {
                "id": "influx1",
                "type": "influxdb",
                "server": "10.0.0.20",
                "port": 8089,
            },
            "provided": frozenset(),
        },
    )
    assert created["id"] == "influx1"
    assert pool.cluster_metadata["metrics"]["servers"]["influx1"]["server"] == "10.0.0.20"
    items = await listing(_request(pool), {"values": {}, "provided": frozenset()})
    assert items[0]["id"] == "influx1"
