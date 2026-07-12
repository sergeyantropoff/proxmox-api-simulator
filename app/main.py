"""FastAPI application factory and ASGI entry point."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI, Response

from app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from app.api.middleware import RequestContextMiddleware
from app.api.registry import HandlerRegistry, register_contract_routes
from app.compatibility import CompatibilityDimension, build_report, load_evidence_manifest
from app.config import Settings, get_settings
from app.contracts.model import Snapshot
from app.db.pool import AsyncpgDatabase, Database
from app.handlers.core import build_core_handlers
from app.lifespan import DatabaseFactory, WorkerFactory, create_lifespan, default_database_factory
from app.logging import configure_logging
from app.observability.health import router as health_router
from app.simulation.clock import AcceleratedClock
from app.tasks.qemu import qemu_handler
from app.tasks.repository import TaskRepository
from app.tasks.worker import TaskWorker


def create_app(
    settings: Settings | None = None,
    database_factory: DatabaseFactory = default_database_factory,
    handlers: HandlerRegistry | None = None,
    worker_factories: tuple[WorkerFactory, ...] | None = None,
) -> FastAPI:
    """Create an isolated application instance with explicit resource factories."""

    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    resolved_workers = worker_factories
    if resolved_workers is None and resolved.contract_snapshot is not None and handlers is None:

        def task_worker(database: Database) -> TaskWorker:
            adapter = cast(AsyncpgDatabase, database)
            repository = TaskRepository(adapter.pool)
            handler = qemu_handler(repository, AcceleratedClock(resolved.simulation_time_scale))
            return TaskWorker(
                repository,
                "simulator-worker",
                {
                    "qemu-create": handler,
                    "qemu-delete": handler,
                    "qemu-reboot": handler,
                    "qemu-reset": handler,
                    "qemu-resume": handler,
                    "qemu-shutdown": handler,
                    "qemu-start": handler,
                    "qemu-stop": handler,
                    "qemu-suspend": handler,
                    "qemu-update": handler,
                },
                concurrency=resolved.task_worker_concurrency,
                lease_seconds=resolved.task_lease_seconds,
            )

        resolved_workers = (task_worker,)
    app = FastAPI(
        title=resolved.app_name,
        version="0.1.0",
        lifespan=create_lifespan(resolved, database_factory, resolved_workers or ()),
    )
    app.state.settings = resolved
    app.add_middleware(RequestContextMiddleware, header_name=resolved.request_id_header)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(health_router)
    if resolved.contract_snapshot is not None:
        snapshot = Snapshot.model_validate_json(resolved.contract_snapshot.read_bytes())
        resolved_handlers = handlers or build_core_handlers(resolved)
        register_contract_routes(
            app,
            snapshot,
            resolved_handlers,
            resolved.contract_fallback,
        )
        declared = frozenset(
            (path.path, method.verb) for path in snapshot.paths for method in path.methods
        )
        dimensions = {CompatibilityDimension.ROUTE_METHOD: declared}
        if resolved.compatibility_evidence is not None:
            evidence = load_evidence_manifest(resolved.compatibility_evidence)
            if evidence.source_version != snapshot.source_version:
                raise ValueError("compatibility evidence version does not match contract")
            dimensions.update(evidence.dimension_map())
            dimensions[CompatibilityDimension.ROUTE_METHOD] = declared
        report = build_report(
            snapshot,
            implemented=resolved_handlers.keys() & declared,
            dimensions=dimensions,
        )

        @app.get("/admin/compatibility", include_in_schema=False)
        async def compatibility_report() -> dict[str, object]:
            return report.as_json()

        @app.get("/admin/compatibility.md", include_in_schema=False)
        async def compatibility_report_markdown() -> Response:
            return Response(report.as_markdown(), media_type="text/markdown")

        @app.get("/admin/compatibility.html", include_in_schema=False)
        async def compatibility_report_html() -> Response:
            return Response(report.as_html(), media_type="text/html")

    return app


app = create_app()
