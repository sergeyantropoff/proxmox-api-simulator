"""API-token lifecycle handler tests without external services."""

import json
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


class RealmPool:
    def __init__(self) -> None:
        self.realms: dict[str, dict[str, Any]] = {
            "pam": {
                "kind": "pam",
                "config": {"comment": "Linux PAM standard authentication"},
            },
            "pve": {
                "kind": "pve",
                "config": {"comment": "Proxmox VE authentication server"},
            },
        }
        self.principals: dict[str, str] = {"root@pam": "pam"}

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, Any]]:
        del arguments
        if "FROM realms ORDER BY name" in query:
            return [
                {"name": name, "kind": data["kind"], "config": dict(data["config"])}
                for name, data in sorted(self.realms.items())
            ]
        raise AssertionError(query)

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "FROM realms WHERE name" in query:
            realm = str(arguments[0])
            data = self.realms.get(realm)
            if data is None:
                return None
            return {"name": realm, "kind": data["kind"], "config": dict(data["config"])}
        raise AssertionError(query)

    async def fetchval(self, query: str, *arguments: object) -> bool:
        realm = str(arguments[0])
        if "EXISTS(SELECT 1 FROM realms" in query:
            return realm in self.realms
        if "EXISTS(SELECT 1 FROM principals" in query:
            return any(value == realm for value in self.principals.values())
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "INSERT INTO realms" in query:
            self.realms[str(arguments[0])] = {
                "kind": str(arguments[1]),
                "config": json.loads(str(arguments[2])),
            }
            return "INSERT 0 1"
        if "UPDATE realms SET config=$2" in query:
            realm = str(arguments[0])
            self.realms[realm]["config"] = json.loads(str(arguments[1]))
            return "UPDATE 1"
        if "SET config = config - 'default'" in query:
            skip = str(arguments[0]) if arguments else None
            for name, data in self.realms.items():
                if skip is not None and name == skip:
                    continue
                data["config"].pop("default", None)
            return "UPDATE 0"
        if "DELETE FROM realms" in query:
            realm = str(arguments[0])
            if realm not in self.realms:
                return "DELETE 0"
            del self.realms[realm]
            return "DELETE 1"
        raise AssertionError(query)


class FakeDatabase:
    def __init__(self, pool: TokenPool | RealmPool) -> None:
        self.pool = pool


def request(pool: TokenPool | RealmPool, principal: str = "root@pam") -> Request:
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
    return {"values": items, "provided": frozenset(items)}


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


async def test_domain_lifecycle_persists_realm_config() -> None:
    registry = HandlerRegistry()
    register_access_handlers(registry)
    pool = RealmPool()
    http_request = request(pool)
    create = registry.get("/access/domains", "POST")
    listing = registry.get("/access/domains", "GET")
    get = registry.get("/access/domains/{realm}", "GET")
    update = registry.get("/access/domains/{realm}", "PUT")
    delete = registry.get("/access/domains/{realm}", "DELETE")
    assert create and listing and get and update and delete

    await create(
        http_request,
        values(
            realm="corp",
            type="ldap",
            comment="Corporate LDAP",
            server1="ldap.example.com",
            password="secret",  # noqa: S106 - fixture secret for unit test
            default=1,
        ),
    )
    listed = await listing(http_request, values())
    assert any(item["realm"] == "corp" and item["type"] == "ldap" for item in listed)
    created = await get(http_request, values(realm="corp"))
    assert created["comment"] == "Corporate LDAP"
    assert created["server1"] == "ldap.example.com"
    assert created["default"] == 1
    assert "password" not in created

    await update(
        http_request,
        values(realm="corp", comment="Updated LDAP", delete="default"),
    )
    updated = await get(http_request, values(realm="corp"))
    assert updated["comment"] == "Updated LDAP"
    assert "default" not in updated

    await delete(http_request, values(realm="corp"))
    with pytest.raises(ApiError) as missing:
        await get(http_request, values(realm="corp"))
    assert missing.value.status_code == 404


async def test_domain_delete_rejects_builtin_and_in_use_realms() -> None:
    registry = HandlerRegistry()
    register_access_handlers(registry)
    pool = RealmPool()
    http_request = request(pool)
    delete = registry.get("/access/domains/{realm}", "DELETE")
    assert delete

    with pytest.raises(ApiError) as builtin:
        await delete(http_request, values(realm="pam"))
    assert builtin.value.status_code == 400

    pool.realms["corp"] = {"kind": "ldap", "config": {}}
    pool.principals["alice@corp"] = "corp"
    with pytest.raises(ApiError) as in_use:
        await delete(http_request, values(realm="corp"))
    assert in_use.value.status_code == 400
