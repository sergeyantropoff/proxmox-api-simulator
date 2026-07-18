"""High availability semantic handlers."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import (
    cluster_metadata,
    database,
    save_cluster_metadata,
    state,
    subdirs,
    values,
)
from app.simulation.seed import CLUSTER_ID, stable_id


def _ha_groups(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = metadata.get("ha_groups", {})
    if not isinstance(groups, dict):
        return {}
    return {str(key): dict(value) for key, value in groups.items() if isinstance(value, dict)}


def register_ha_handlers(registry: HandlerRegistry) -> None:
    async def ha_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("groups", "resources", "rules", "status")

    async def ha_resources(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            """SELECT r.external_id, r.state, n.name AS node
            FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE r.kind='ha' ORDER BY r.external_id"""
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = state(row["state"])
            sid = str(row["external_id"])
            result.append(
                {
                    "sid": sid,
                    "type": "vm" if sid.startswith("vm:") else "ct",
                    "state": payload.get("state", "started"),
                    "group": payload.get("group"),
                    "node": str(row["node"]),
                    "max_relocate": payload.get("max_relocate", 1),
                    "max_restart": payload.get("max_restart", 1),
                }
            )
        return result

    async def ha_resource_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        sid = str(values(inputs)["sid"])
        items = await ha_resources(request, inputs)
        for item in items:
            if item["sid"] == sid:
                return item
        raise ApiError(404, "HA resource does not exist")

    async def ha_resource_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        sid = str(payload["sid"])
        group = str(payload.get("group") or "")
        exists = await database(request).pool.fetchval(
            """SELECT EXISTS(SELECT 1 FROM resources WHERE kind='ha' AND external_id=$1)""",
            sid,
        )
        if exists:
            raise ApiError(409, "HA resource already exists")
        guest_kind, _, guest_id = sid.partition(":")
        if guest_kind not in {"vm", "ct"} or not guest_id.isdigit():
            raise ApiError(400, "invalid HA resource sid")
        resource_kind = "qemu" if guest_kind == "vm" else "lxc"
        guest = await database(request).pool.fetchrow(
            """SELECT r.id, n.name FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE r.kind=$1 AND r.external_id=$2""",
            resource_kind,
            guest_id,
        )
        if guest is None:
            raise ApiError(404, "guest does not exist")
        node = await database(request).pool.fetchrow(
            "SELECT id FROM nodes WHERE name=$1",
            str(guest["name"]),
        )
        if node is None:
            raise ApiError(404, "node does not exist")
        ha_state = {
            "state": str(payload.get("state") or "started"),
            "group": group or None,
            "max_relocate": int(payload.get("max_relocate") or 1),
            "max_restart": int(payload.get("max_restart") or 1),
        }
        await database(request).pool.execute(
            """INSERT INTO resources(id, node_id, cluster_id, kind, external_id, state, metadata)
            VALUES($1, $2, $3, 'ha', $4, $5::jsonb, '{}'::jsonb)""",
            stable_id(f"ha:{sid}"),
            node["id"],
            CLUSTER_ID,
            sid,
            json.dumps(ha_state, sort_keys=True),
        )

    async def ha_resource_update(request: Request, inputs: dict[str, Any]) -> None:
        sid = str(values(inputs)["sid"])
        payload = values(inputs)
        row = await database(request).pool.fetchrow(
            "SELECT id, state FROM resources WHERE kind='ha' AND external_id=$1",
            sid,
        )
        if row is None:
            raise ApiError(404, "HA resource does not exist")
        current = state(row["state"])
        updated = {
            **current,
            **{
                key: value
                for key, value in payload.items()
                if key not in {"sid", "delete", "digest"}
            },
        }
        await database(request).pool.execute(
            "UPDATE resources SET state=$2::jsonb, updated_at=now() WHERE id=$1",
            row["id"],
            json.dumps(updated, sort_keys=True),
        )

    async def ha_resource_delete(request: Request, inputs: dict[str, Any]) -> None:
        sid = str(values(inputs)["sid"])
        status = await database(request).pool.execute(
            "DELETE FROM resources WHERE kind='ha' AND external_id=$1",
            sid,
        )
        if status != "DELETE 1":
            raise ApiError(404, "HA resource does not exist")

    async def ha_groups(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        configured = _ha_groups(metadata)
        return [
            {
                "group": group_id,
                "nodes": str(payload.get("nodes", "")),
                "nofailback": int(payload.get("nofailback", 0)),
                "restricted": int(payload.get("restricted", 0)),
                "type": "group",
                "comment": payload.get("comment", ""),
            }
            for group_id, payload in sorted(configured.items())
        ]

    async def ha_group_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        group = str(values(inputs)["group"])
        for item in await ha_groups(request, inputs):
            if item["group"] == group:
                return item
        raise ApiError(404, "HA group does not exist")

    async def ha_group_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        group = str(payload["group"])
        metadata = await cluster_metadata(request)
        groups = _ha_groups(metadata)
        if group in groups:
            raise ApiError(409, "HA group already exists")
        groups[group] = {
            "nodes": str(payload.get("nodes") or ""),
            "nofailback": int(payload.get("nofailback") or 0),
            "restricted": int(payload.get("restricted") or 0),
            "comment": str(payload.get("comment") or ""),
        }
        metadata["ha_groups"] = groups
        await save_cluster_metadata(request, metadata)

    async def ha_group_update(request: Request, inputs: dict[str, Any]) -> None:
        group = str(values(inputs)["group"])
        metadata = await cluster_metadata(request)
        groups = _ha_groups(metadata)
        if group not in groups:
            raise ApiError(404, "HA group does not exist")
        payload = values(inputs)
        groups[group] = {
            **groups[group],
            **{
                key: value
                for key, value in payload.items()
                if key not in {"group", "delete", "digest"}
            },
        }
        metadata["ha_groups"] = groups
        await save_cluster_metadata(request, metadata)

    async def ha_group_delete(request: Request, inputs: dict[str, Any]) -> None:
        group = str(values(inputs)["group"])
        metadata = await cluster_metadata(request)
        groups = _ha_groups(metadata)
        if group not in groups:
            raise ApiError(404, "HA group does not exist")
        del groups[group]
        metadata["ha_groups"] = groups
        await save_cluster_metadata(request, metadata)

    async def ha_status(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("current", "manager_status")

    async def ha_status_current(request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        row = await database(request).pool.fetchrow(
            """SELECT count(*) FILTER (WHERE state->>'state' = 'started') AS started,
                count(*) AS total
            FROM resources WHERE kind='ha'"""
        )
        master = await database(request).pool.fetchval(
            "SELECT name FROM nodes WHERE status='online' ORDER BY name LIMIT 1"
        )
        metadata = await cluster_metadata(request)
        ha_raw = metadata.get("ha")
        ha: dict[str, Any] = dict(ha_raw) if isinstance(ha_raw, dict) else {}
        status_raw = ha.get("status_current")
        status: dict[str, Any] = dict(status_raw) if isinstance(status_raw, dict) else {}
        armed = bool(ha.get("armed")) if "armed" in ha else False
        return {
            "quorate": status.get("quorate", metadata.get("quorate", 0)),
            "mode": status.get("mode", "active" if armed else "disabled"),
            "master_node": status.get("master_node", str(master or "")),
            "ha_started": int(row["started"] or 0),
            "ha_total": int(row["total"] or 0),
            "armed": 1 if armed else 0,
        }

    async def ha_manager_status(request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        ha_raw = metadata.get("ha")
        ha: dict[str, Any] = dict(ha_raw) if isinstance(ha_raw, dict) else {}
        manager_raw = ha.get("manager_status")
        manager: dict[str, Any] = dict(manager_raw) if isinstance(manager_raw, dict) else {}
        armed = bool(ha.get("armed")) if "armed" in ha else False
        return {
            "manager_status": manager.get("manager_status", "active" if armed else "disabled"),
            "quorum": manager.get("quorum", ""),
            "armed": 1 if armed else 0,
        }

    async def ha_rules(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        rules = metadata.get("ha_rules")
        if isinstance(rules, list):
            return [dict(item) for item in rules if isinstance(item, dict)]
        return []

    async def ha_relocate(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        sid = str(payload["sid"])
        target = str(payload.get("node") or payload.get("target") or "")
        if not target:
            raise ApiError(400, "parameter verification failed - target node missing")
        ha_row = await database(request).pool.fetchrow(
            "SELECT id, state FROM resources WHERE kind='ha' AND external_id=$1",
            sid,
        )
        if ha_row is None:
            raise ApiError(404, "HA resource does not exist")
        node = await database(request).pool.fetchrow(
            "SELECT id, name FROM nodes WHERE name=$1",
            target,
        )
        if node is None:
            raise ApiError(404, "node does not exist")
        guest_kind, _, guest_id = sid.partition(":")
        resource_kind = "qemu" if guest_kind == "vm" else "lxc"
        await database(request).pool.execute(
            "UPDATE resources SET node_id=$2, updated_at=now() WHERE kind='ha' AND external_id=$1",
            sid,
            node["id"],
        )
        await database(request).pool.execute(
            """UPDATE resources SET node_id=$3, updated_at=now()
            WHERE kind=$1 AND external_id=$2""",
            resource_kind,
            guest_id,
            node["id"],
        )
        current = state(ha_row["state"])
        current["node"] = target
        current["state"] = current.get("state") or "started"
        await database(request).pool.execute(
            "UPDATE resources SET state=$2::jsonb, updated_at=now() WHERE id=$1",
            ha_row["id"],
            json.dumps(current, sort_keys=True),
        )

    async def ha_migrate(request: Request, inputs: dict[str, Any]) -> None:
        await ha_relocate(request, inputs)

    async def ha_arm(request: Request, _inputs: dict[str, Any]) -> None:
        metadata = await cluster_metadata(request)
        ha = dict(metadata.get("ha") or {})
        ha["armed"] = True
        metadata["ha"] = ha
        await save_cluster_metadata(request, metadata)

    async def ha_disarm(request: Request, _inputs: dict[str, Any]) -> None:
        metadata = await cluster_metadata(request)
        ha = dict(metadata.get("ha") or {})
        ha["armed"] = False
        metadata["ha"] = ha
        await save_cluster_metadata(request, metadata)

    registry.register("/cluster/ha", "GET", ha_index)
    registry.register("/cluster/ha/groups", "GET", ha_groups)
    registry.register("/cluster/ha/groups", "POST", ha_group_create)
    registry.register("/cluster/ha/groups/{group}", "GET", ha_group_get)
    registry.register("/cluster/ha/groups/{group}", "PUT", ha_group_update)
    registry.register("/cluster/ha/groups/{group}", "DELETE", ha_group_delete)
    registry.register("/cluster/ha/resources", "GET", ha_resources)
    registry.register("/cluster/ha/resources", "POST", ha_resource_create)
    registry.register("/cluster/ha/resources/{sid}", "GET", ha_resource_get)
    registry.register("/cluster/ha/resources/{sid}", "PUT", ha_resource_update)
    registry.register("/cluster/ha/resources/{sid}", "DELETE", ha_resource_delete)
    registry.register("/cluster/ha/status", "GET", ha_status)
    registry.register("/cluster/ha/status/current", "GET", ha_status_current)
    registry.register("/cluster/ha/status/manager_status", "GET", ha_manager_status)
    registry.register("/cluster/ha/rules", "GET", ha_rules)
    registry.register("/cluster/ha/resources/{sid}/migrate", "POST", ha_migrate)
    registry.register("/cluster/ha/resources/{sid}/relocate", "POST", ha_relocate)
    registry.register("/cluster/ha/status/arm-ha", "POST", ha_arm)
    registry.register("/cluster/ha/status/disarm-ha", "POST", ha_disarm)
