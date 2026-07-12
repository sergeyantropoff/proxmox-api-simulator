"""Bounded task worker outcome tests."""

import asyncio
import uuid
from typing import cast

from app.tasks.repository import Task, TaskRepository
from app.tasks.worker import TaskWorker


class FakeRepository:
    def __init__(self, task: Task) -> None:
        self.task = task
        self.finishes: list[tuple[str, str | None]] = []

    async def get(self, _task_id: uuid.UUID) -> Task:
        return self.task

    async def finish(
        self,
        _task_id: uuid.UUID,
        _worker_id: str,
        *,
        status: str,
        result: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        del result
        self.finishes.append((status, error))


def make_task(*, task_type: str = "test", cancelled: bool = False) -> Task:
    return Task(uuid.uuid4(), "UPID:test", task_type, "running", {}, 0, cancelled, 1)


async def test_worker_persists_success_error_and_unsupported() -> None:
    task = make_task()
    repository = FakeRepository(task)

    async def success(_task: Task) -> dict[str, object]:
        return {"ok": True}

    worker = TaskWorker(cast(TaskRepository, repository), "worker", {"test": success})
    await worker._execute(task)
    assert repository.finishes == [("success", None)]

    unsupported = make_task(task_type="missing")
    repository.task = unsupported
    await worker._execute(unsupported)
    assert repository.finishes[-1] == ("error", "unsupported task type")

    async def failure(_task: Task) -> None:
        raise RuntimeError("private detail")

    failed = make_task()
    repository.task = failed
    worker.handlers["test"] = failure
    await worker._execute(failed)
    assert repository.finishes[-1] == ("error", "RuntimeError")


async def test_worker_honors_persisted_cancellation() -> None:
    task = make_task(cancelled=True)
    repository = FakeRepository(task)
    called = False

    async def handler(_task: Task) -> None:
        nonlocal called
        called = True

    worker = TaskWorker(cast(TaskRepository, repository), "worker", {"test": handler})
    await worker._execute(task)

    assert not called
    assert repository.finishes == [("cancelled", None)]


async def test_worker_retries_after_claim_failure() -> None:
    class RecoveringRepository:
        attempts = 0

        async def claim(self, _worker_id: str, _lease_seconds: float) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("database schema is not ready")
            return None

    repository = RecoveringRepository()
    worker = TaskWorker(
        cast(TaskRepository, repository),
        "worker",
        {},
        poll_seconds=0.001,
    )
    running = asyncio.create_task(worker.run())
    await asyncio.sleep(0.01)
    worker.stop()
    await running

    assert repository.attempts > 1
