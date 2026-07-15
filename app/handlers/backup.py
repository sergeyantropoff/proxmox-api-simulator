"""Cluster backup and vzdump handlers."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.primitives import ConflictError
from app.handlers.common import database, require_node, state, values
from app.tasks.repository import TaskRepository
from app.tasks.upid import Upid


def register_backup_handlers(registry: HandlerRegistry) -> None:
    async def backup_list(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            """SELECT b.id, b.volume_id, b.size_bytes, b.metadata, b.created_at,
                r.external_id AS vmid, n.name AS node, s.storage_id
            FROM backups b
            LEFT JOIN resources r ON r.id = b.resource_id
            LEFT JOIN nodes n ON n.id = r.node_id
            JOIN storages s ON s.resource_id = b.storage_resource_id
            ORDER BY b.created_at DESC LIMIT 2000"""
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            metadata = state(row["metadata"])
            result.append(
                {
                    "id": str(row["id"]),
                    "volid": str(row["volume_id"]),
                    "size": int(row["size_bytes"]),
                    "vmid": int(row["vmid"]) if row["vmid"] is not None else None,
                    "node": str(row["node"]) if row["node"] is not None else None,
                    "storage": str(row["storage_id"]),
                    "starttime": int(row["created_at"].timestamp()),
                    "mode": metadata.get("mode", "snapshot"),
                    "type": metadata.get("type", "vzdump"),
                }
            )
        return result

    async def backup_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        backup_id = str(values(inputs)["id"])
        row = await database(request).pool.fetchrow(
            """SELECT b.id, b.volume_id, b.size_bytes, b.metadata, b.created_at,
                r.external_id AS vmid, n.name AS node, s.storage_id
            FROM backups b
            LEFT JOIN resources r ON r.id = b.resource_id
            LEFT JOIN nodes n ON n.id = r.node_id
            JOIN storages s ON s.resource_id = b.storage_resource_id
            WHERE b.id::text = $1 OR b.volume_id = $1""",
            backup_id,
        )
        if row is None:
            raise ApiError(404, "backup does not exist")
        metadata = state(row["metadata"])
        return {
            "id": str(row["id"]),
            "volid": str(row["volume_id"]),
            "size": int(row["size_bytes"]),
            "vmid": int(row["vmid"]) if row["vmid"] is not None else None,
            "node": str(row["node"]) if row["node"] is not None else None,
            "storage": str(row["storage_id"]),
            "starttime": int(row["created_at"].timestamp()),
            "notes": metadata.get("notes-template"),
            **metadata,
        }

    async def backup_update(request: Request, inputs: dict[str, Any]) -> None:
        backup_id = str(values(inputs)["id"])
        row = await database(request).pool.fetchrow(
            "SELECT id, metadata FROM backups WHERE id::text = $1",
            backup_id,
        )
        if row is None:
            raise ApiError(404, "backup does not exist")
        metadata = state(row["metadata"])
        payload = values(inputs)
        if "notes" in payload:
            metadata["notes-template"] = payload["notes"]
        await database(request).pool.execute(
            "UPDATE backups SET metadata=$2::jsonb WHERE id=$1",
            row["id"],
            json.dumps(metadata, sort_keys=True),
        )

    async def backup_delete(request: Request, inputs: dict[str, Any]) -> None:
        backup_id = str(values(inputs)["id"])
        status = await database(request).pool.execute(
            "DELETE FROM backups WHERE id::text = $1",
            backup_id,
        )
        if status != "DELETE 1":
            raise ApiError(404, "backup does not exist")

    async def backup_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload.get("node") or payload.get("target") or "pve01")
        await require_node(request, node)
        vmid = payload.get("vmid")
        return await _schedule_vzdump(
            request,
            node=node,
            vmids=[str(vmid)] if vmid is not None else None,
            payload=payload,
        )

    async def backup_info(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            """SELECT r.external_id AS vmid, n.name AS node, max(b.created_at) AS last_backup
            FROM resources r
            JOIN nodes n ON n.id = r.node_id
            LEFT JOIN backups b ON b.resource_id = r.id
            WHERE r.kind = 'qemu'
            GROUP BY r.external_id, n.name
            ORDER BY r.external_id::integer
            LIMIT 5000"""
        )
        return [
            {
                "vmid": int(row["vmid"]),
                "node": str(row["node"]),
                "lastbackup": int(row["last_backup"].timestamp()) if row["last_backup"] else 0,
                "protected": 0,
            }
            for row in rows
        ]

    async def backup_not_backed_up(_request: Request, _inputs: dict[str, Any]) -> list[int]:
        rows = await database(_request).pool.fetch(
            """SELECT r.external_id::integer AS vmid
            FROM resources r
            LEFT JOIN backups b ON b.resource_id = r.id
            WHERE r.kind = 'qemu' AND b.id IS NULL
            ORDER BY r.external_id::integer"""
        )
        return [int(row["vmid"]) for row in rows]

    async def backup_included_volumes(request: Request, inputs: dict[str, Any]) -> list[str]:
        backup_id = str(values(inputs)["id"])
        row = await database(request).pool.fetchrow(
            """SELECT b.volume_id, r.external_id AS vmid
            FROM backups b LEFT JOIN resources r ON r.id = b.resource_id
            WHERE b.id::text = $1""",
            backup_id,
        )
        if row is None:
            raise ApiError(404, "backup does not exist")
        vmid = row["vmid"]
        return [f"qemu/{vmid}"] if vmid is not None else [str(row["volume_id"])]

    async def vzdump_defaults(_request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        await require_node(_request, str(values(inputs)["node"]))
        return {
            "all": 0,
            "bwlimit": 0,
            "compress": "zstd",
            "dumpdir": "backup",
            "mode": "snapshot",
            "remove": 0,
            "storage": "nfs-backup",
            "mailto": "",
            "notes-template": "{{guestname}}",
        }

    async def vzdump_extractconfig(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        volid = str(payload.get("volume") or payload.get("volid") or "")
        if not volid:
            raise ApiError(400, "volume parameter required")
        return f"# simulated vzdump config extracted from {volid}\name: demo\nmemory: 2048\n"

    async def vzdump_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        vmids = payload.get("vmid")
        selected = None
        if vmids is not None:
            selected = [str(item) for item in str(vmids).split(",") if item.strip()]
        return await _schedule_vzdump(request, node=node, vmids=selected, payload=payload)

    registry.register("/cluster/backup", "GET", backup_list)
    registry.register("/cluster/backup", "POST", backup_create)
    registry.register("/cluster/backup-info", "GET", backup_info)
    registry.register("/cluster/backup-info/not-backed-up", "GET", backup_not_backed_up)
    registry.register("/cluster/backup/{id}", "GET", backup_get)
    registry.register("/cluster/backup/{id}", "PUT", backup_update)
    registry.register("/cluster/backup/{id}", "DELETE", backup_delete)
    registry.register("/cluster/backup/{id}/included_volumes", "GET", backup_included_volumes)
    registry.register("/nodes/{node}/vzdump", "POST", vzdump_create)
    registry.register("/nodes/{node}/vzdump/defaults", "GET", vzdump_defaults)
    registry.register("/nodes/{node}/vzdump/extractconfig", "GET", vzdump_extractconfig)


async def _schedule_vzdump(
    request: Request,
    *,
    node: str,
    vmids: list[str] | None,
    payload: dict[str, Any],
) -> str:
    pool = database(request).pool
    if vmids is None:
        rows = await pool.fetch(
            """SELECT external_id FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='qemu' ORDER BY external_id::integer LIMIT 100""",
            node,
        )
        vmids = [str(row["external_id"]) for row in rows]
    if not vmids:
        raise ApiError(400, "no virtual machines selected for backup")
    vmid = vmids[0]
    upid = str(Upid.allocate(node, "vzdump", vmid, str(request.state.principal)))
    try:
        task = await TaskRepository(pool).create(
            upid=upid,
            task_type="vzdump",
            payload={
                "node": node,
                "vmids": vmids,
                "storage": str(payload.get("storage") or "nfs-backup"),
                "mode": str(payload.get("mode") or "snapshot"),
                "compress": str(payload.get("compress") or "zstd"),
            },
            resource_key=f"backup:{node}",
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid
