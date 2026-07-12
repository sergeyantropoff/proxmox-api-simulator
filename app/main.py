"""FastAPI application factory and ASGI entry point."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.errors import unhandled_exception_handler
from app.api.middleware import RequestContextMiddleware
from app.config import Settings, get_settings
from app.lifespan import DatabaseFactory, create_lifespan, default_database_factory
from app.logging import configure_logging
from app.observability.health import router as health_router


def create_app(
    settings: Settings | None = None,
    database_factory: DatabaseFactory = default_database_factory,
) -> FastAPI:
    """Create an isolated application instance with explicit resource factories."""

    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    app = FastAPI(
        title=resolved.app_name,
        version="0.0.1",
        lifespan=create_lifespan(resolved, database_factory),
    )
    app.add_middleware(RequestContextMiddleware, header_name=resolved.request_id_header)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(health_router)
    return app


app = create_app()
