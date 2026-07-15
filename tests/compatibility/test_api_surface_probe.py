"""CI gate: every declared method on majors 6-9 is callable without critical failures.

Critical = HTTP 501, server 5xx, unhandled exceptions, or emulator-limitation
strings. Synthetic 4xx (missing object / incomplete payload) are allowed.
Requires PostgreSQL via ``TEST_DATABASE_URL``.
"""

from __future__ import annotations

import os

import pytest

from app.surface_probe import run_probe

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required"),
]


@pytest.mark.asyncio
async def test_all_majors_surface_has_zero_critical_failures() -> None:
    results = await run_probe()
    assert len(results) == 4
    for item in results:
        version = item["version"]
        declared = item["declared"]
        assert item["implemented"] == declared, version
        assert item["verified"] == declared, version
        assert item["dimensions_min"] == declared, version
        assert item["failure_count"] == 0, f"{version} critical failures: {item.get('failures')}"
        by_verb = item["by_verb"]
        for verb, buckets in by_verb.items():
            assert buckets.get("unimplemented_501", 0) == 0, (version, verb, buckets)
            assert buckets.get("unsupported_message", 0) == 0, (version, verb, buckets)
            assert buckets.get("server_5xx", 0) == 0, (version, verb, buckets)
            assert buckets.get("exception", 0) == 0, (version, verb, buckets)
