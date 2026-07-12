"""Small typed asyncpg pool boundary."""

from __future__ import annotations

from typing import Protocol, Self, cast

import asyncpg  # type: ignore[import-untyped]
from asyncpg import Pool

from app.config import Settings


class Database(Protocol):
    """Application-facing database lifecycle and health interface."""

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def is_ready(self) -> bool: ...


class AsyncpgDatabase:
    """Own an asyncpg pool without exposing it as global mutable state."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: Pool | None = None

    @property
    def pool(self) -> Pool:
        """Return the initialized pool to repository factories."""

        if self._pool is None:
            message = "database pool is not initialized"
            raise RuntimeError(message)
        return self._pool

    async def connect(self) -> None:
        """Create the pool and verify the first connection."""

        if self._pool is not None:
            return
        settings = self._settings
        pool = await asyncpg.create_pool(
            dsn=settings.database_url.get_secret_value(),
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            timeout=settings.db_connect_timeout_seconds,
            command_timeout=settings.db_command_timeout_seconds,
        )
        if pool is None:  # pragma: no cover - asyncpg types allow this for legacy reasons
            message = "asyncpg did not create a pool"
            raise RuntimeError(message)
        self._pool = cast(Pool, pool)

    async def close(self) -> None:
        """Close all pooled connections; repeated close is safe."""

        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.close()

    async def is_ready(self) -> bool:
        """Check that PostgreSQL accepts a trivial query."""

        if self._pool is None:
            return False
        try:
            return bool(await self._pool.fetchval("SELECT 1") == 1)
        except asyncpg.PostgresError:
            return False

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()
