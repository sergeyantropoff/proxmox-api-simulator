"""Simulation clock behavior."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.simulation.clock import AcceleratedClock, ManualClock


async def test_manual_clock_releases_sleep_only_after_advance() -> None:
    clock = ManualClock(datetime(2026, 1, 1, tzinfo=UTC))
    sleeper = asyncio.create_task(clock.sleep(10))
    await asyncio.sleep(0)
    assert not sleeper.done()

    await clock.advance(9)
    assert not sleeper.done()
    await clock.advance(1)
    await sleeper
    assert await clock.now() == datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)


def test_clocks_reject_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        AcceleratedClock(0)
    with pytest.raises(ValueError):
        ManualClock(datetime(2026, 1, 1))
