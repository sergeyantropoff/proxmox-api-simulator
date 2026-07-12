"""PostgreSQL migration acceptance checks."""

import os
import uuid

import asyncpg  # type: ignore[import-untyped]
import pytest

from app.db.migrations import migrate

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
