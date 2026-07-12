"""API-token lifecycle handler tests without external services."""

from typing import Any, cast

import pytest
from fastapi import FastAPI, Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.access import register_access_handlers


class TokenPool:
    def __init__(self) -> None:
        self.token: dict[str, Any] | None = None

    async def fetch(self, _query: str, _userid: str) -> list[dict[str, Any]]:
        return [] if self.token is None else [{"token_id": "test", **self.token}]

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "INSERT INTO" in query:
            self.token = {
                "comment": arguments[3],
                "privilege_separation": arguments[5],
                "expire": arguments[4],
            }
            return self.token
        if "UPDATE api_tokens" in query:
            if self.token is None:
                return None
            self.token["comment"] = arguments[2]
            self.token["privilege_separation"] = arguments[4]
            return self.token
        return self.token

    async def fetchval(self, _query: str, _userid: str) -> bool:
        return True

    async def execute(self, _query: str, _userid: str, _tokenid: str) -> str:
        if self.token is None:
            return "DELETE 0"
        self.token = None
        return "DELETE 1"


class FakeDatabase:
    def __init__(self, pool: TokenPool) -> None:
        self.pool = pool


def request(pool: TokenPool, principal: str = "root@pam") -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, FakeDatabase(pool))
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
    result.state.principal = principal
    return result


def values(**items: object) -> dict[str, Any]:
    return {"values": items}


async def test_token_lifecycle_returns_secret_once_and_persists_metadata() -> None:
    registry = HandlerRegistry()
    register_access_handlers(registry)
    pool = TokenPool()
    http_request = request(pool)
    create = registry.get("/access/users/{userid}/token/{tokenid}", "POST")
    get = registry.get("/access/users/{userid}/token/{tokenid}", "GET")
    update = registry.get("/access/users/{userid}/token/{tokenid}", "PUT")
    delete = registry.get("/access/users/{userid}/token/{tokenid}", "DELETE")
    list_tokens = registry.get("/access/users/{userid}/token", "GET")
    assert create and get and update and delete and list_tokens

    created = await create(
        http_request,
        values(userid="root@pam", tokenid="test", comment="first", privsep=True),
    )
    assert created["full-tokenid"] == "root@pam!test"
    assert created["value"]
    assert "value" not in await get(http_request, values(userid="root@pam", tokenid="test"))
    assert await list_tokens(http_request, values(userid="root@pam"))

    updated = await update(
        http_request,
        values(userid="root@pam", tokenid="test", comment="second", privsep=False),
    )
    assert updated["comment"] == "second"
    await delete(http_request, values(userid="root@pam", tokenid="test"))
    with pytest.raises(ApiError) as missing:
        await get(http_request, values(userid="root@pam", tokenid="test"))
    assert missing.value.status_code == 404


async def test_token_lifecycle_rejects_non_owner() -> None:
    registry = HandlerRegistry()
    register_access_handlers(registry)
    handler = registry.get("/access/users/{userid}/token", "GET")
    assert handler
    with pytest.raises(ApiError) as denied:
        await handler(request(TokenPool(), "auditor@pve"), values(userid="other@pve"))
    assert denied.value.status_code == 403
