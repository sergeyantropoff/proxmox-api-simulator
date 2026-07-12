"""Application resource ownership."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db.pool import AsyncpgDatabase, Database

DatabaseFactory = Callable[[Settings], Database]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_lifespan(settings: Settings, database_factory: DatabaseFactory) -> Lifespan:
    """Build a lifespan context so tests can inject a database implementation."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = database_factory(settings)
        await database.connect()
        app.state.database = database
        try:
            yield
        finally:
            await database.close()

    return lifespan


def default_database_factory(settings: Settings) -> Database:
    """Create the production asyncpg adapter."""

    return AsyncpgDatabase(settings)
