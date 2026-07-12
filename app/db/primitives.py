"""Typed transactional helpers and stable database error mapping."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import asyncpg  # type: ignore[import-untyped]
from asyncpg import Connection, Pool


class DatabaseOperationError(RuntimeError):
    """Safe base error for repository operations."""


class ConflictError(DatabaseOperationError):
    pass


class ReferenceError(DatabaseOperationError):
    pass


class TransientDatabaseError(DatabaseOperationError):
    pass


def map_database_error(error: asyncpg.PostgresError) -> DatabaseOperationError:
    if isinstance(error, asyncpg.UniqueViolationError):
        return ConflictError("database uniqueness constraint failed")
    if isinstance(error, asyncpg.ForeignKeyViolationError):
        return ReferenceError("database reference constraint failed")
    if isinstance(
        error,
        asyncpg.SerializationError
        | asyncpg.DeadlockDetectedError
        | asyncpg.TooManyConnectionsError,
    ):
        return TransientDatabaseError("transient database failure")
    return DatabaseOperationError("database operation failed")


@asynccontextmanager
async def transaction(pool: Pool) -> AsyncIterator[Connection]:
    async with pool.acquire() as connection:
        try:
            async with connection.transaction():
                yield connection
        except asyncpg.PostgresError as error:
            raise map_database_error(error) from error


@asynccontextmanager
async def savepoint(connection: Connection) -> AsyncIterator[Connection]:
    try:
        async with connection.transaction():
            yield connection
    except asyncpg.PostgresError as error:
        raise map_database_error(error) from error


def require_affected(status: str, expected: int = 1) -> None:
    try:
        affected = int(status.rsplit(" ", 1)[1])
    except (IndexError, ValueError) as error:
        raise DatabaseOperationError(f"unrecognized command status: {status}") from error
    if affected != expected:
        raise DatabaseOperationError(f"expected {expected} affected row(s), got {affected}")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.02


DEFAULT_RETRY_POLICY = RetryPolicy()


async def retry_transient[T](
    operation: Callable[[], Awaitable[T]], policy: RetryPolicy = DEFAULT_RETRY_POLICY
) -> T:
    if policy.attempts < 1:
        raise ValueError("retry attempts must be positive")
    for attempt in range(policy.attempts):
        try:
            return await operation()
        except TransientDatabaseError:
            if attempt + 1 == policy.attempts:
                raise
            await asyncio.sleep(policy.base_delay_seconds * (2**attempt))
    raise RuntimeError("unreachable retry state")
