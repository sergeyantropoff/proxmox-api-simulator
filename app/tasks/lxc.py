"""Worker semantics for asynchronous LXC transitions."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any, cast

from app.simulation.clock import Clock
from app.simulation.transitions import VmState, plan_transition
from app.tasks.repository import Task, TaskRepository
from app.tasks.worker import TaskHandler


def lxc_handler(repository: TaskRepository, clock: Clock) -> TaskHandler:
    async def execute(task: Task) -> dict[str, Any]:
        operation = task.task_type.removeprefix("lxc-")
        if operation == "create":
            return await _create(repository, task, clock)
        if operation == "clone":
            return await _clone(repository, task)
        resource_id = uuid.UUID(str(task.payload["resource_id"]))
        if operation == "delete":
            return await _delete(repository, task, resource_id)
        if operation.startswith("snapshot-"):
            return await _snapshot(
                repository, task, resource_id, operation.removeprefix("snapshot-")
            )
        if operation == "migrate" or operation == "remote-migrate":
            return await _migrate(repository, task, resource_id, clock)
        async with repository.pool.acquire() as connection:
            row = await connection.fetchrow("SELECT state FROM resources WHERE id=$1", resource_id)
            if row is None:
                raise ValueError("resource disappeared")
            state = _object(row["state"])
            transition = plan_transition(VmState(str(state["status"])), operation)
            state["status"] = transition.intermediate
            await connection.execute(
                "UPDATE resources SET state=$2::jsonb WHERE id=$1",
                resource_id,
                json.dumps(state),
            )
        await repository.append_log(task.id, f"container {operation} started")
        await clock.sleep(1.0)
        async with repository.pool.acquire() as connection:
            state["status"] = transition.after
            await connection.execute(
                "UPDATE resources SET state=$2::jsonb WHERE id=$1",
                resource_id,
                json.dumps(state),
            )
        await repository.append_log(task.id, f"container {operation} completed")
        return {"status": str(transition.after)}

    return execute


async def _create(repository: TaskRepository, task: Task, clock: Clock) -> dict[str, Any]:
    node, vmid = str(task.payload["node"]), int(task.payload["vmid"])
    config = dict(task.payload.get("config", {}))
    start = bool(task.payload.get("start", False))
    resource_id = uuid.uuid4()
    status = "running" if start else "stopped"
    state = {"status": status, **config}
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
                ) VALUES($1, $2, $3, 'lxc', $4, $5::jsonb, '{}'::jsonb)""",
                resource_id,
                node_row["id"],
                node_row["cluster_id"],
                str(vmid),
                json.dumps(state, sort_keys=True),
            )
            await connection.execute(
                """INSERT INTO containers(resource_id, cluster_id, vmid, config)
                VALUES($1, $2, $3, $4::jsonb)""",
                resource_id,
                node_row["cluster_id"],
                vmid,
                json.dumps(config, sort_keys=True),
            )
    if start:
        await clock.sleep(0.5)
    await repository.append_log(task.id, f"container {vmid} created")
    return {"vmid": vmid, "status": status}


async def _delete(repository: TaskRepository, task: Task, resource_id: uuid.UUID) -> dict[str, Any]:
    async with repository.pool.acquire() as connection:
        status = await connection.execute("DELETE FROM resources WHERE id=$1", resource_id)
        if status != "DELETE 1":
            raise ValueError("resource disappeared")
    await repository.append_log(task.id, "container deleted")
    return {"deleted": True}


async def _snapshot(
    repository: TaskRepository,
    task: Task,
    resource_id: uuid.UUID,
    operation: str,
) -> dict[str, Any]:
    name = str(task.payload["snapname"])
    async with repository.pool.acquire() as connection:
        async with connection.transaction():
            if operation == "create":
                row = await connection.fetchrow(
                    """SELECT r.state, c.config FROM resources r
                    JOIN containers c ON c.resource_id=r.id WHERE r.id=$1""",
                    resource_id,
                )
                if row is None:
                    raise ValueError("resource disappeared")
                captured = {
                    "resource_state": _object(row["state"]),
                    "config": _object(row["config"]),
                }
                await connection.execute(
                    """INSERT INTO snapshots(id, resource_id, name, description, state)
                    VALUES($1, $2, $3, $4, $5::jsonb)""",
                    uuid.uuid4(),
                    resource_id,
                    name,
                    str(task.payload.get("description", "")),
                    json.dumps(captured, sort_keys=True),
                )
            elif operation == "delete":
                status = await connection.execute(
                    "DELETE FROM snapshots WHERE resource_id=$1 AND name=$2",
                    resource_id,
                    name,
                )
                if status != "DELETE 1":
                    raise ValueError("snapshot disappeared")
            elif operation == "rollback":
                row = await connection.fetchrow(
                    "SELECT state FROM snapshots WHERE resource_id=$1 AND name=$2",
                    resource_id,
                    name,
                )
                if row is None:
                    raise ValueError("snapshot disappeared")
                captured = _object(row["state"])
                state = dict(cast(Mapping[str, Any], captured["resource_state"]))
                await connection.execute(
                    """UPDATE resources SET state=$2::jsonb, version=version+1,
                    updated_at=now() WHERE id=$1""",
                    resource_id,
                    json.dumps(state, sort_keys=True),
                )
                await connection.execute(
                    "UPDATE containers SET config=$2::jsonb WHERE resource_id=$1",
                    resource_id,
                    json.dumps(captured["config"], sort_keys=True),
                )
            else:
                raise ValueError(f"unsupported snapshot operation: {operation}")
    await repository.append_log(task.id, f"snapshot {name} {operation} completed")
    return {"snapshot": name, "operation": operation}


async def _clone(repository: TaskRepository, task: Task) -> dict[str, Any]:
    source_id = uuid.UUID(str(task.payload["source_resource_id"]))
    target_id = uuid.uuid4()
    node, vmid = str(task.payload["node"]), int(task.payload["vmid"])
    async with repository.pool.acquire() as connection:
        async with connection.transaction():
            source = await connection.fetchrow(
                """SELECT r.state, c.config FROM resources r
                JOIN containers c ON c.resource_id=r.id WHERE r.id=$1""",
                source_id,
            )
            target = await connection.fetchrow(
                "SELECT id, cluster_id FROM nodes WHERE name=$1", node
            )
            if source is None or target is None:
                raise ValueError("clone source or target disappeared")
            config = _object(source["config"])
            if task.payload.get("name") is not None:
                config["hostname"] = task.payload["name"]
            state = {**_object(source["state"]), **config, "status": "stopped"}
            await connection.execute(
                """INSERT INTO resources(id,node_id,cluster_id,kind,external_id,state,metadata)
                VALUES($1,$2,$3,'lxc',$4,$5::jsonb,'{}'::jsonb)""",
                target_id,
                target["id"],
                target["cluster_id"],
                str(vmid),
                json.dumps(state),
            )
            await connection.execute(
                """INSERT INTO containers(resource_id,cluster_id,vmid,config)
                VALUES($1,$2,$3,$4::jsonb)""",
                target_id,
                target["cluster_id"],
                vmid,
                json.dumps(config),
            )
    await repository.append_log(task.id, f"container cloned to {vmid}")
    return {"vmid": vmid, "node": node}


async def _migrate(
    repository: TaskRepository, task: Task, resource_id: uuid.UUID, clock: Clock
) -> dict[str, Any]:
    target = str(task.payload["target"])
    async with repository.pool.acquire() as connection:
        row = await connection.fetchrow("SELECT state FROM resources WHERE id=$1", resource_id)
        if row is None:
            raise ValueError("resource disappeared")
        state = _object(row["state"])
        transition = plan_transition(VmState(str(state["status"])), "migrate")
        state["status"] = transition.intermediate
        await connection.execute(
            "UPDATE resources SET state=$2::jsonb WHERE id=$1", resource_id, json.dumps(state)
        )
    await repository.append_log(task.id, f"migration to {target} started")
    await clock.sleep(1.0)
    async with repository.pool.acquire() as connection:
        node = await connection.fetchrow("SELECT id FROM nodes WHERE name=$1", target)
        if node is None:
            raise ValueError("target node disappeared")
        state["status"] = transition.after
        await connection.execute(
            """UPDATE resources SET node_id=$2,state=$3::jsonb,version=version+1,
            updated_at=now() WHERE id=$1""",
            resource_id,
            node["id"],
            json.dumps(state),
        )
    await repository.append_log(task.id, f"migration to {target} completed")
    return {"node": target, "status": str(transition.after)}


def _object(value: object) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(cast(Mapping[str, Any], value))
