"""Bounded durable task worker with cooperative cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.tasks.repository import Task, TaskRepository

TaskHandler = Callable[[Task], Awaitable[dict[str, Any] | None]]


@dataclass(slots=True)
class TaskWorker:
    repository: TaskRepository
    worker_id: str
    handlers: dict[str, TaskHandler]
    concurrency: int = 2
    lease_seconds: float = 30.0
    poll_seconds: float = 0.1
    _running: set[asyncio.Task[None]] = field(default_factory=set, init=False)
    _stopping: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    async def run(self) -> None:
        self._stopping.clear()
        try:
            while not self._stopping.is_set():
                self._reap()
                if len(self._running) >= self.concurrency:
                    await asyncio.sleep(self.poll_seconds)
                    continue
                task = await self.repository.claim(self.worker_id, self.lease_seconds)
                if task is None:
                    await asyncio.sleep(self.poll_seconds)
                    continue
                execution = asyncio.create_task(self._execute(task))
                self._running.add(execution)
        finally:
            if self._running:
                await asyncio.gather(*self._running, return_exceptions=True)
            self._running.clear()

    def stop(self) -> None:
        self._stopping.set()

    def _reap(self) -> None:
        self._running = {task for task in self._running if not task.done()}

    async def _execute(self, task: Task) -> None:
        handler = self.handlers.get(task.task_type)
        if handler is None:
            await self.repository.finish(
                task.id, self.worker_id, status="error", error="unsupported task type"
            )
            return
        try:
            current = await self.repository.get(task.id)
            if current is not None and current.cancel_requested:
                await self.repository.finish(task.id, self.worker_id, status="cancelled")
                return
            execution: asyncio.Future[dict[str, Any] | None] = asyncio.ensure_future(handler(task))
            heartbeat = asyncio.create_task(self._heartbeat(task))
            try:
                while not execution.done():
                    await asyncio.sleep(self.poll_seconds)
                    current = await self.repository.get(task.id)
                    if current is not None and current.cancel_requested:
                        execution.cancel()
                        await asyncio.gather(execution, return_exceptions=True)
                        await self.repository.finish(task.id, self.worker_id, status="cancelled")
                        return
                result = await execution
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            await self.repository.finish(task.id, self.worker_id, status="success", result=result)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # task failures are persisted, not leaked
            await self.repository.finish(
                task.id, self.worker_id, status="error", error=type(error).__name__
            )

    async def _heartbeat(self, task: Task) -> None:
        interval = max(self.lease_seconds / 3, 0.01)
        while True:
            await asyncio.sleep(interval)
            await self.repository.heartbeat(task.id, self.worker_id, self.lease_seconds)
