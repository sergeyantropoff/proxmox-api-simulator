from __future__ import annotations

from typing import Self

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.pool import Database
from app.main import create_app


class FakeDatabase:
    def __init__(self, ready: bool) -> None:
        self.ready = ready
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def is_ready(self) -> bool:
        return self.ready

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()


@pytest.mark.parametrize(("database_ready", "status_code"), [(True, 200), (False, 503)])
async def test_health_endpoints(database_ready: bool, status_code: int) -> None:
    database = FakeDatabase(database_ready)

    def factory(settings: Settings) -> Database:
        del settings
        return database

    application = create_app(Settings(), factory)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready", headers={"X-Request-ID": "test-request"})

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == status_code
    assert ready.headers["X-Request-ID"] == "test-request"
    assert database.connected
    assert database.closed
