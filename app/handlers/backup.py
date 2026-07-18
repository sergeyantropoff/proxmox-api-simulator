"""Cluster backup jobs and node vzdump handlers."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.primitives import ConflictError
from app.handlers.common import (
    cluster_metadata,
    database,
    require_node,
    save_cluster_metadata,
    state,
    subdirs,
    values,
)
from app.tasks.repository import TaskRepository
from app.tasks.upid import Upid


def _backup_jobs(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = metadata.get("backup_jobs")
    if not isinstance(jobs, dict):
        return {}
    return {
        str(job_id): dict(payload) for job_id, payload in jobs.items() if isinstance(payload, dict)
    }


def _job_view(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    view = dict(payload)
    view["id"] = job_id
    enabled = view.get("enabled", 1)
    view["enabled"] = bool(int(enabled)) if not isinstance(enabled, bool) else enabled
    return view


def register_backup_handlers(registry: HandlerRegistry) -> None:
    async def backup_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        jobs = _backup_jobs(metadata)
        return [_job_view(job_id, payload) for job_id, payload in sorted(jobs.items())]

    async def backup_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        job_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        jobs = _backup_jobs(metadata)
        payload = jobs.get(job_id)
        if payload is None:
            raise ApiError(404, "backup job does not exist")
        return _job_view(job_id, payload)

    async def backup_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        metadata = await cluster_metadata(request)
        jobs = _backup_jobs(metadata)
        job_id = str(payload.get("id") or f"backup-{secrets.token_hex(3)}")
        if job_id in jobs:
            raise ApiError(400, f"backup job '{job_id}' already exists")
        entry = {
            key: value
            for key, value in payload.items()
            if key not in {"delete", "digest", "node", "target"}
        }
        entry["id"] = job_id
        entry.setdefault("enabled", 1)
        entry.setdefault("storage", payload.get("storage") or "local")
        jobs[job_id] = entry
        metadata["backup_jobs"] = jobs
        await save_cluster_metadata(request, metadata)

    async def backup_update(request: Request, inputs: dict[str, Any]) -> None:
        job_id = str(values(inputs)["id"])
        payload = values(inputs)
        metadata = await cluster_metadata(request)
        jobs = _backup_jobs(metadata)
        current = jobs.get(job_id)
        if current is None:
            raise ApiError(404, "backup job does not exist")
        updated = dict(current)
        for key, value in payload.items():
            if key in {"id", "delete", "digest"}:
                continue
            updated[key] = value
        updated["id"] = job_id
        jobs[job_id] = updated
        metadata["backup_jobs"] = jobs
        await save_cluster_metadata(request, metadata)

    async def backup_delete(request: Request, inputs: dict[str, Any]) -> None:
        job_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        jobs = _backup_jobs(metadata)
        if job_id not in jobs:
            raise ApiError(404, "backup job does not exist")
        del jobs[job_id]
        metadata["backup_jobs"] = jobs
        await save_cluster_metadata(request, metadata)

    async def backup_info(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("not-backed-up")

    async def backupinfo_stub(_request: Request, _inputs: dict[str, Any]) -> str:
        # PVE 6.x `/cluster/backupinfo` returns a stub string; 7+ uses `/backup-info` index.
        return "Please use the 'not-backed-up' API"

    async def backup_not_backed_up(
        request: Request, _inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        jobs = _backup_jobs(metadata)
        covered: set[str] = set()
        for payload in jobs.values():
            if int(payload.get("all") or 0):
                covered.add("*")
            for item in str(payload.get("vmid") or "").split(","):
                item = item.strip()
                if item:
                    covered.add(item)
        rows = await database(request).pool.fetch(
            """SELECT r.external_id, r.kind, r.state FROM resources r
            WHERE r.kind IN ('qemu', 'lxc')
            ORDER BY r.external_id::integer"""
        )
        result: list[dict[str, Any]] = []
        if "*" in covered:
            return result
        for row in rows:
            vmid = str(row["external_id"])
            if vmid in covered:
                continue
            guest_state = state(row["state"])
            result.append(
                {
                    "vmid": int(vmid),
                    "type": "qemu" if row["kind"] == "qemu" else "lxc",
                    "name": str(guest_state.get("name") or f"{row['kind']}-{vmid}"),
                }
            )
        return result

    async def backup_included_volumes(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        job_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        jobs = _backup_jobs(metadata)
        job = jobs.get(job_id)
        if job is None:
            raise ApiError(404, "backup job does not exist")
        vmids = [item.strip() for item in str(job.get("vmid") or "").split(",") if item.strip()]
        guest_select = """SELECT r.external_id, r.kind, r.state,
                v.config AS qemu_config, c.config AS lxc_config
            FROM resources r
            LEFT JOIN virtual_machines v ON v.resource_id = r.id
            LEFT JOIN containers c ON c.resource_id = r.id"""
        if int(job.get("all") or 0):
            rows = await database(request).pool.fetch(
                f"""{guest_select}
                WHERE r.kind IN ('qemu', 'lxc')
                ORDER BY r.external_id::integer"""
            )
        else:
            rows = await database(request).pool.fetch(
                f"""{guest_select}
                WHERE r.kind IN ('qemu', 'lxc') AND r.external_id = ANY($1::text[])
                ORDER BY r.external_id::integer""",
                vmids,
            )
        children: list[dict[str, Any]] = []
        for row in rows:
            guest_state = state(row["state"])
            config_raw = row["qemu_config"] if row["kind"] == "qemu" else row["lxc_config"]
            config = state(config_raw) if config_raw is not None else {}
            volumes: list[dict[str, Any]] = []
            for key, value in sorted(config.items()):
                if not (
                    key.startswith("scsi")
                    or key.startswith("virtio")
                    or key.startswith("sata")
                    or key.startswith("ide")
                    or key in {"rootfs", "mp0", "mp1", "mp2", "mp3"}
                ):
                    continue
                volumes.append(
                    {
                        "id": key,
                        "name": str(value).split(",", 1)[0],
                        "included": True,
                        "reason": "included by default",
                    }
                )
            children.append(
                {
                    "id": int(row["external_id"]),
                    "name": str(guest_state.get("name") or f"{row['kind']}-{row['external_id']}"),
                    "type": "qemu" if row["kind"] == "qemu" else "lxc",
                    "children": volumes,
                }
            )
        return {"children": children}

    async def vzdump_defaults(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        from app.handlers.nodes import load_node_ops

        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        vzdump = ops.get("vzdump")
        defaults = vzdump.get("defaults") if isinstance(vzdump, dict) else None
        return dict(defaults) if isinstance(defaults, dict) else {}

    async def vzdump_extractconfig(request: Request, inputs: dict[str, Any]) -> str:
        from app.handlers.nodes import load_node_ops

        payload = values(inputs)
        node = str(payload["node"])
        volid = str(payload.get("volume") or payload.get("volid") or "")
        if not volid:
            raise ApiError(400, "volume parameter required")
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        vzdump = ops.get("vzdump")
        configs = vzdump.get("extractconfig") if isinstance(vzdump, dict) else None
        if not isinstance(configs, dict):
            return ""
        return str(configs.get(volid) or "")

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
    registry.register("/cluster/backupinfo", "GET", backupinfo_stub)
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
                "storage": str(payload.get("storage") or "local"),
                "mode": str(payload.get("mode") or "snapshot"),
                "compress": str(payload.get("compress") or "zstd"),
            },
            resource_key=f"backup:{node}:{secrets.token_hex(4)}",
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid
