"""Basic persistent QEMU and task semantic handlers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.db.primitives import ConflictError
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
            """SELECT r.state, v.config FROM resources r
            JOIN nodes n ON n.id=r.node_id
            JOIN virtual_machines v ON v.resource_id=r.id
            WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "virtual machine does not exist")
        return {"vmid": int(vmid), **_state(row["config"]), **_state(row["state"])}

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
        upid = str(
            Upid(
                node,
                pid,
                pid,
                timestamp,
                f"qm{operation}",
                vmid,
                str(request.state.principal),
            )
        )
        task = await TaskRepository(database.pool).create(
            upid=upid,
            task_type=f"qemu-{operation}",
            payload={"node": node, "vmid": vmid, "resource_id": str(row["id"])},
            resource_key=f"qemu:{vmid}",
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return task.upid

    async def create(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid = str(values["node"]), int(values["vmid"])
        database = _database(request)
        if not await database.pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM nodes WHERE name=$1)", node
        ):
            raise ApiError(404, "node does not exist")
        if await database.pool.fetchval(
            """SELECT EXISTS(SELECT 1 FROM resources
            WHERE external_id=$1 AND kind IN ('qemu','lxc'))""",
            str(vmid),
        ):
            raise ApiError(409, "VMID already exists")
        config = {
            key: value
            for key, value in values.items()
            if key not in {"node", "vmid", "force", "archive", "start"}
        }
        return await _create_task(
            request,
            node=node,
            vmid=str(vmid),
            task_type="qemu-create",
            payload={"node": node, "vmid": vmid, "config": config},
        )

    async def update(request: Request, inputs: dict[str, Any], *, asynchronous: bool) -> str | None:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        database = _database(request)
        row = await database.pool.fetchrow(
            """SELECT r.id, r.version, r.state, v.config FROM resources r
            JOIN nodes n ON n.id=r.node_id
            JOIN virtual_machines v ON v.resource_id=r.id
            WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "virtual machine does not exist")
        control = {"node", "vmid", "digest", "delete", "revert", "skiplock", "background_delay"}
        provided = frozenset(str(item) for item in inputs.get("provided", values))
        changes = {
            key: value for key, value in values.items() if key in provided and key not in control
        }
        delete = str(values.get("delete", "")) if "delete" in provided else ""
        if asynchronous:
            return await _create_task(
                request,
                node=node,
                vmid=vmid,
                task_type="qemu-update",
                payload={
                    "node": node,
                    "vmid": vmid,
                    "resource_id": str(row["id"]),
                    "changes": changes,
                    "delete": delete,
                },
            )
        state = _state(row["state"])
        config = _state(row["config"])
        state.update(changes)
        config.update(changes)
        for key in delete.split(","):
            if key:
                state.pop(key, None)
                config.pop(key, None)
        status = await database.pool.execute(
            """UPDATE resources SET state=$3::jsonb, version=version+1,
            updated_at=now() WHERE id=$1 AND version=$2""",
            row["id"],
            row["version"],
            json.dumps(state, sort_keys=True),
        )
        if status != "UPDATE 1":
            raise ApiError(409, "configuration changed concurrently")
        await database.pool.execute(
            """UPDATE virtual_machines SET config=$2::jsonb
            WHERE resource_id=$1""",
            row["id"],
            json.dumps(config, sort_keys=True),
        )
        return None

    async def update_async(request: Request, inputs: dict[str, Any]) -> str:
        result = await update(request, inputs, asynchronous=True)
        if not isinstance(result, str):
            raise RuntimeError("async QEMU update did not create a task")
        return result

    async def update_sync(request: Request, inputs: dict[str, Any]) -> None:
        await update(request, inputs, asynchronous=False)

    async def delete(request: Request, inputs: dict[str, Any]) -> str:
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
        if str(_state(row["state"]).get("status")) != "stopped":
            raise ApiError(409, "cannot delete a running virtual machine")
        return await _create_task(
            request,
            node=node,
            vmid=vmid,
            task_type="qemu-delete",
            payload={"node": node, "vmid": vmid, "resource_id": str(row["id"])},
        )

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
    registry.register("/nodes/{node}/qemu", "POST", create)
    registry.register("/nodes/{node}/qemu/{vmid}", "DELETE", delete)
    registry.register("/nodes/{node}/qemu/{vmid}/config", "GET", qemu_config)
    registry.register("/nodes/{node}/qemu/{vmid}/config", "POST", update_async)
    registry.register("/nodes/{node}/qemu/{vmid}/config", "PUT", update_sync)
    registry.register("/nodes/{node}/qemu/{vmid}/status/current", "GET", qemu_status)
    registry.register("/nodes/{node}/qemu/{vmid}/status/start", "POST", start)
    registry.register("/nodes/{node}/qemu/{vmid}/status/stop", "POST", stop)
    registry.register("/nodes/{node}/tasks", "GET", task_list)
    registry.register("/nodes/{node}/tasks/{upid}/status", "GET", task_status)
    registry.register("/nodes/{node}/tasks/{upid}/log", "GET", task_log)


async def _create_task(
    request: Request,
    *,
    node: str,
    vmid: str,
    task_type: str,
    payload: dict[str, Any],
) -> str:
    database = _database(request)
    timestamp = int(await database.pool.fetchval("SELECT extract(epoch from now())::bigint"))
    pid = int(await database.pool.fetchval("SELECT pg_backend_pid()"))
    worker_type = {
        "qemu-create": "qmcreate",
        "qemu-delete": "qmdestroy",
        "qemu-update": "qmconfig",
    }[task_type]
    upid = str(Upid(node, pid, pid, timestamp, worker_type, vmid, str(request.state.principal)))
    try:
        task = await TaskRepository(database.pool).create(
            upid=upid,
            task_type=task_type,
            payload=payload,
            resource_key=f"qemu:{vmid}",
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid
