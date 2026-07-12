"""HTTP-boundary API-token and contract permission tests."""

from typing import Any, cast

import pytest
from fastapi import FastAPI, Request

from app.api.errors import ApiError
from app.api.registry import _authenticate
from app.config import Settings
from app.contracts.model import Method, Permissions, Schema
from app.db.pool import AsyncpgDatabase
from app.security.auth import hash_secret


class FakePool:
    def __init__(self, secret: str, token_privileges: list[str]) -> None:
        self.secret_hash = hash_secret(secret, salt=b"boundary-token-v1")
        self.token_privileges = token_privileges

    async def fetchrow(self, _query: str, principal: str, token_id: str) -> dict[str, Any] | None:
        if principal != "operator@pve" or token_id != "api":
            return None
        return {
            "name": principal,
            "secret_hash": self.secret_hash,
            "privileges": self.token_privileges,
        }

    async def fetch(self, _query: str, principal: str) -> list[dict[str, Any]]:
        return [
            {
                "path": "/vms",
                "propagate": True,
                "privileges": ["VM.Audit", "VM.PowerMgmt"],
                "principal": principal,
            }
        ]


class FakeDatabase:
    def __init__(self, pool: FakePool) -> None:
        self.pool = pool


def token_request(secret: str, token_privileges: list[str]) -> Request:
    app = FastAPI()
    app.state.settings = Settings()
    app.state.database = cast(AsyncpgDatabase, FakeDatabase(FakePool("valid", token_privileges)))
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "POST",
            "path": "/api2/json/nodes/pve1/qemu/101/status/start",
            "headers": [(b"authorization", f"PVEAPIToken=operator@pve!api={secret}".encode())],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 123),
            "scheme": "http",
        }
    )


def power_method() -> Method:
    return Method(
        verb="POST",
        name="start",
        returns=Schema(type="string"),
        permissions=Permissions(expression={"check": ["perm", "/vms/{vmid}", ["VM.PowerMgmt"]]}),
        checksum="1" * 64,
    )


async def test_api_token_skips_csrf_but_honors_separated_privileges() -> None:
    allowed = token_request("valid", ["VM.PowerMgmt"])
    await _authenticate(
        allowed,
        "/nodes/{node}/qemu/{vmid}/status/start",
        power_method(),
        {"values": {"node": "pve1", "vmid": 101}},
    )
    assert allowed.state.principal == "operator@pve"

    denied = token_request("valid", ["VM.Audit"])
    with pytest.raises(ApiError) as error:
        await _authenticate(
            denied,
            "/nodes/{node}/qemu/{vmid}/status/start",
            power_method(),
            {"values": {"node": "pve1", "vmid": 101}},
        )
    assert error.value.status_code == 403


async def test_api_token_rejects_unknown_or_wrong_secret() -> None:
    request = token_request("wrong", ["VM.PowerMgmt"])
    with pytest.raises(ApiError) as error:
        await _authenticate(
            request,
            "/nodes/{node}/qemu/{vmid}/status/start",
            power_method(),
            {"values": {"node": "pve1", "vmid": 101}},
        )
    assert error.value.status_code == 401
