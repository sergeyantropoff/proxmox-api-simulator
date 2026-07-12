"""Injectable simulation clocks; task leases deliberately do not use these."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    async def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class RealClock:
    async def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class AcceleratedClock:
    def __init__(self, scale: float) -> None:
        if scale <= 0:
            raise ValueError("clock scale must be positive")
        self._scale = scale

    async def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds / self._scale)


class ManualClock:
    def __init__(self, initial: datetime) -> None:
        if initial.tzinfo is None:
            raise ValueError("manual clock requires timezone-aware time")
        self._now = initial
        self._condition = asyncio.Condition()

    async def now(self) -> datetime:
        async with self._condition:
            return self._now

    async def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep duration cannot be negative")
        async with self._condition:
            target = self._now + timedelta(seconds=seconds)
            await self._condition.wait_for(lambda: self._now >= target)

    async def advance(self, seconds: float) -> datetime:
        if seconds < 0:
            raise ValueError("clock cannot move backwards")
        async with self._condition:
            self._now += timedelta(seconds=seconds)
            self._condition.notify_all()
            return self._now
