"""SemVer helpers."""

from __future__ import annotations

from app.version import get_app_version, get_app_version_label, parse_version


def test_get_app_version_reads_version_file() -> None:
    version = get_app_version()
    major, minor, patch = parse_version(version)
    assert major >= 0
    assert minor >= 0
    assert patch >= 0
    assert get_app_version_label() == f"v{version}"
