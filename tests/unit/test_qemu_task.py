"""QEMU worker transition semantics."""

import uuid
from datetime import UTC, datetime
from typing import cast

from app.simulation.clock import Clock
from app.tasks.qemu import qemu_handler
from app.tasks.repository import Task, TaskRepository


class ImmediateClock:
    async def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)

    async def sleep(self, seconds: float) -> None:
        assert seconds == 1.0


class Connection:
    def __init__(self) -> None:
        self.states: list[str] = []

    async def fetchrow(self, sql: str, resource_id: uuid.UUID) -> dict[str, object]:
        del sql, resource_id
        return {"state": '{"status":"stopped"}'}

    async def execute(self, sql: str, resource_id: uuid.UUID, state: str) -> str:
        del sql, resource_id
        self.states.append(state)
        return "UPDATE 1"


class Acquire:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> Connection:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        return None


class Pool:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def acquire(self) -> Acquire:
        return Acquire(self.connection)


class Repository:
    def __init__(self) -> None:
        self.connection = Connection()
        self.pool = Pool(self.connection)
        self.logs: list[str] = []

    async def append_log(self, task_id: uuid.UUID, message: str) -> None:
        del task_id
        self.logs.append(message)


async def test_qemu_worker_applies_intermediate_and_final_states() -> None:
    repository = Repository()
    task = Task(
        uuid.uuid4(),
        "UPID:test",
        "qemu-start",
        "running",
        {"resource_id": str(uuid.uuid4())},
        0,
        False,
        1,
    )

    result = await qemu_handler(cast(TaskRepository, repository), cast(Clock, ImmediateClock()))(
        task
    )

    assert result == {"status": "running"}
    assert '"starting"' in repository.connection.states[0]
    assert '"running"' in repository.connection.states[1]
    assert repository.logs == ["VM start started", "VM start completed"]
