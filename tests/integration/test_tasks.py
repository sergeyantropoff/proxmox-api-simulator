"""Durable task concurrency and recovery tests."""

import asyncio
import os
import uuid

import asyncpg  # type: ignore[import-untyped]
import pytest
from asyncpg import Pool

from app.db.migrations import migrate
from app.tasks.repository import TaskRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required"),
]


async def repository() -> tuple[Pool, TaskRepository]:
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=4)
    async with pool.acquire() as connection:
        await migrate(connection)
    return pool, TaskRepository(pool)


async def test_two_worker_exclusion_idempotency_and_logs() -> None:
    pool, tasks = await repository()
    key = uuid.uuid4().hex
    try:
        created = await tasks.create(
            upid=f"UPID:pve1:00000001:00000001:00000001:test:{key}:root@pam:",
            task_type="test",
            payload={"value": 1},
            resource_key=f"vm:{key}",
            idempotency_key=key,
        )
        repeated = await tasks.create(
            upid=f"ignored-{key}", task_type="test", payload={}, idempotency_key=key
        )
        assert repeated.id == created.id

        first, second = await asyncio.gather(
            tasks.claim("worker-a", 30), tasks.claim("worker-b", 30)
        )
        claimed = first or second
        assert claimed is not None
        assert (first is None) != (second is None)
        worker = "worker-a" if first is not None else "worker-b"
        await tasks.append_log(claimed.id, "started")
        await tasks.progress(claimed.id, worker, 50)
        await tasks.finish(claimed.id, worker, status="success", result={"ok": True})
        assert await tasks.logs(claimed.id) == ("started",)
        finished = await tasks.get(claimed.id)
        assert finished is not None
        assert finished.status == "success"
    finally:
        await pool.close()


async def test_expired_lease_is_reclaimed_after_restart() -> None:
    pool, tasks = await repository()
    key = uuid.uuid4().hex
    try:
        created = await tasks.create(
            upid=f"UPID:pve1:00000001:00000001:00000001:test:{key}:root@pam:",
            task_type="test",
            payload={},
        )
        assert await tasks.claim("dead-worker", 0) is not None
        recovered = await tasks.claim("new-worker", 30)
        assert recovered is not None
        assert recovered.id == created.id
        assert recovered.attempt == 2
        await tasks.request_cancel(recovered.id)
        cancelled = await tasks.get(recovered.id)
        assert cancelled is not None
        assert cancelled.cancel_requested
        await tasks.finish(recovered.id, "new-worker", status="cancelled")
    finally:
        await pool.close()
