"""Request correlation and access logging middleware."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

RequestHandler = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a bounded request ID and log one structured completion event."""

    def __init__(self, app: object, header_name: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        supplied = request.headers.get(self._header_name, "")
        request_id = supplied if 0 < len(supplied) <= 128 else str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        response.headers[self._header_name] = request_id
        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
            },
        )
        return response
