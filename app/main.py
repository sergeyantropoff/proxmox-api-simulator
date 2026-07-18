"""FastAPI application factory and ASGI entry point."""

from __future__ import annotations

import asyncio
from typing import cast

from fastapi import FastAPI

from app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from app.api.middleware import RequestContextMiddleware
from app.api.openapi import openapi_tag_metadata
from app.api.registry import HandlerRegistry
from app.config import Settings, get_settings
from app.contracts.model import Snapshot
from app.contracts.runtime import apply_runtime_contract, contract_store_root
from app.db.pool import AsyncpgDatabase, Database
from app.handlers.core import build_core_handlers
from app.lifespan import DatabaseFactory, WorkerFactory, create_lifespan, default_database_factory
from app.logging import configure_logging
from app.observability.health import router as health_router
from app.simulation.clock import AcceleratedClock
from app.tasks.backup import backup_handler
from app.tasks.lxc import lxc_handler
from app.tasks.qemu import qemu_handler
from app.tasks.repository import TaskRepository
from app.tasks.worker import TaskWorker
from app.web.routes import router as web_router


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
            clock = AcceleratedClock(resolved.simulation_time_scale)
            qemu = qemu_handler(repository, clock)
            lxc = lxc_handler(repository, clock)
            backup = backup_handler(repository, clock)
            return TaskWorker(
                repository,
                "simulator-worker",
                {
                    "qemu-clone": qemu,
                    "qemu-create": qemu,
                    "qemu-delete": qemu,
                    "qemu-reboot": qemu,
                    "qemu-reset": qemu,
                    "qemu-resume": qemu,
                    "qemu-shutdown": qemu,
                    "qemu-migrate": qemu,
                    "qemu-move-disk": qemu,
                    "qemu-snapshot-create": qemu,
                    "qemu-snapshot-delete": qemu,
                    "qemu-snapshot-rollback": qemu,
                    "qemu-start": qemu,
                    "qemu-stop": qemu,
                    "qemu-suspend": qemu,
                    "qemu-update": qemu,
                    "qemu-resize": qemu,
                    "qemu-template": qemu,
                    "lxc-clone": lxc,
                    "lxc-create": lxc,
                    "lxc-delete": lxc,
                    "lxc-migrate": lxc,
                    "lxc-reboot": lxc,
                    "lxc-resume": lxc,
                    "lxc-resize": lxc,
                    "lxc-shutdown": lxc,
                    "lxc-snapshot-create": lxc,
                    "lxc-snapshot-delete": lxc,
                    "lxc-snapshot-rollback": lxc,
                    "lxc-start": lxc,
                    "lxc-stop": lxc,
                    "lxc-suspend": lxc,
                    "vzdump": backup,
                    "aptupdate": backup,
                    "network-reload": backup,
                    "disk-initgpt": backup,
                    "disk-wipe": backup,
                    "disk-directory-create": backup,
                    "disk-directory-delete": backup,
                    "disk-lvm-create": backup,
                    "disk-lvm-delete": backup,
                    "disk-lvmthin-create": backup,
                    "disk-lvmthin-delete": backup,
                    "disk-zfs-create": backup,
                    "disk-zfs-delete": backup,
                    "service-start": backup,
                    "service-stop": backup,
                    "service-restart": backup,
                    "service-reload": backup,
                    "storage-allocate": backup,
                    "storage-upload": backup,
                    "prune-backups": backup,
                    "acme": backup,
                    "sdn-apply": backup,
                    "ceph-flags": backup,
                    "cluster-create": backup,
                    "cluster-join": backup,
                },
                concurrency=resolved.task_worker_concurrency,
                lease_seconds=resolved.task_lease_seconds,
            )

        resolved_workers = (task_worker,)
    app = FastAPI(
        title=resolved.app_name,
        version="0.1.0",
        openapi_tags=openapi_tag_metadata(),
        lifespan=create_lifespan(resolved, database_factory, resolved_workers or ()),
    )
    app.state.settings = resolved
    app.state.contract_swap_lock = asyncio.Lock()
    app.add_middleware(RequestContextMiddleware, header_name=resolved.request_id_header)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(web_router)
    app.include_router(health_router)
    if resolved.contract_snapshot is not None:
        snapshot = Snapshot.model_validate_json(resolved.contract_snapshot.read_bytes())
        resolved_handlers = handlers or build_core_handlers(resolved)
        apply_runtime_contract(
            app,
            snapshot,
            handlers=resolved_handlers,
            store_root=contract_store_root(resolved),
            fallback=resolved.contract_fallback,
            settings=resolved,
            require_evidence_match=True,
            register_admin=True,
        )

    return app


app = create_app()
