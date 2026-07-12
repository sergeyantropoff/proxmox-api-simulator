"""Basic persistent QEMU and task semantic handlers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.tasks.repository import TaskRepository
from app.tasks.upid import Upid


def _database(request: Request) -> AsyncpgDatabase:
    return cast(AsyncpgDatabase, request.app.state.database)


def _values(inputs: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], inputs["values"])


def _state(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        return cast(dict[str, Any], json.loads(value))
    return dict(cast(Mapping[str, Any], value))


def register_qemu_handlers(registry: HandlerRegistry) -> None:
    async def qemu_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(_values(inputs)["node"])
        rows = await _database(request).pool.fetch(
            """SELECT r.external_id::integer AS vmid, r.state
            FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='qemu' ORDER BY r.external_id::integer""",
            node,
        )
        return [{"vmid": int(row["vmid"]), **_state(row["state"])} for row in rows]

    async def qemu_config(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node, vmid = str(_values(inputs)["node"]), str(_values(inputs)["vmid"])
        row = await _database(request).pool.fetchrow(
            """SELECT r.state FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "virtual machine does not exist")
        return {"vmid": int(vmid), **_state(row["state"])}

    async def qemu_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await qemu_config(request, inputs)

    async def mutate(operation: str, request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        database = _database(request)
        row = await database.pool.fetchrow(
            """SELECT r.id, r.state FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "virtual machine does not exist")
        current = str(_state(row["state"]).get("status", "stopped"))
        if (operation == "start" and current != "stopped") or (
            operation == "stop" and current != "running"
        ):
            raise ApiError(409, f"cannot {operation} VM while it is {current}")
        timestamp = int(await database.pool.fetchval("SELECT extract(epoch from now())::bigint"))
        pid = int(await database.pool.fetchval("SELECT pg_backend_pid()"))
        upid = str(Upid(node, pid, pid, timestamp, f"qm{operation}", vmid, "root@pam"))
        task = await TaskRepository(database.pool).create(
            upid=upid,
            task_type=f"qemu-{operation}",
            payload={"node": node, "vmid": vmid, "resource_id": str(row["id"])},
            resource_key=f"qemu:{vmid}",
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return task.upid

    async def start(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("start", request, inputs)

    async def stop(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("stop", request, inputs)

    async def task_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        tasks = await TaskRepository(_database(request).pool).list_for_node(
            str(_values(inputs)["node"])
        )
        return [
            {"upid": task.upid, "status": task.status, "type": task.task_type} for task in tasks
        ]

    async def task_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        task = await TaskRepository(_database(request).pool).get_by_upid(
            str(_values(inputs)["upid"])
        )
        if task is None:
            raise ApiError(404, "task does not exist")
        result: dict[str, Any] = {
            "upid": task.upid,
            "status": "stopped" if task.status in {"success", "error", "cancelled"} else "running",
            "progress": task.progress,
        }
        if task.status in {"success", "error", "cancelled"}:
            result["exitstatus"] = "OK" if task.status == "success" else task.status.upper()
        return result

    async def task_log(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        repository = TaskRepository(_database(request).pool)
        task = await repository.get_by_upid(str(_values(inputs)["upid"]))
        if task is None:
            raise ApiError(404, "task does not exist")
        return [
            {"n": index + 1, "t": message}
            for index, message in enumerate(await repository.logs(task.id))
        ]

    registry.register("/nodes/{node}/qemu", "GET", qemu_list)
    registry.register("/nodes/{node}/qemu/{vmid}/config", "GET", qemu_config)
    registry.register("/nodes/{node}/qemu/{vmid}/status/current", "GET", qemu_status)
    registry.register("/nodes/{node}/qemu/{vmid}/status/start", "POST", start)
    registry.register("/nodes/{node}/qemu/{vmid}/status/stop", "POST", stop)
    registry.register("/nodes/{node}/tasks", "GET", task_list)
    registry.register("/nodes/{node}/tasks/{upid}/status", "GET", task_status)
    registry.register("/nodes/{node}/tasks/{upid}/log", "GET", task_log)
