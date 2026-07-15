"""First read/login semantic service handlers."""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.config import Settings
from app.contracts.runtime import runtime_version_payload
from app.db.pool import AsyncpgDatabase
from app.handlers.access import register_access_handlers
from app.handlers.acme import register_acme_handlers
from app.handlers.backup import register_backup_handlers
from app.handlers.ceph import register_ceph_handlers
from app.handlers.cluster import register_cluster_handlers
from app.handlers.cluster_config import register_cluster_config_handlers
from app.handlers.cluster_extra import register_cluster_extra_handlers
from app.handlers.common import require_node, subdirs
from app.handlers.firewall import register_firewall_handlers
from app.handlers.ha import register_ha_handlers
from app.handlers.legacy_aliases import register_legacy_aliases
from app.handlers.lxc import register_lxc_handlers
from app.handlers.mapping import register_mapping_handlers
from app.handlers.nodes import register_node_ops_handlers
from app.handlers.nodes_extra import register_nodes_extra_handlers
from app.handlers.notifications import register_notifications_handlers
from app.handlers.pools import register_pool_handlers
from app.handlers.qemu import register_qemu_handlers
from app.handlers.sdn import register_sdn_handlers
from app.handlers.storage import register_storage_handlers
from app.security.auth import csrf_token, issue_ticket, verify_secret


def _database(request: Request) -> AsyncpgDatabase:
    return cast(AsyncpgDatabase, request.app.state.database)


def build_core_handlers(settings: Settings) -> HandlerRegistry:
    registry = HandlerRegistry()

    async def version(request: Request, _inputs: dict[str, Any]) -> dict[str, str]:
        return runtime_version_payload(request)

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

    async def node_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        node = str(cast(dict[str, Any], inputs["values"])["node"])
        await require_node(request, node)
        return subdirs(
            "apt",
            "ceph",
            "disks",
            "firewall",
            "lxc",
            "network",
            "qemu",
            "services",
            "status",
            "storage",
            "tasks",
            "version",
            "vzdump",
        )

    async def node_version(request: Request, inputs: dict[str, Any]) -> dict[str, str]:
        node = str(cast(dict[str, Any], inputs["values"])["node"])
        await require_node(request, node)
        return runtime_version_payload(request)

    registry.register("/version", "GET", version)
    registry.register("/access/ticket", "POST", login)
    registry.register("/nodes", "GET", nodes)
    registry.register("/nodes/{node}", "GET", node_index)
    registry.register("/nodes/{node}/status", "GET", node_status)
    registry.register("/nodes/{node}/version", "GET", node_version)
    registry.register("/cluster/resources", "GET", resources)
    register_access_handlers(registry)
    register_cluster_handlers(registry)
    register_notifications_handlers(registry)
    register_mapping_handlers(registry)
    register_acme_handlers(registry)
    register_cluster_config_handlers(registry)
    register_sdn_handlers(registry)
    register_storage_handlers(registry)

    register_pool_handlers(registry)
    register_ceph_handlers(registry)
    register_backup_handlers(registry)
    register_ha_handlers(registry)
    register_node_ops_handlers(registry)
    register_firewall_handlers(registry)
    register_qemu_handlers(registry)
    register_lxc_handlers(registry)
    register_nodes_extra_handlers(registry)
    register_cluster_extra_handlers(registry)
    register_legacy_aliases(registry)
    return registry
