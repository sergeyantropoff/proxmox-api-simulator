"""SemVer source of truth: VERSION file (synced to pyproject + Helm)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
_PROJECT_ROOT = _VERSION_FILE.parent
_PYPROJECT_FILE = _PROJECT_ROOT / "pyproject.toml"
_CHART_FILE = _PROJECT_ROOT / "helm" / "proxmox-api-simulator" / "Chart.yaml"
_VALUES_FILE = _PROJECT_ROOT / "helm" / "proxmox-api-simulator" / "values.yaml"
_DEFAULT_VERSION = "0.1.0"
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _read_version_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if _VERSION_RE.match(text):
        return text
    return None


@lru_cache
def get_app_version() -> str:
    for path in (
        Path("/app/VERSION"),
        _VERSION_FILE,
        Path.cwd() / "VERSION",
    ):
        found = _read_version_file(path)
        if found:
            return found
    try:
        from importlib.metadata import version

        meta = version("proxmox-api-simulator")
        if _VERSION_RE.match(meta):
            return meta
    except Exception:
        pass
    return _DEFAULT_VERSION


def get_app_version_label() -> str:
    clear_version_cache()
    return f"v{get_app_version()}"


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid semantic version: {value!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def format_version(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def clear_version_cache() -> None:
    get_app_version.cache_clear()


def write_project_version(version: str) -> None:
    parse_version(version)
    _VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")

    pyproject = _PYPROJECT_FILE.read_text(encoding="utf-8")
    pyproject, count = re.subn(
        r'^version = ".*"$',
        f'version = "{version}"',
        pyproject,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise RuntimeError("Failed to update pyproject.toml version")
    _PYPROJECT_FILE.write_text(pyproject, encoding="utf-8")

    chart = _CHART_FILE.read_text(encoding="utf-8")
    chart, chart_count = re.subn(
        r"^version: .*$",
        f"version: {version}",
        chart,
        count=1,
        flags=re.MULTILINE,
    )
    chart, app_count = re.subn(
        r'^appVersion: ".*"$',
        f'appVersion: "{version}"',
        chart,
        count=1,
        flags=re.MULTILINE,
    )
    if chart_count != 1 or app_count != 1:
        raise RuntimeError("Failed to update Chart.yaml version")
    _CHART_FILE.write_text(chart, encoding="utf-8")

    values = _VALUES_FILE.read_text(encoding="utf-8")
    values, values_count = re.subn(
        r'^(\s*tag:\s*).*$',
        rf'\1"{version}"',
        values,
        count=1,
        flags=re.MULTILINE,
    )
    if values_count != 1:
        raise RuntimeError("Failed to update helm values.yaml image.tag")
    _VALUES_FILE.write_text(values, encoding="utf-8")

    clear_version_cache()


def bump_patch_version() -> str:
    major, minor, patch = parse_version(get_app_version())
    version = format_version(major, minor, patch + 1)
    write_project_version(version)
    return version


def bump_minor_version() -> str:
    major, minor, patch = parse_version(get_app_version())
    version = format_version(major, minor + 1, 0)
    write_project_version(version)
    return version
