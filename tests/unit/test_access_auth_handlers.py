"""TFA / OpenID / permissions access handlers."""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from pydantic import SecretStr

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.config import Settings
from app.db.pool import AsyncpgDatabase
from app.handlers.access_auth import register_access_auth_handlers
from app.security.auth import issue_ticket


class AuthPool:
    def __init__(self) -> None:
        self.principals = {
            "root@pam": {
                "id": uuid.uuid4(),
                "tfa_locked_until": None,
                "totp_locked": False,
            }
        }
        self.tfa: dict[tuple[uuid.UUID, str], dict[str, Any]] = {}
        self.realms = {
            "sso": {
                "kind": "openid",
                "config": {
                    "issuer-url": "https://idp.example",
                    "client-id": "pve",
                },
            }
        }
        self.pending: dict[str, dict[str, str]] = {}

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, Any]]:
        if "FROM principals p" in query and "LEFT JOIN tfa_entries" in query:
            rows: list[dict[str, Any]] = []
            for name, data in self.principals.items():
                matches = [item for key, item in self.tfa.items() if key[0] == data["id"]]
                if not matches:
                    rows.append(
                        {
                            "userid": name,
                            "tfa_locked_until": data["tfa_locked_until"],
                            "totp_locked": data["totp_locked"],
                            "entry_id": None,
                            "tfa_type": None,
                            "description": None,
                            "enable": None,
                            "created_at": 0,
                        }
                    )
                for item in matches:
                    rows.append(
                        {
                            "userid": name,
                            "tfa_locked_until": data["tfa_locked_until"],
                            "totp_locked": data["totp_locked"],
                            **item,
                        }
                    )
            return rows
        if "FROM tfa_entries" in query and "DISTINCT" in query:
            principal_id = arguments[0]
            types = sorted(
                {
                    item["tfa_type"]
                    for key, item in self.tfa.items()
                    if key[0] == principal_id and item["enable"]
                }
            )
            return [{"tfa_type": value} for value in types]
        if "FROM tfa_entries WHERE principal_id" in query or (
            "FROM tfa_entries" in query and "principal_id=$1" in query and "DISTINCT" not in query
        ):
            principal_id = arguments[0]
            return [item for key, item in self.tfa.items() if key[0] == principal_id]
        if "FROM acl_entries" in query:
            return []
        raise AssertionError(query)

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, Any] | None:
        if "FROM principals WHERE name" in query:
            userid = str(arguments[0])
            data = self.principals.get(userid)
            if data is None:
                return None
            return {"name": userid, **data}
        if "FROM realms WHERE name" in query:
            realm = str(arguments[0])
            realm_data = self.realms.get(realm)
            if realm_data is None:
                return None
            return {"name": realm, **realm_data}
        if "FROM openid_pending WHERE state" in query:
            return self.pending.get(str(arguments[0]))
        if "FROM tfa_entries WHERE principal_id" in query:
            key = (cast(uuid.UUID, arguments[0]), str(arguments[1]))
            item = self.tfa.get(key)
            return item
        raise AssertionError(query)

    async def fetchval(self, query: str, *arguments: object) -> Any:
        if "EXISTS(SELECT 1 FROM principals" in query:
            return str(arguments[0]) in self.principals
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "INSERT INTO openid_pending" in query:
            self.pending[str(arguments[0])] = {
                "realm": str(arguments[1]),
                "redirect_url": str(arguments[2]),
            }
            return "INSERT 0 1"
        if "DELETE FROM openid_pending" in query:
            self.pending.pop(str(arguments[0]), None)
            return "DELETE 1"
        if "INSERT INTO principals" in query:
            self.principals[str(arguments[0])] = {
                "id": uuid.uuid4(),
                "tfa_locked_until": None,
                "totp_locked": False,
            }
            return "INSERT 0 1"
        if "INSERT INTO tfa_entries" in query:
            principal_id = cast(uuid.UUID, arguments[0])
            entry_id = str(arguments[1])
            self.tfa[(principal_id, entry_id)] = {
                "entry_id": entry_id,
                "tfa_type": str(arguments[2]),
                "description": arguments[3],
                "enable": True,
                "created_at": 1_700_000_000,
                "secret": arguments[4],
                "metadata": json.loads(str(arguments[5])),
            }
            return "INSERT 0 1"
        if "UPDATE tfa_entries SET enable" in query:
            key = (cast(uuid.UUID, arguments[0]), str(arguments[1]))
            self.tfa[key]["enable"] = bool(arguments[2])
            return "UPDATE 1"
        if "UPDATE tfa_entries SET description" in query:
            key = (cast(uuid.UUID, arguments[0]), str(arguments[1]))
            self.tfa[key]["description"] = arguments[2]
            return "UPDATE 1"
        if "DELETE FROM tfa_entries" in query:
            key = (cast(uuid.UUID, arguments[0]), str(arguments[1]))
            if key not in self.tfa:
                return "DELETE 0"
            del self.tfa[key]
            return "DELETE 1"
        if "UPDATE principals" in query and "totp_locked" in query:
            userid = str(arguments[0])
            if userid not in self.principals:
                return "UPDATE 0"
            self.principals[userid]["tfa_locked_until"] = None
            self.principals[userid]["totp_locked"] = False
            return "UPDATE 1"
        raise AssertionError(query)


class FakeDatabase:
    def __init__(self, pool: AuthPool) -> None:
        self.pool = pool


def request(pool: AuthPool, principal: str = "root@pam") -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, FakeDatabase(pool))
    app.state.settings = Settings(ticket_signing_key=SecretStr("test-signing-key"))
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


async def test_tfa_lifecycle_and_unlock_persist() -> None:
    registry = HandlerRegistry()
    register_access_auth_handlers(registry)
    pool = AuthPool()
    http = request(pool)
    create = registry.get("/access/tfa/{userid}", "POST")
    listing = registry.get("/access/tfa/{userid}", "GET")
    get = registry.get("/access/tfa/{userid}/{id}", "GET")
    update = registry.get("/access/tfa/{userid}/{id}", "PUT")
    delete = registry.get("/access/tfa/{userid}/{id}", "DELETE")
    unlock = registry.get("/access/users/{userid}/unlock-tfa", "PUT")
    types = registry.get("/access/users/{userid}/tfa", "GET")
    assert create and listing and get and update and delete and unlock and types

    created = await create(http, values(userid="root@pam", type="totp", description="phone"))
    entry_id = created["id"]
    assert await listing(http, values(userid="root@pam"))
    fetched = await get(http, values(userid="root@pam", id=entry_id))
    assert fetched["type"] == "totp"
    await update(http, values(userid="root@pam", id=entry_id, enable=0))
    assert (await get(http, values(userid="root@pam", id=entry_id)))["enable"] == 0
    assert await unlock(http, values(userid="root@pam")) is True
    assert (await types(http, values(userid="root@pam")))["types"] == []
    await delete(http, values(userid="root@pam", id=entry_id))
    with pytest.raises(ApiError):
        await get(http, values(userid="root@pam", id=entry_id))


async def test_openid_auth_url_and_login_create_principal() -> None:
    registry = HandlerRegistry()
    register_access_auth_handlers(registry)
    pool = AuthPool()
    http = request(pool)
    auth_url = registry.get("/access/openid/auth-url", "POST")
    login = registry.get("/access/openid/login", "POST")
    assert auth_url and login

    url = await auth_url(
        http,
        values(realm="sso", **{"redirect-url": "https://pve.local/api2/json/access/openid/login"}),
    )
    assert "https://idp.example/authorize?" in url
    assert pool.pending
    state = next(iter(pool.pending))
    result = await login(
        http,
        values(
            code="abc1234567890",
            state=state,
            **{"redirect-url": "https://pve.local/api2/json/access/openid/login"},
        ),
    )
    assert result["ticket"].startswith("PVE:")
    assert any(name.endswith("@sso") for name in pool.principals)


async def test_permissions_and_vncticket() -> None:
    registry = HandlerRegistry()
    register_access_auth_handlers(registry)
    pool = AuthPool()
    http = request(pool)
    permissions = registry.get("/access/permissions", "GET")
    vncticket = registry.get("/access/vncticket", "POST")
    ticket_get = registry.get("/access/ticket", "GET")
    assert permissions and vncticket and ticket_get

    caps = await permissions(http, values())
    assert "/" in caps
    assert await ticket_get(http, values()) is None
    ticket = issue_ticket("root@pam", b"test-signing-key")
    await vncticket(
        http,
        values(
            authid="root@pam",
            path="/nodes/pve01/qemu/100/vncwebsocket",
            privs="Sys.Console",
            vncticket=ticket,
        ),
    )
