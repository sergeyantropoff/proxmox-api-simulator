"""Worker semantics for asynchronous QEMU transitions."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any, cast

from app.simulation.clock import Clock
from app.simulation.transitions import VmState, plan_transition
from app.tasks.repository import Task, TaskRepository
from app.tasks.worker import TaskHandler


def qemu_handler(repository: TaskRepository, clock: Clock) -> TaskHandler:
    async def execute(task: Task) -> dict[str, Any]:
        operation = task.task_type.removeprefix("qemu-")
        if operation == "create":
            return await _create(repository, task)
        resource_id = uuid.UUID(str(task.payload["resource_id"]))
        if operation == "update":
            return await _update(repository, task, resource_id)
        if operation == "delete":
            return await _delete(repository, task, resource_id)
        async with repository.pool.acquire() as connection:
            row = await connection.fetchrow("SELECT state FROM resources WHERE id=$1", resource_id)
            if row is None:
                raise ValueError("resource disappeared")
            raw = row["state"]
            state = json.loads(raw) if isinstance(raw, str) else dict(raw)
            transition = plan_transition(VmState(str(state["status"])), operation)
            state["status"] = transition.intermediate
            await connection.execute(
                "UPDATE resources SET state=$2::jsonb WHERE id=$1",
                resource_id,
                json.dumps(state),
            )
        await repository.append_log(task.id, f"VM {operation} started")
        await clock.sleep(1.0)
        async with repository.pool.acquire() as connection:
            state["status"] = transition.after
            await connection.execute(
                "UPDATE resources SET state=$2::jsonb WHERE id=$1",
                resource_id,
                json.dumps(state),
            )
        await repository.append_log(task.id, f"VM {operation} completed")
        return {"status": str(transition.after)}

    return execute


async def _create(repository: TaskRepository, task: Task) -> dict[str, Any]:
    node, vmid = str(task.payload["node"]), int(task.payload["vmid"])
    config = dict(task.payload.get("config", {}))
    resource_id = uuid.uuid4()
    state = {"status": "stopped", **config}
    async with repository.pool.acquire() as connection:
        async with connection.transaction():
            node_row = await connection.fetchrow(
                "SELECT id, cluster_id FROM nodes WHERE name=$1", node
            )
            if node_row is None:
                raise ValueError("node disappeared")
            await connection.execute(
                """INSERT INTO resources(
                    id, node_id, cluster_id, kind, external_id, state, metadata
                ) VALUES($1, $2, $3, 'qemu', $4, $5::jsonb, '{}'::jsonb)""",
                resource_id,
                node_row["id"],
                node_row["cluster_id"],
                str(vmid),
                json.dumps(state, sort_keys=True),
            )
            await connection.execute(
                """INSERT INTO virtual_machines(resource_id, cluster_id, vmid, config)
                VALUES($1, $2, $3, $4::jsonb)""",
                resource_id,
                node_row["cluster_id"],
                vmid,
                json.dumps(config, sort_keys=True),
            )
    await repository.append_log(task.id, f"VM {vmid} created")
    return {"vmid": vmid, "status": "stopped"}


async def _update(repository: TaskRepository, task: Task, resource_id: uuid.UUID) -> dict[str, Any]:
    changes = dict(task.payload.get("changes", {}))
    delete_keys = tuple(str(task.payload.get("delete", "")).split(","))
    async with repository.pool.acquire() as connection:
        async with connection.transaction():
            row = await connection.fetchrow(
                """SELECT r.state, v.config FROM resources r
                JOIN virtual_machines v ON v.resource_id=r.id WHERE r.id=$1""",
                resource_id,
            )
            if row is None:
                raise ValueError("resource disappeared")
            state = _object(row["state"])
            config = _object(row["config"])
            config.update(changes)
            for key in delete_keys:
                if key:
                    config.pop(key, None)
                    state.pop(key, None)
            state.update(changes)
            await connection.execute(
                """UPDATE resources SET state=$2::jsonb, version=version+1,
                updated_at=now() WHERE id=$1""",
                resource_id,
                json.dumps(state, sort_keys=True),
            )
            await connection.execute(
                "UPDATE virtual_machines SET config=$2::jsonb WHERE resource_id=$1",
                resource_id,
                json.dumps(config, sort_keys=True),
            )
    await repository.append_log(task.id, "VM configuration updated")
    return {"updated": sorted(changes), "deleted": sorted(key for key in delete_keys if key)}


async def _delete(repository: TaskRepository, task: Task, resource_id: uuid.UUID) -> dict[str, Any]:
    async with repository.pool.acquire() as connection:
        status = await connection.execute("DELETE FROM resources WHERE id=$1", resource_id)
        if status != "DELETE 1":
            raise ValueError("resource disappeared")
    await repository.append_log(task.id, "VM deleted")
    return {"deleted": True}


def _object(value: object) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(cast(Mapping[str, Any], value))
