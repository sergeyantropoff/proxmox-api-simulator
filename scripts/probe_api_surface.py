#!/usr/bin/env python3
"""CLI entrypoint for the CI API surface probe."""

from __future__ import annotations

import asyncio

from app.surface_probe import main

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
