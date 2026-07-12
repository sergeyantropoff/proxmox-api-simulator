"""First read/login semantic service handlers."""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.config import Settings
from app.db.pool import AsyncpgDatabase
from app.handlers.qemu import register_qemu_handlers
from app.security.auth import csrf_token, issue_ticket, verify_secret


def _database(request: Request) -> AsyncpgDatabase:
    return cast(AsyncpgDatabase, request.app.state.database)


def build_core_handlers(settings: Settings) -> HandlerRegistry:
    registry = HandlerRegistry()

    async def version(_request: Request, _inputs: dict[str, Any]) -> dict[str, str]:
        return {"version": "9.2.3", "release": "9.2", "repoid": "simulator"}

    async def login(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = cast(dict[str, Any], inputs["values"])
        username = str(values["username"])
        password = str(values["password"])
        row = await _database(request).pool.fetchrow(
            "SELECT name, password_hash FROM principals WHERE name=$1", username
        )
        if (
            row is None
            or row["password_hash"] is None
            or not verify_secret(password, str(row["password_hash"]))
        ):
            raise ApiError(401, "authentication failure")
        key = settings.ticket_signing_key.get_secret_value().encode()
        ticket = issue_ticket(username, key)
        return {
            "username": username,
            "ticket": ticket,
            "CSRFPreventionToken": csrf_token(ticket, key),
            "cap": {"vms": {"VM.Audit": 1, "VM.PowerMgmt": 1}},
        }

    async def nodes(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await _database(request).pool.fetch(
            "SELECT name AS node, status FROM nodes ORDER BY name"
        )
        return [{"node": str(row["node"]), "status": str(row["status"])} for row in rows]

    async def node_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(cast(dict[str, Any], inputs["values"])["node"])
        row = await _database(request).pool.fetchrow(
            "SELECT name, status FROM nodes WHERE name=$1", node
        )
        if row is None:
            raise ApiError(404, "node does not exist")
        return {
            "status": str(row["status"]),
            "node": str(row["name"]),
            "uptime": 0,
            "cpu": 0.0,
            "memory": {"used": 0, "total": 0},
        }

    async def resources(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await _database(request).pool.fetch(
            """SELECT r.kind AS type, r.external_id, r.state, n.name AS node
            FROM resources r JOIN nodes n ON n.id=r.node_id
            ORDER BY r.kind, r.external_id"""
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            raw_state = row["state"]
            state = json.loads(raw_state) if isinstance(raw_state, str) else dict(raw_state)
            result.append(
                {
                    "type": str(row["type"]),
                    "id": f"{row['type']}/{row['external_id']}",
                    "node": str(row["node"]),
                    **state,
                }
            )
        return result

    registry.register("/version", "GET", version)
    registry.register("/access/ticket", "POST", login)
    registry.register("/nodes", "GET", nodes)
    registry.register("/nodes/{node}/status", "GET", node_status)
    registry.register("/cluster/resources", "GET", resources)
    register_qemu_handlers(registry)
    return registry
