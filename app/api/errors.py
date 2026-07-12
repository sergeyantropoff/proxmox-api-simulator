"""Base external error representation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


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
