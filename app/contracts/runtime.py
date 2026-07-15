"""In-memory runtime contract hot-swap helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from starlette.routing import Route

from app.api.registry import (
    FallbackMode,
    HandlerRegistry,
    register_contract_routes,
    register_legacy_handler_routes,
)
from app.compatibility import (
    CompatibilityDimension,
    CompatibilityReport,
    build_report,
    load_evidence_manifest,
    resolve_evidence_path,
)
from app.config import Settings
from app.contracts.model import Snapshot

_ADMIN_ROUTE_NAMES = frozenset(
    {
        "admin:compatibility",
        "admin:compatibility.md",
        "admin:compatibility.html",
    }
)


def clear_contract_routes(app: FastAPI) -> None:
    """Drop previously registered contract (and optional admin) routes for rebuild."""

    app.router.routes = [route for route in app.router.routes if not _is_swappable_route(route)]
    app.openapi_schema = None


def _is_swappable_route(route: object) -> bool:
    name = getattr(route, "name", None)
    if not isinstance(name, str):
        return False
    return name.startswith("contract:") or name in _ADMIN_ROUTE_NAMES


def build_compatibility_for_snapshot(
    snapshot: Snapshot,
    handlers: HandlerRegistry,
    settings: Settings,
    *,
    require_evidence_match: bool = False,
) -> CompatibilityReport:
    """Build a compatibility report for the active primary snapshot.

    Evidence is resolved per ``snapshot.source_version``
    (``evidence/pve-{version}.json``). When ``require_evidence_match`` is true
    (cold start) a missing or mismatched ledger raises.
    """

    declared = frozenset(
        (path.path, method.verb.upper()) for path in snapshot.paths for method in path.methods
    )
    dimensions: dict[CompatibilityDimension, frozenset[tuple[str, str]]] = {
        CompatibilityDimension.ROUTE_METHOD: declared,
    }
    observed: frozenset[tuple[str, str]] = frozenset()
    verified: frozenset[tuple[str, str]] = frozenset()
    evidence_path = resolve_evidence_path(snapshot.source_version, settings)
    if evidence_path is not None:
        evidence = load_evidence_manifest(evidence_path)
        if evidence.source_version != snapshot.source_version:
            if require_evidence_match:
                raise ValueError("compatibility evidence version does not match contract")
        else:
            dimensions.update(evidence.dimension_map())
            dimensions[CompatibilityDimension.ROUTE_METHOD] = declared
            observed = evidence.observed_methods() & declared
            verified = evidence.verified_methods() & declared
    implemented_all = frozenset(handlers.keys())
    return build_report(
        snapshot,
        implemented=implemented_all & declared,
        observed=observed,
        verified=verified,
        dimensions=dimensions,
    )


def apply_runtime_contract(
    app: FastAPI,
    snapshot: Snapshot,
    *,
    handlers: HandlerRegistry,
    store_root: Path,
    fallback: FallbackMode,
    settings: Settings,
    require_evidence_match: bool = False,
    register_admin: bool = True,
) -> CompatibilityReport:
    """Replace `/api2/*` contract routes and refresh runtime app.state fields."""

    clear_contract_routes(app)
    registered = register_contract_routes(app, snapshot, handlers, fallback)
    register_legacy_handler_routes(
        app,
        handlers,
        store_root,
        fallback,
        primary_version=snapshot.source_version,
        existing=registered,
    )
    report = build_compatibility_for_snapshot(
        snapshot,
        handlers,
        settings,
        require_evidence_match=require_evidence_match,
    )
    implemented_all = frozenset(handlers.keys())
    app.state.runtime_snapshot = snapshot
    app.state.runtime_source_version = snapshot.source_version
    app.state.handlers = handlers
    app.state.contract_store_root = store_root
    app.state.implemented_methods = implemented_all
    app.state.compatibility_report = report
    if register_admin:
        _ensure_admin_compatibility_routes(app)
    return report


async def apply_runtime_contract_locked(
    app: FastAPI,
    snapshot: Snapshot,
    *,
    handlers: HandlerRegistry,
    store_root: Path,
    fallback: FallbackMode,
    settings: Settings,
    require_evidence_match: bool = False,
    register_admin: bool = True,
) -> CompatibilityReport:
    """Serialize concurrent Apply calls to avoid a torn route table."""

    lock = getattr(app.state, "contract_swap_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        app.state.contract_swap_lock = lock
    async with lock:
        return apply_runtime_contract(
            app,
            snapshot,
            handlers=handlers,
            store_root=store_root,
            fallback=fallback,
            settings=settings,
            require_evidence_match=require_evidence_match,
            register_admin=register_admin,
        )


def contract_store_root(settings: Settings) -> Path:
    """Resolve the revision store root next to ``CONTRACT_SNAPSHOT``."""

    if settings.contract_snapshot is None:
        return Path("contracts")
    snapshot_path = settings.contract_snapshot.resolve()
    if snapshot_path.name == "snapshot.json" and (snapshot_path.parent / "manifest.json").is_file():
        return snapshot_path.parent.parent
    return snapshot_path.parent


def runtime_version_payload(request: Request) -> dict[str, str]:
    """Proxmox-shaped version payload derived from the active runtime contract."""

    version = getattr(request.app.state, "runtime_source_version", None) or "0.0"
    release = str(version).split("-", 1)[0]
    if release.count(".") >= 2:
        release = ".".join(release.split(".")[:2])
    return {"version": str(version), "release": release, "repoid": "simulator"}


def _ensure_admin_compatibility_routes(app: FastAPI) -> None:
    existing = {
        getattr(route, "name", None) for route in app.router.routes if isinstance(route, Route)
    }
    if "admin:compatibility" in existing:
        return

    @app.get("/admin/compatibility", include_in_schema=False, name="admin:compatibility")
    async def compatibility_report(request: Request) -> dict[str, Any]:
        report = getattr(request.app.state, "compatibility_report", None)
        if report is None:
            return {}
        return cast(dict[str, Any], report.as_json())

    @app.get("/admin/compatibility.md", include_in_schema=False, name="admin:compatibility.md")
    async def compatibility_report_markdown(request: Request) -> Response:
        report = getattr(request.app.state, "compatibility_report", None)
        body = report.as_markdown() if report is not None else ""
        return Response(body, media_type="text/markdown")

    @app.get("/admin/compatibility.html", include_in_schema=False, name="admin:compatibility.html")
    async def compatibility_report_html(request: Request) -> Response:
        report = getattr(request.app.state, "compatibility_report", None)
        body = report.as_html() if report is not None else ""
        return Response(body, media_type="text/html")
