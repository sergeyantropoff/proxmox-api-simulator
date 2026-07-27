#!/usr/bin/env python3
"""CLI: bump project SemVer (VERSION + pyproject + Helm chart/values)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.version import bump_minor_version, bump_patch_version  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in {"patch", "minor"}:
        print("Usage: bump_version.py patch|minor", file=sys.stderr)
        return 1
    version = bump_patch_version() if args[0] == "patch" else bump_minor_version()
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
