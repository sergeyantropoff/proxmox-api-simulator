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


class Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class CrudConnection:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def transaction(self) -> Transaction:
        return Transaction()

    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None:
        del args
        if "FROM nodes" in sql:
            return {"id": uuid.uuid4(), "cluster_id": uuid.uuid4()}
        if "JOIN virtual_machines" in sql:
            return {"state": '{"status":"stopped","name":"old"}', "config": '{"name":"old"}'}
        if "SELECT state FROM resources" in sql:
            return {"state": '{"status":"stopped","name":"old"}'}
        if "FROM snapshots" in sql:
            return {
                "state": (
                    '{"resource_state":{"status":"stopped","name":"old"},"config":{"name":"old"}}'
                )
            }
        return None

    async def execute(self, sql: str, *args: object) -> str:
        del args
        self.commands.append(sql)
        return "DELETE 1" if sql.startswith("DELETE") else "UPDATE 1"


class CrudRepository:
    def __init__(self) -> None:
        self.connection = CrudConnection()
        self.pool = Pool(cast(Connection, self.connection))
        self.logs: list[str] = []

    async def append_log(self, _task_id: uuid.UUID, message: str) -> None:
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


async def test_qemu_worker_create_update_and_delete_are_persistent() -> None:
    repository = CrudRepository()
    handler = qemu_handler(cast(TaskRepository, repository), cast(Clock, ImmediateClock()))
    resource_id = uuid.uuid4()

    created = await handler(
        Task(
            uuid.uuid4(),
            "UPID:create",
            "qemu-create",
            "running",
            {"node": "pve1", "vmid": 150, "config": {"name": "new"}},
            0,
            False,
            1,
        )
    )
    updated = await handler(
        Task(
            uuid.uuid4(),
            "UPID:update",
            "qemu-update",
            "running",
            {
                "resource_id": str(resource_id),
                "changes": {"name": "changed", "cores": 4},
                "delete": "unused",
            },
            0,
            False,
            1,
        )
    )
    deleted = await handler(
        Task(
            uuid.uuid4(),
            "UPID:delete",
            "qemu-delete",
            "running",
            {"resource_id": str(resource_id)},
            0,
            False,
            1,
        )
    )

    assert created == {"vmid": 150, "status": "stopped"}
    assert updated == {"updated": ["cores", "name"], "deleted": ["unused"]}
    assert deleted == {"deleted": True}
    assert any("INSERT INTO resources" in command for command in repository.connection.commands)
    assert any("UPDATE virtual_machines" in command for command in repository.connection.commands)
    assert any("DELETE FROM resources" in command for command in repository.connection.commands)


async def test_qemu_worker_snapshot_create_rollback_and_delete_are_persistent() -> None:
    repository = CrudRepository()
    handler = qemu_handler(cast(TaskRepository, repository), cast(Clock, ImmediateClock()))
    resource_id = uuid.uuid4()

    async def run(operation: str, **payload: object) -> dict[str, object]:
        result = await handler(
            Task(
                uuid.uuid4(),
                f"UPID:{operation}",
                f"qemu-snapshot-{operation}",
                "running",
                {"resource_id": str(resource_id), "snapname": "baseline", **payload},
                0,
                False,
                1,
            )
        )
        assert result is not None
        return cast(dict[str, object], result)

    assert await run("create", description="stable") == {
        "snapshot": "baseline",
        "operation": "create",
    }
    assert await run("rollback", start=True) == {
        "snapshot": "baseline",
        "operation": "rollback",
    }
    assert await run("delete") == {"snapshot": "baseline", "operation": "delete"}
    commands = repository.connection.commands
    assert any("INSERT INTO snapshots" in command for command in commands)
    assert any("UPDATE virtual_machines" in command for command in commands)
    assert any("DELETE FROM snapshots" in command for command in commands)


async def test_qemu_worker_clone_and_migrate_are_persistent() -> None:
    repository = CrudRepository()
    handler = qemu_handler(cast(TaskRepository, repository), cast(Clock, ImmediateClock()))
    resource_id = uuid.uuid4()

    cloned = await handler(
        Task(
            uuid.uuid4(),
            "UPID:clone",
            "qemu-clone",
            "running",
            {
                "source_resource_id": str(resource_id),
                "node": "pve1",
                "vmid": 151,
                "name": "clone",
            },
            0,
            False,
            1,
        )
    )
    migrated = await handler(
        Task(
            uuid.uuid4(),
            "UPID:migrate",
            "qemu-migrate",
            "running",
            {"resource_id": str(resource_id), "target": "pve2"},
            0,
            False,
            1,
        )
    )

    assert cloned == {"vmid": 151, "node": "pve1"}
    assert migrated == {"node": "pve2", "status": "stopped"}
    commands = repository.connection.commands
    assert any("INSERT INTO resources" in command for command in commands)
    assert any("node_id=$2" in command for command in commands)
