"""Database primitive behavior independent of PostgreSQL."""

import asyncpg  # type: ignore[import-untyped]
import pytest

from app.db.primitives import (
    ConflictError,
    DatabaseOperationError,
    ReferenceError,
    RetryPolicy,
    TransientDatabaseError,
    map_database_error,
    require_affected,
    retry_transient,
)


def test_error_mapping_is_stable_and_safe() -> None:
    assert isinstance(map_database_error(asyncpg.UniqueViolationError("secret")), ConflictError)
    assert isinstance(
        map_database_error(asyncpg.ForeignKeyViolationError("secret")), ReferenceError
    )
    assert isinstance(
        map_database_error(asyncpg.SerializationError("secret")), TransientDatabaseError
    )
    assert "secret" not in str(map_database_error(asyncpg.PostgresError("secret")))


def test_affected_row_checks() -> None:
    require_affected("UPDATE 1")
    with pytest.raises(DatabaseOperationError, match="expected 1"):
        require_affected("UPDATE 0")
    with pytest.raises(DatabaseOperationError, match="unrecognized"):
        require_affected("BROKEN")


async def test_transient_retry_is_bounded() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TransientDatabaseError("retry")
        return "ok"

    assert await retry_transient(operation, RetryPolicy(attempts=3, base_delay_seconds=0)) == "ok"
    assert calls == 3


async def test_transient_retry_propagates_final_failure() -> None:
    async def operation() -> None:
        raise TransientDatabaseError("retry")

    with pytest.raises(TransientDatabaseError):
        await retry_transient(operation, RetryPolicy(attempts=2, base_delay_seconds=0))

    with pytest.raises(ValueError, match="positive"):
        await retry_transient(operation, RetryPolicy(attempts=0))
