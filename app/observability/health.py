"""Kubernetes-compatible health endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.db.pool import Database
from app.dependencies import get_database

router = APIRouter(prefix="/health", tags=["Simulator"])


class HealthResponse(BaseModel):
    status: str


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Report process liveness without checking dependencies."""

    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def ready(
    response: Response,
    database: Annotated[Database, Depends(get_database)],
) -> HealthResponse:
    """Report whether the required database dependency is usable."""

    if await database.is_ready():
        return HealthResponse(status="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable")
