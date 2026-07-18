"""Canonical Ceph cluster flag names (PVE /cluster/ceph/flags)."""

from __future__ import annotations

# Keep in sync with Proxmox `ceph_flags` API (majors 6-9).
CEPH_FLAG_DESCRIPTIONS: dict[str, str] = {
    "nobackfill": "Pause backfill operations",
    "nodeep-scrub": "Disable deep scrubbing",
    "nodown": "Do not mark OSDs down",
    "noin": "Do not mark OSDs in",
    "noout": "Do not mark OSDs out",
    "norebalance": "Pause rebalance",
    "norecover": "Pause recovery",
    "noscrub": "Disable scrubbing",
    "notieragent": "Pause tiering agent",
    "noup": "Do not mark OSDs up",
    "pause": "Pause I/O",
}


def default_ceph_flags(*, enabled: frozenset[str] | None = None) -> dict[str, int]:
    """Return the full flag map; unset flags are ``0`` (PVE GET → ``false``)."""

    active = enabled or frozenset()
    return {name: (1 if name in active else 0) for name in CEPH_FLAG_DESCRIPTIONS}
