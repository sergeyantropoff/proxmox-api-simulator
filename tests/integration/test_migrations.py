"""PostgreSQL migration acceptance checks."""

import os
import uuid

import asyncpg  # type: ignore[import-untyped]
import pytest

from app.config import Settings
from app.db.migrations import migrate
from app.db.pool import AsyncpgDatabase
from app.db.primitives import ConflictError
from app.db.repositories.resources import ResourceRepository
from app.simulation.seed import apply_seed, small_profile

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required"),
]


async def test_migration_is_repeatable_and_constraints_hold() -> None:
    connection = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        await migrate(connection)
        assert await migrate(connection) == 0
        node_id = uuid.uuid4()
        await connection.execute(
            "INSERT INTO nodes(id, name, status) VALUES($1, $2, 'online') ON CONFLICT DO NOTHING",
            node_id,
            f"test-{node_id}",
        )
        with pytest.raises(asyncpg.CheckViolationError):
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO nodes(id, name, status) VALUES($1, $2, 'invalid')",
                    uuid.uuid4(),
                    f"invalid-{node_id}",
                )
    finally:
        await connection.close()


async def test_small_seed_is_idempotent() -> None:
    connection = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        await migrate(connection)
        await apply_seed(connection, small_profile())
        await apply_seed(connection, small_profile())
        assert await connection.fetchval("SELECT count(*) FROM nodes WHERE name = 'pve1'") == 1
        assert (
            await connection.fetchval(
                """SELECT count(*) FROM resources
                WHERE external_id IN ('100', '101', '200', 'local', 'local-lvm')"""
            )
            == 5
        )
        assert await connection.fetchval("SELECT count(*) FROM tasks WHERE status = 'success'") == 2
        assert await connection.fetchval("SELECT count(*) FROM virtual_machines") == 2
        assert await connection.fetchval("SELECT count(*) FROM containers") == 1
        assert await connection.fetchval("SELECT count(*) FROM storages") == 2
        assert await connection.fetchval("SELECT count(*) FROM storage_contents") == 4
        assert await connection.fetchval("SELECT count(*) FROM identity_groups") == 1
        assert await connection.fetchval("SELECT count(*) FROM identity_group_members") == 1
        assert await connection.fetchval("SELECT count(*) FROM group_acl_entries") == 1
        assert await connection.fetchval("SELECT count(*) FROM roles") == 3
        assert await connection.fetchval("SELECT count(*) FROM api_tokens") == 4
        secrets = await connection.fetch("SELECT secret_hash FROM api_tokens")
        assert all(str(row["secret_hash"]).startswith("scrypt$") for row in secrets)
        assert all("-secret" not in str(row["secret_hash"]) for row in secrets)
    finally:
        await connection.close()


async def test_schema_readiness_and_optimistic_resource_repository() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    connection = await asyncpg.connect(url)
    database = AsyncpgDatabase(Settings(database_url=url))
    try:
        await migrate(connection)
        await apply_seed(connection, small_profile())
        await database.connect()
        assert await database.is_ready()

        repository = ResourceRepository(database.pool)
        resource = await repository.get(kind="qemu", external_id="101")
        assert resource is not None
        updated = await repository.update_state(
            resource.id,
            expected_version=resource.version,
            state={**resource.state, "status": "running"},
        )
        assert updated.version == resource.version + 1
        assert updated.state["status"] == "running"
        with pytest.raises(ConflictError):
            await repository.update_state(
                resource.id,
                expected_version=resource.version,
                state=resource.state,
            )
    finally:
        await database.close()
        await connection.close()
