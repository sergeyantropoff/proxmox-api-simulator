"""Base external error representation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """A safe error intended for the Proxmox-compatible boundary."""

    def __init__(
        self, status_code: int, message: str, errors: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.errors = errors


class ContractValidationError(ApiError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(400, "parameter verification failed", errors)


async def api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise TypeError("api_error_handler received an incompatible exception")
    body: dict[str, Any] = {"data": None, "message": exc.message}
    if exc.errors is not None:
        body["errors"] = exc.errors
    return JSONResponse(status_code=exc.status_code, content=body)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log internal failures and return a stable non-FastAPI error envelope."""

    logger.exception(
        "unhandled request error",
        extra={"request_id": getattr(request.state, "request_id", None), "path": request.url.path},
    )
    body: dict[str, Any] = {
        "data": None,
        "errors": {"internal": "internal server error"},
    }
    return JSONResponse(status_code=500, content=body)
