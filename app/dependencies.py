"""FastAPI dependency adapters."""

from __future__ import annotations

from fastapi import Request

from app.db.pool import Database


def get_database(request: Request) -> Database:
    """Resolve the lifespan-owned database from application state."""

    database: Database = request.app.state.database
    return database
