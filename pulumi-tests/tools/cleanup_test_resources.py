#!/usr/bin/env python3
"""Delete leftover test guests whose names start with the configured prefix."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "pulumi"))

from pvelib.api import Pve  # noqa: E402


def main() -> int:
    prefix = os.environ.get("TEST_RESOURCE_PREFIX", "hx")
    deleted = 0
    with Pve() as pve:
        for kind, delete in (
            ("qemu", pve.delete_vm),
            ("lxc", pve.delete_lxc),
        ):
            items = pve.req("GET", f"/nodes/{pve.node}/{kind}")
            if not isinstance(items, list):
                continue
            for item in items:
                name = str(item.get("name") or item.get("hostname") or "")
                vmid = int(item["vmid"])
                if not name.startswith(prefix):
                    continue
                try:
                    delete(vmid)
                    deleted += 1
                    print(f"deleted {kind} vmid={vmid} name={name}")
                except Exception as exc:  # noqa: BLE001
                    print(f"skip {kind} vmid={vmid}: {exc}", file=sys.stderr)
    print(f"cleanup complete: deleted={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
