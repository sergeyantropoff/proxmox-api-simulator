"""Worker semantics for asynchronous QEMU transitions."""

from __future__ import annotations

import json
import uuid

from app.simulation.clock import Clock
from app.simulation.transitions import VmState, plan_transition
from app.tasks.repository import Task, TaskRepository
from app.tasks.worker import TaskHandler


def qemu_handler(repository: TaskRepository, clock: Clock) -> TaskHandler:
    async def execute(task: Task) -> dict[str, str]:
        operation = task.task_type.removeprefix("qemu-")
        resource_id = uuid.UUID(str(task.payload["resource_id"]))
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
