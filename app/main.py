"""FastAPI application factory and ASGI entry point."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.errors import unhandled_exception_handler
from app.api.middleware import RequestContextMiddleware
from app.api.registry import HandlerRegistry, register_contract_routes
from app.config import Settings, get_settings
from app.contracts.model import Snapshot
from app.lifespan import DatabaseFactory, create_lifespan, default_database_factory
from app.logging import configure_logging
from app.observability.health import router as health_router


def create_app(
    settings: Settings | None = None,
    database_factory: DatabaseFactory = default_database_factory,
    handlers: HandlerRegistry | None = None,
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
    if resolved.contract_snapshot is not None:
        snapshot = Snapshot.model_validate_json(resolved.contract_snapshot.read_bytes())
        register_contract_routes(
            app,
            snapshot,
            handlers or HandlerRegistry(),
            resolved.contract_fallback,
        )
    return app


app = create_app()
