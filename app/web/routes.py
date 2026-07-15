"""Browser console for exercising the simulator API."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from asyncpg import Pool  # type: ignore[import-untyped]
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.registry import HandlerRegistry
from app.config import Settings
from app.contracts.runtime import apply_runtime_contract_locked, contract_store_root
from app.contracts.source import SourceError
from app.db.pool import AsyncpgDatabase
from app.dependencies import get_database
from app.simulation.seed import apply_seed, build_profile, simulation_state_summary
from app.web.assets import console_html
from app.web.compatibility_catalog import compatibility_payload
from app.web.contract_catalog import catalog_payload, list_majors, load_snapshot, method_payload

router = APIRouter(tags=["Simulator"])


@router.get("/", response_class=HTMLResponse, include_in_schema=True)
async def console() -> HTMLResponse:
    """Interactive API console and cluster overview."""

    return HTMLResponse(
        console_html(),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/ui/api/versions", include_in_schema=False)
async def ui_versions(request: Request) -> JSONResponse:
    settings = _settings(request)
    runtime_version = _runtime_version(request)
    return JSONResponse(list_majors(runtime_version=runtime_version, settings=settings))


@router.get("/ui/api/catalog", include_in_schema=False)
async def ui_catalog(
    request: Request,
    major: Annotated[int, Query(ge=6, le=9)],
) -> JSONResponse:
    settings = _settings(request)
    try:
        snapshot = await load_snapshot(major, _store_root(request), settings=settings)
    except SourceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    implemented = getattr(request.app.state, "implemented_methods", None)
    return JSONResponse(
        catalog_payload(snapshot, major, implemented_methods=implemented, settings=settings)
    )


@router.get("/ui/api/method", include_in_schema=False)
async def ui_method(
    request: Request,
    major: Annotated[int, Query(ge=6, le=9)],
    path: Annotated[str, Query(min_length=1)],
    verb: Annotated[str, Query(min_length=1)],
) -> JSONResponse:
    settings = _settings(request)
    try:
        snapshot = await load_snapshot(major, _store_root(request), settings=settings)
    except SourceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    runtime_version = _runtime_version(request)
    implemented = getattr(request.app.state, "implemented_methods", None)
    try:
        payload = method_payload(
            snapshot,
            major=major,
            path=path,
            verb=verb,
            runtime_version=runtime_version,
            implemented_methods=implemented,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"unknown contract method: {error}") from error
    return JSONResponse(payload)


@router.get("/ui/api/compatibility", include_in_schema=False)
async def ui_compatibility(
    request: Request,
    major: Annotated[int, Query(ge=6, le=9)],
) -> JSONResponse:
    settings = _settings(request)
    try:
        snapshot = await load_snapshot(major, _store_root(request), settings=settings)
    except SourceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    implemented = getattr(request.app.state, "implemented_methods", None)
    runtime_report = getattr(request.app.state, "compatibility_report", None)
    runtime_version = _runtime_version(request)
    return JSONResponse(
        compatibility_payload(
            snapshot,
            major,
            implemented_methods=implemented,
            runtime_report=runtime_report,
            runtime_version=runtime_version,
            settings=settings,
        )
    )


@router.post("/ui/api/contract/apply", include_in_schema=False)
async def ui_contract_apply(
    request: Request,
    major: Annotated[int, Query(ge=6, le=9)],
) -> JSONResponse:
    """Hot-swap the in-memory runtime contract to a catalog major (memory-only)."""

    settings = _settings(request)
    handlers = getattr(request.app.state, "handlers", None)
    if (
        settings is None
        or settings.contract_snapshot is None
        or not isinstance(handlers, HandlerRegistry)
    ):
        raise HTTPException(status_code=503, detail="runtime contract is not available")
    store_root = _store_root(request)
    try:
        snapshot = await load_snapshot(major, store_root, settings=settings)
    except SourceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    await apply_runtime_contract_locked(
        request.app,
        snapshot,
        handlers=handlers,
        store_root=store_root,
        fallback=settings.contract_fallback,
        settings=settings,
        require_evidence_match=False,
        register_admin=True,
    )
    method_count = sum(len(path.methods) for path in snapshot.paths)
    return JSONResponse(
        {
            "ok": True,
            "major": major,
            "runtime_version": snapshot.source_version,
            "path_count": len(snapshot.paths),
            "method_count": method_count,
        }
    )


@router.get("/ui/api/demo/state", include_in_schema=False)
async def ui_demo_state(request: Request) -> JSONResponse:
    pool = _database_pool(request)
    async with pool.acquire() as connection:
        return JSONResponse(await simulation_state_summary(connection))


@router.post("/ui/api/demo/load", include_in_schema=False)
async def ui_demo_load(request: Request) -> JSONResponse:
    pool = _database_pool(request)
    profile = build_profile("demo-cluster")
    async with pool.acquire() as connection:
        await apply_seed(connection, profile)
        summary = await simulation_state_summary(connection)
    return JSONResponse({"ok": True, "profile": profile.name, "summary": summary})


@router.post("/ui/api/demo/unload", include_in_schema=False)
async def ui_demo_unload(request: Request) -> JSONResponse:
    """Reset to minimal seed, wiping API-created state first."""
    pool = _database_pool(request)
    profile = build_profile("minimal")
    try:
        async with pool.acquire() as connection:
            await apply_seed(connection, profile)
            summary = await simulation_state_summary(connection)
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=f"failed to remove demo data: {error}"
        ) from error
    return JSONResponse({"ok": True, "profile": profile.name, "summary": summary})


def _database_pool(request: Request) -> Pool:
    database = get_database(request)
    if not isinstance(database, AsyncpgDatabase):
        raise HTTPException(status_code=503, detail="database is not available")
    return database.pool


def _settings(request: Request) -> Settings | None:
    return getattr(request.app.state, "settings", None)


def _runtime_version(request: Request) -> str | None:
    active = getattr(request.app.state, "runtime_source_version", None)
    if isinstance(active, str) and active:
        return active
    settings = _settings(request)
    if settings is None or settings.contract_snapshot is None:
        return None
    from app.contracts.model import Snapshot

    snapshot = Snapshot.model_validate_json(settings.contract_snapshot.read_bytes())
    return snapshot.source_version


def _store_root(request: Request) -> Path:
    stored = getattr(request.app.state, "contract_store_root", None)
    if isinstance(stored, Path):
        return stored
    settings = _settings(request)
    if settings is not None:
        return contract_store_root(settings)
    return Path("contracts")
