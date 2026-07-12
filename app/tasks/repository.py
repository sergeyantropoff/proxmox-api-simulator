"""PostgreSQL repository for durable leased tasks."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg  # type: ignore[import-untyped]  # noqa: F401
from asyncpg import Pool, Record

from app.db.primitives import ConflictError, require_affected, transaction


@dataclass(frozen=True, slots=True)
class Task:
    id: uuid.UUID
    upid: str
    task_type: str
    status: str
    payload: dict[str, Any]
    progress: int
    cancel_requested: bool
    attempt: int


def _task(row: Record) -> Task:
    return Task(
        id=row["id"],
        upid=str(row["upid"]),
        task_type=str(row["task_type"]),
        status=str(row["status"]),
        payload=json.loads(row["payload"])
        if isinstance(row["payload"], str)
        else dict(row["payload"]),
        progress=int(row["progress"]),
        cancel_requested=bool(row["cancel_requested"]),
        attempt=int(row["attempt"]),
    )


@dataclass(frozen=True, slots=True)
class TaskRepository:
    pool: Pool

    async def create(
        self,
        *,
        upid: str,
        task_type: str,
        payload: dict[str, Any],
        resource_key: str | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        task_id = uuid.uuid4()
        async with transaction(self.pool) as connection:
            if idempotency_key is not None:
                existing = await connection.fetchrow(
                    "SELECT * FROM tasks WHERE idempotency_key=$1", idempotency_key
                )
                if existing is not None:
                    return _task(existing)
            row = await connection.fetchrow(
                """INSERT INTO tasks(id, upid, task_type, status, payload, idempotency_key)
                VALUES($1,$2,$3,'queued',$4::jsonb,$5) RETURNING *""",
                task_id,
                upid,
                task_type,
                json.dumps(payload),
                idempotency_key,
            )
            if resource_key is not None:
                try:
                    await connection.execute(
                        "INSERT INTO resource_locks(resource_key, task_id) VALUES($1,$2)",
                        resource_key,
                        task_id,
                    )
                except Exception as error:
                    raise ConflictError(f"resource is locked: {resource_key}") from error
            await connection.execute(
                "INSERT INTO task_events(task_id, kind) VALUES($1,'created')", task_id
            )
            if row is None:
                raise RuntimeError("task insert returned no row")
            return _task(row)

    async def claim(self, worker_id: str, lease_seconds: float) -> Task | None:
        async with transaction(self.pool) as connection:
            row = await connection.fetchrow(
                """WITH candidate AS (
                    SELECT id FROM tasks
                    WHERE status='queued' OR (status='running' AND lease_expires_at < now())
                    ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE tasks SET status='running', worker_id=$1,
                    lease_expires_at=now() + $2 * interval '1 second', attempt=attempt+1,
                    updated_at=now()
                WHERE id=(SELECT id FROM candidate) RETURNING *""",
                worker_id,
                lease_seconds,
            )
            if row is None:
                return None
            await connection.execute(
                "INSERT INTO task_events(task_id, kind, data) VALUES($1,'claimed',$2::jsonb)",
                row["id"],
                json.dumps({"worker": worker_id}),
            )
            return _task(row)

    async def heartbeat(self, task_id: uuid.UUID, worker_id: str, lease_seconds: float) -> None:
        status = await self.pool.execute(
            """UPDATE tasks SET lease_expires_at=now()+$3*interval '1 second', updated_at=now()
            WHERE id=$1 AND worker_id=$2 AND status='running'""",
            task_id,
            worker_id,
            lease_seconds,
        )
        require_affected(status)

    async def progress(self, task_id: uuid.UUID, worker_id: str, value: int) -> None:
        status = await self.pool.execute(
            """UPDATE tasks SET progress=$3, updated_at=now()
            WHERE id=$1 AND worker_id=$2 AND status='running'""",
            task_id,
            worker_id,
            value,
        )
        require_affected(status)

    async def append_log(self, task_id: uuid.UUID, message: str) -> None:
        await self.pool.execute(
            "INSERT INTO task_logs(task_id, message) VALUES($1,$2)", task_id, message
        )

    async def request_cancel(self, task_id: uuid.UUID) -> None:
        status = await self.pool.execute(
            """UPDATE tasks SET cancel_requested=true, updated_at=now()
            WHERE id=$1 AND status IN ('queued','running')""",
            task_id,
        )
        require_affected(status)

    async def finish(
        self,
        task_id: uuid.UUID,
        worker_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in {"success", "error", "cancelled"}:
            raise ValueError("invalid terminal task status")
        async with transaction(self.pool) as connection:
            command = await connection.execute(
                """UPDATE tasks SET status=$3, result=$4::jsonb, error=$5,
                progress=CASE WHEN $3='success' THEN 100 ELSE progress END,
                lease_expires_at=NULL, updated_at=now()
                WHERE id=$1 AND worker_id=$2 AND status='running'""",
                task_id,
                worker_id,
                status,
                json.dumps(result) if result is not None else None,
                error,
            )
            require_affected(command)
            await connection.execute("DELETE FROM resource_locks WHERE task_id=$1", task_id)
            await connection.execute(
                "INSERT INTO task_events(task_id, kind, data) VALUES($1,$2,$3::jsonb)",
                task_id,
                status,
                json.dumps({"error": error} if error else {}),
            )

    async def get(self, task_id: uuid.UUID) -> Task | None:
        row = await self.pool.fetchrow("SELECT * FROM tasks WHERE id=$1", task_id)
        return _task(row) if row is not None else None

    async def logs(self, task_id: uuid.UUID) -> tuple[str, ...]:
        rows = await self.pool.fetch(
            "SELECT message FROM task_logs WHERE task_id=$1 ORDER BY sequence", task_id
        )
        return tuple(str(row["message"]) for row in rows)
