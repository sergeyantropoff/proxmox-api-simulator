"""Cluster-level semantic handlers."""

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
from app.simulation.seed import CLUSTER_ID


def _replication_jobs(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = metadata.get("replication", [])
    if not isinstance(jobs, list):
        return []
    result: list[dict[str, Any]] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        guest_raw = item.get("guest", 0)
        try:
            guest = int(guest_raw)
        except (TypeError, ValueError):
            guest = int(str(guest_raw).split(":")[-1] or 0)
        jobnum_raw = item.get("jobnum")
        if jobnum_raw is None:
            id_text = str(item.get("id") or "0")
            tail = id_text.rsplit("-", 1)[-1]
            jobnum = int(tail) if tail.isdigit() else 0
        else:
            jobnum = int(jobnum_raw)
        disable = item.get("disable")
        if disable is None:
            disable = 0 if int(item.get("enabled", 1) or 1) else 1
        entry = {
            "id": str(item.get("id") or f"{guest}-{jobnum}"),
            "guest": guest,
            "jobnum": jobnum,
            "target": str(item.get("target") or ""),
            "type": str(item.get("type") or "local"),
            "disable": bool(int(disable)),
        }
        if item.get("schedule") is not None:
            entry["schedule"] = str(item["schedule"])
        if item.get("rate") is not None:
            entry["rate"] = int(item["rate"])
        if item.get("comment") is not None:
            entry["comment"] = str(item["comment"])
        if item.get("source") is not None:
            entry["source"] = str(item["source"])
        result.append(entry)
    return result


def register_cluster_handlers(registry: HandlerRegistry) -> None:
    async def cluster_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs(
            "acme",
            "backup",
            "backup-info",
            "config",
            "ha",
            "log",
            "mapping",
            "nextid",
            "notifications",
            "options",
            "replication",
            "sdn",
            "status",
            "tasks",
        )

    async def cluster_status(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        from app.handlers.nodes import load_node_ops

        rows = await database(request).pool.fetch(
            """SELECT id, name, status FROM nodes ORDER BY name"""
        )
        metadata = await cluster_metadata(request)
        quorate = bool(int(metadata.get("quorate", 1) or 1))
        cluster_name = metadata.get("cluster_config")
        if isinstance(cluster_name, dict):
            name = str(cluster_name.get("clustername") or "pve-simulator")
            version = int(cluster_name.get("version") or 2)
        else:
            name = "pve-simulator"
            version = 2
        result: list[dict[str, Any]] = [
            {
                "type": "cluster",
                "id": "cluster",
                "name": name,
                "nodes": len(rows),
                "quorate": quorate,
                "version": version,
            }
        ]
        for index, row in enumerate(rows):
            online = str(row["status"]) == "online"
            ops = await load_node_ops(request, str(row["name"]))
            cluster_node = ops.get("cluster_status")
            entry = dict(cluster_node) if isinstance(cluster_node, dict) else {}
            local_raw = entry.get("local", index == 0)
            node_name = str(row["name"])
            result.append(
                {
                    "type": "node",
                    "id": f"node/{node_name}",
                    "name": node_name,
                    "nodeid": int(entry.get("nodeid", index + 1)),
                    "online": online,
                    "local": bool(int(local_raw)) if not isinstance(local_raw, bool) else local_raw,
                    "ip": str(entry.get("ip") or ops.get("ip") or ""),
                    "level": str(entry.get("level", "")),
                }
            )
        return result

    async def cluster_nextid(request: Request, inputs: dict[str, Any]) -> int:
        requested = values(inputs).get("vmid")
        if requested is not None:
            candidate = int(requested)
            taken = await database(request).pool.fetchval(
                """SELECT EXISTS(
                    SELECT 1 FROM resources WHERE kind IN ('qemu', 'lxc') AND external_id=$1
                )""",
                str(candidate),
            )
            if not taken:
                return candidate
            raise ApiError(400, f"VMID {candidate} already exists")
        maximum = await database(request).pool.fetchval(
            """SELECT COALESCE(MAX(external_id::integer), 99)
            FROM resources WHERE kind IN ('qemu', 'lxc')"""
        )
        return int(maximum) + 1

    async def cluster_options_get(_request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        row = await database(_request).pool.fetchrow(
            "SELECT metadata FROM clusters WHERE id=$1",
            CLUSTER_ID,
        )
        metadata = state(row["metadata"]) if row is not None else {}
        options = metadata.get("options", {})
        if not isinstance(options, dict):
            return {}
        return dict(options)

    async def cluster_options_put(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        current = await cluster_options_get(request, inputs)
        provided = values(inputs)
        updated = {**current, **{key: value for key, value in provided.items() if key != "node"}}
        await database(request).pool.execute(
            """UPDATE clusters SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb), '{options}', $2::jsonb, true
            ), updated_at=now() WHERE id=$1""",
            CLUSTER_ID,
            json.dumps(updated, sort_keys=True),
        )
        return updated

    async def cluster_log(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        limit = int(values(inputs).get("max") or 50)
        rows = await database(request).pool.fetch(
            """SELECT tl.message, tl.sequence
            FROM task_logs tl
            ORDER BY tl.created_at DESC, tl.sequence DESC
            LIMIT $1""",
            limit,
        )
        return [{"n": int(row["sequence"]), "t": str(row["message"])} for row in reversed(rows)]

    async def cluster_tasks(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            "SELECT upid FROM tasks ORDER BY created_at DESC LIMIT 1000"
        )
        return [{"upid": str(row["upid"])} for row in rows]

    async def replication_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        return _replication_jobs(metadata)

    async def replication_create(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        from app.handlers.common import require_value

        payload = values(inputs)
        guest = str(require_value(payload, "guest"))
        target = str(require_value(payload, "target"))
        job_id = str(payload.get("id") or f"repl-{guest.replace(':', '-')}")
        metadata = await cluster_metadata(request)
        jobs = _replication_jobs(metadata)
        if any(str(item.get("id")) == job_id for item in jobs):
            raise ApiError(409, "replication job already exists")
        job = {
            "id": job_id,
            "guest": guest,
            "target": target,
            "type": str(payload.get("type") or "local"),
            "schedule": str(payload.get("schedule") or "*/15"),
            "rate": int(payload.get("rate") or 1),
            "comment": str(payload.get("comment") or ""),
            "enabled": int(payload.get("enabled", 1)),
        }
        jobs.append(job)
        metadata["replication"] = jobs
        await save_cluster_metadata(request, metadata)
        return job

    async def replication_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        job_id = str(values(inputs)["id"])
        for job in _replication_jobs(await cluster_metadata(request)):
            if str(job.get("id")) == job_id:
                return job
        raise ApiError(404, "replication job does not exist")

    async def replication_update(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        job_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        jobs = _replication_jobs(metadata)
        for index, job in enumerate(jobs):
            if str(job.get("id")) != job_id:
                continue
            payload = values(inputs)
            updated = {
                **job,
                **{
                    key: value
                    for key, value in payload.items()
                    if key not in {"id", "delete", "digest"}
                },
            }
            jobs[index] = updated
            metadata["replication"] = jobs
            await save_cluster_metadata(request, metadata)
            return updated
        raise ApiError(404, "replication job does not exist")

    async def replication_delete(request: Request, inputs: dict[str, Any]) -> None:
        job_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        jobs = _replication_jobs(metadata)
        remaining = [job for job in jobs if str(job.get("id")) != job_id]
        if len(remaining) == len(jobs):
            raise ApiError(404, "replication job does not exist")
        metadata["replication"] = remaining
        await save_cluster_metadata(request, metadata)

    registry.register("/cluster", "GET", cluster_index)
    registry.register("/cluster/status", "GET", cluster_status)
    registry.register("/cluster/nextid", "GET", cluster_nextid)
    registry.register("/cluster/options", "GET", cluster_options_get)
    registry.register("/cluster/options", "PUT", cluster_options_put)
    registry.register("/cluster/log", "GET", cluster_log)
    registry.register("/cluster/tasks", "GET", cluster_tasks)
    registry.register("/cluster/replication", "GET", replication_list)
    registry.register("/cluster/replication", "POST", replication_create)
    registry.register("/cluster/replication/{id}", "GET", replication_get)
    registry.register("/cluster/replication/{id}", "PUT", replication_update)
    registry.register("/cluster/replication/{id}", "DELETE", replication_delete)
