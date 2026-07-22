"""Shared handler helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.db.pool import AsyncpgDatabase


def database(request: Request) -> AsyncpgDatabase:
    return cast(AsyncpgDatabase, request.app.state.database)


def values(inputs: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], inputs["values"])


def require_value(payload: Mapping[str, Any], key: str) -> Any:
    if key not in payload or payload[key] in {None, ""}:
        raise ApiError(400, f"parameter '{key}' is required")
    return payload[key]


def state(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        return cast(dict[str, Any], json.loads(value))
    return dict(cast(Mapping[str, Any], value))


def subdirs(*names: str) -> list[dict[str, str]]:
    return [{"subdir": name} for name in names]


_SIZE_RE = re.compile(r"^(?P<value>\d+)(?P<unit>[KMGT]?)$", re.IGNORECASE)
_UNITS = {"": 1, "K": 2**10, "M": 2**20, "G": 2**30, "T": 2**40}


def parse_size_bytes(value: str) -> int:
    match = _SIZE_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"invalid disk size: {value}")
    return int(match.group("value")) * _UNITS[match.group("unit").upper()]


def resize_size_bytes(value: str, current: int) -> int:
    if value.startswith("+"):
        return current + parse_size_bytes(value[1:])
    result = parse_size_bytes(value)
    if result < current:
        raise ValueError("shrinking disks is not supported")
    return result


def replace_disk_size(value: str, size: int) -> str:
    parts = [part for part in value.split(",") if not part.startswith("size=")]
    parts.append(f"size={size // 2**30}G" if size % 2**30 == 0 else f"size={size}")
    return ",".join(parts)


def disk_size_bytes(value: str) -> int:
    for part in value.split(","):
        if part.startswith("size="):
            return parse_size_bytes(part.removeprefix("size="))
    return 0


async def require_node(request: Request, node: str) -> None:
    exists = await database(request).pool.fetchval(
        "SELECT EXISTS(SELECT 1 FROM nodes WHERE name=$1)",
        node,
    )
    if not exists:
        raise ApiError(
            404,
            f"No such node ('{node}')",
            errors={"node": f"No such node ('{node}')"},
        )


async def cluster_metadata(request: Request) -> dict[str, Any]:
    from app.simulation.seed import CLUSTER_ID

    row = await database(request).pool.fetchrow(
        "SELECT metadata FROM clusters WHERE id=$1",
        CLUSTER_ID,
    )
    return state(row["metadata"]) if row is not None else {}


async def save_cluster_metadata(request: Request, metadata: dict[str, Any]) -> None:
    from app.simulation.seed import CLUSTER_ID

    await database(request).pool.execute(
        "UPDATE clusters SET metadata=$2::jsonb, updated_at=now() WHERE id=$1",
        CLUSTER_ID,
        json.dumps(metadata, sort_keys=True),
    )


async def node_metadata(request: Request, node: str) -> dict[str, Any]:
    row = await database(request).pool.fetchrow(
        "SELECT metadata FROM nodes WHERE name=$1",
        node,
    )
    if row is None:
        raise ApiError(
            404,
            f"No such node ('{node}')",
            errors={"node": f"No such node ('{node}')"},
        )
    return state(row["metadata"])


async def save_node_metadata(request: Request, node: str, metadata: dict[str, Any]) -> None:
    status = await database(request).pool.execute(
        "UPDATE nodes SET metadata=$2::jsonb, updated_at=now() WHERE name=$1",
        node,
        json.dumps(metadata, sort_keys=True),
    )
    if status != "UPDATE 1":
        raise ApiError(
            404,
            f"No such node ('{node}')",
            errors={"node": f"No such node ('{node}')"},
        )


def storage_payload(row: Any) -> dict[str, Any]:
    config = state(row["config"])
    content = config.get("content", [])
    if isinstance(content, list):
        content_str = ",".join(str(item) for item in content)
    else:
        content_str = str(content)
    total = int(row["capacity_bytes"] or 0)
    used = int(row["used_bytes"] or 0)
    avail = max(total - used, 0)
    storage_type = str(row["storage_type"])
    formats = config.get("formats")
    if not isinstance(formats, str) or not formats:
        formats = {
            "dir": "raw,qcow2,vmdk",
            "lvmthin": "raw",
            "rbd": "raw",
            "zfspool": "raw,subvol",
        }.get(storage_type, "raw")
    payload: dict[str, Any] = {
        "storage": str(row["storage_id"]),
        "type": storage_type,
        "shared": int(bool(row["shared"])),
        "content": content_str,
        "active": int(bool(config.get("active", True))),
        "enabled": int(bool(config.get("enabled", True))),
        "formats": formats,
        "select_existing": int(bool(config.get("select_existing", False))),
        "total": total,
        "used": used,
        "avail": avail,
    }
    if total:
        payload["used_fraction"] = used / total
    return payload
