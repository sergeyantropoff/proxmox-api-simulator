"""Durable full-surface verified ledger for bundled Proxmox majors 6-9.

These tests stay offline (no TLS gateway). When a new contract snapshot is
imported, regenerate ledgers with ``make evidence`` and commit the updated
``evidence/pve-*.json`` files so this suite stays green.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.evidence_gen import generate_all
from app.main import create_app
from tests.unit.test_health import FakeDatabase

_BUNDLED_9 = Path(
    "contracts/e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1/snapshot.json"
)
_EVIDENCE_9 = Path("evidence/pve-9.2.3.json")
_MAJORS = (6, 7, 8, 9)


def _app() -> FastAPI:
    settings = Settings(
        contract_snapshot=_BUNDLED_9,
        compatibility_evidence=_EVIDENCE_9,
    )
    return create_app(
        settings=settings,
        database_factory=lambda _settings: FakeDatabase(True),
        worker_factories=(),
    )


@pytest.mark.parametrize("major", _MAJORS)
async def test_hot_swap_reports_full_verified_surface(major: int) -> None:
    app = _app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            applied = await client.post("/ui/api/contract/apply", params={"major": major})
            assert applied.status_code == 200
            assert applied.json()["ok"] is True

            report = await client.get("/admin/compatibility")
            assert report.status_code == 200
            body = report.json()
            declared = body["total_declared"]
            levels = body["levels"]
            assert declared > 0
            assert levels["implemented"]["count"] == declared
            assert levels["observed"]["count"] == declared
            assert levels["verified"]["count"] == declared
            assert levels["verified"]["score"] == pytest.approx(1.0)
            for name, dimension in (body.get("dimensions") or {}).items():
                assert dimension["count"] == declared, name
                assert dimension["score"] == pytest.approx(1.0), name
            assert len(body.get("classifications", {}).get("fully_compatible") or []) == declared


def test_committed_evidence_matches_generator(tmp_path: Path) -> None:
    written = generate_all(out_dir=tmp_path)
    assert set(written) == {"6.4-15", "7.4-16", "8.4.5", "9.2.3"}
    for version, generated in written.items():
        committed = Path("evidence") / f"pve-{version}.json"
        assert committed.is_file(), f"missing committed ledger for {version}"
        assert generated.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8")
