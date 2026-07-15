"""Notification endpoints/matchers persistence."""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import FastAPI, Request

from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.notifications import register_notifications_handlers
from app.simulation.seed import CLUSTER_ID


class NotesPool:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "FROM clusters WHERE id" in query:
            return {"metadata": json.dumps(self.metadata)}
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "UPDATE clusters SET metadata" in query:
            self.metadata = json.loads(str(arguments[1]))
            return "UPDATE 1"
        raise AssertionError(query)


def request(pool: NotesPool) -> Request:
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


async def test_notification_endpoint_and_matcher_persist() -> None:
    registry = HandlerRegistry()
    register_notifications_handlers(registry)
    pool = NotesPool()
    http = request(pool)
    create = registry.get("/cluster/notifications/endpoints/gotify", "POST")
    get = registry.get("/cluster/notifications/endpoints/gotify/{name}", "GET")
    matchers = registry.get("/cluster/notifications/matchers", "POST")
    targets = registry.get("/cluster/notifications/targets", "GET")
    test = registry.get("/cluster/notifications/targets/{name}/test", "POST")
    assert create and get and matchers and targets and test

    await create(
        http,
        {
            "values": {
                "name": "ops",
                "server": "https://gotify.local",
                "token": "secret-token",
            },
            "provided": frozenset(),
        },
    )
    payload = await get(http, {"values": {"name": "ops"}, "provided": frozenset()})
    assert payload["server"] == "https://gotify.local"
    assert "token" not in payload
    await matchers(
        http,
        {
            "values": {"name": "all-mail", "target": "ops", "mode": "all"},
            "provided": frozenset(),
        },
    )
    listed = await targets(http, {"values": {}, "provided": frozenset()})
    assert listed[0]["name"] == "ops"
    await test(http, {"values": {"name": "ops"}, "provided": frozenset()})
    assert pool.metadata["notifications"]["tests"]
    assert CLUSTER_ID
