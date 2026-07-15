"""Ceph semantic handlers with durable cluster/node state."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import (
    database,
    node_metadata,
    require_node,
    save_node_metadata,
    state,
    subdirs,
    values,
)
from app.simulation.seed import CLUSTER_ID

DEFAULT_CLUSTER_CEPH = {
    "initialized": True,
    "config": {
        "network": "10.10.10.0/24",
        "cluster-network": "10.10.10.0/24",
        "size": 3,
        "min_size": 2,
        "pg_bits": 7,
    },
    "cfg_db": [
        {"section": "global", "name": "auth_client_required", "value": "cephx"},
        {"section": "global", "name": "fsid", "value": "pve-simulator-fsid"},
    ],
    "cfg_raw": "[global]\nfsid = pve-simulator-fsid\nauth_client_required = cephx\n",
    "cfg_values": {},
    "pools": {
        "rbd": {
            "pool": "rbd",
            "size": 3,
            "min_size": 2,
            "pg_num": 128,
            "application": "rbd",
            "crush_rule": "replicated_rule",
        }
    },
    "fs": {},
    "rules": [{"name": "replicated_rule", "id": 0}],
    "crush": "device 0 osd.0 class hdd\n",
    "running": True,
}


async def _load_cluster_ceph(request: Request) -> dict[str, Any]:
    row = await database(request).pool.fetchrow(
        "SELECT metadata FROM clusters WHERE id=$1",
        CLUSTER_ID,
    )
    metadata = state(row["metadata"]) if row is not None else {}
    ceph = metadata.get("ceph")
    if not isinstance(ceph, dict) or not ceph:
        return dict(DEFAULT_CLUSTER_CEPH)
    merged = dict(DEFAULT_CLUSTER_CEPH)
    merged.update(ceph)
    for key in ("config", "pools", "fs", "cfg_values"):
        if not isinstance(merged.get(key), dict):
            merged[key] = dict(cast(dict[str, Any], DEFAULT_CLUSTER_CEPH[key]))
    return merged


async def _save_cluster_ceph(request: Request, ceph: dict[str, Any]) -> None:
    await database(request).pool.execute(
        """UPDATE clusters SET metadata = jsonb_set(
            COALESCE(metadata, '{}'::jsonb), '{ceph}', $2::jsonb, true
        ), updated_at=now() WHERE id=$1""",
        CLUSTER_ID,
        json.dumps(ceph, sort_keys=True),
    )


async def _load_node_ceph(request: Request, node: str) -> dict[str, Any]:
    metadata = await node_metadata(request, node)
    ops = metadata.setdefault("ops", {})
    ceph = ops.setdefault(
        "ceph",
        {
            "mds": {},
            "mgr": {},
            "mon": {f"{node}": {"name": node, "addr": f"{node}.local:6789", "rank": 0}},
            "log": [{"t": 1_700_000_000, "n": 0, "line": "ceph simulator ready"}],
        },
    )
    if not isinstance(ceph, dict):
        ceph = {
            "mds": {},
            "mgr": {},
            "mon": {},
            "log": [],
        }
        ops["ceph"] = ceph
    ceph.setdefault("mds", {})
    ceph.setdefault("mgr", {})
    ceph.setdefault("mon", {})
    ceph.setdefault("log", [])
    return ceph


async def _save_node_ceph(request: Request, node: str, ceph: dict[str, Any]) -> None:
    metadata = await node_metadata(request, node)
    ops = metadata.setdefault("ops", {})
    ops["ceph"] = ceph
    await save_node_metadata(request, node, metadata)


def _upid(node: str, kind: str) -> str:
    return f"UPID:{node}:{secrets.token_hex(4)}:{kind}:root@pam:"


async def _osd_row(request: Request, node: str, osdid: str) -> Any:
    row = await database(request).pool.fetchrow(
        """SELECT r.id, r.external_id, r.state
        FROM resources r JOIN nodes n ON n.id=r.node_id
        WHERE n.name=$1 AND r.kind='ceph-osd'
          AND (r.external_id=$2 OR r.external_id=$3)""",
        node,
        osdid,
        f"osd.{osdid}",
    )
    if row is None:
        raise ApiError(404, "OSD does not exist")
    return row


def register_ceph_handlers(registry: HandlerRegistry) -> None:
    async def ceph_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        return subdirs(
            "cfg",
            "cmd-safety",
            "crush",
            "fs",
            "init",
            "log",
            "mds",
            "mgr",
            "mon",
            "osd",
            "pool",
            "restart",
            "rules",
            "start",
            "status",
            "stop",
        )

    async def cfg_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("db", "raw", "value")

    async def cfg_db(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        ceph = await _load_cluster_ceph(request)
        return list(ceph.get("cfg_db") or [])

    async def cfg_raw(request: Request, inputs: dict[str, Any]) -> str:
        await require_node(request, str(values(inputs)["node"]))
        ceph = await _load_cluster_ceph(request)
        return str(ceph.get("cfg_raw") or "")

    async def cfg_value(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        ceph = await _load_cluster_ceph(request)
        keys = [item.strip() for item in str(payload.get("config-keys") or "").split(",") if item]
        stored = ceph.setdefault("cfg_values", {})
        result = {key: stored.get(key, "") for key in keys} if keys else dict(stored)
        await _save_cluster_ceph(request, ceph)
        return result

    async def crush(request: Request, inputs: dict[str, Any]) -> str:
        await require_node(request, str(values(inputs)["node"]))
        ceph = await _load_cluster_ceph(request)
        return str(ceph.get("crush") or "")

    async def rules(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        ceph = await _load_cluster_ceph(request)
        return list(ceph.get("rules") or [])

    async def log(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ceph = await _load_node_ceph(request, node)
        entries = list(ceph.get("log") or [])
        start = int(values(inputs).get("start") or 0)
        limit = int(values(inputs).get("limit") or 50)
        return entries[start : start + limit]

    async def cmd_safety(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        return {
            "safe": 1,
            "action": payload.get("action"),
            "service": payload.get("service"),
            "id": payload.get("id"),
        }

    async def init(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ceph = await _load_cluster_ceph(request)
        config = ceph.setdefault("config", {})
        for key in (
            "network",
            "cluster-network",
            "size",
            "min_size",
            "pg_bits",
            "disable_cephx",
        ):
            if key in payload:
                config[key] = payload[key]
        ceph["initialized"] = True
        await _save_cluster_ceph(request, ceph)
        node_ceph = await _load_node_ceph(request, node)
        node_ceph.setdefault("mon", {})[node] = {
            "name": node,
            "addr": f"{node}.local:6789",
            "rank": 0,
        }
        await _save_node_ceph(request, node, node_ceph)

    async def status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        return await cluster_ceph_status(request, inputs)

    async def start(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ceph = await _load_cluster_ceph(request)
        ceph["running"] = True
        ceph["last_service_action"] = {
            "action": "start",
            "service": payload.get("service"),
            "node": node,
        }
        await _save_cluster_ceph(request, ceph)
        return _upid(node, "cephstart")

    async def stop(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ceph = await _load_cluster_ceph(request)
        ceph["running"] = False
        ceph["last_service_action"] = {
            "action": "stop",
            "service": payload.get("service"),
            "node": node,
        }
        await _save_cluster_ceph(request, ceph)
        return _upid(node, "cephstop")

    async def restart(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ceph = await _load_cluster_ceph(request)
        ceph["running"] = True
        ceph["last_service_action"] = {
            "action": "restart",
            "service": payload.get("service"),
            "node": node,
        }
        await _save_cluster_ceph(request, ceph)
        return _upid(node, "cephrestart")

    async def pool_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        ceph = await _load_cluster_ceph(request)
        pools = ceph.get("pools") or {}
        return [dict(item) for _, item in sorted(pools.items()) if isinstance(item, dict)]

    async def pool_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        name = str(payload["name"])
        ceph = await _load_cluster_ceph(request)
        pools = ceph.setdefault("pools", {})
        if name in pools:
            raise ApiError(400, f"pool '{name}' already exists")
        pools[name] = {
            "pool": name,
            "size": int(payload.get("size") or 3),
            "min_size": int(payload.get("min_size") or 2),
            "pg_num": int(payload.get("pg_num") or 128),
            "application": str(payload.get("application") or "rbd"),
            "crush_rule": str(payload.get("crush_rule") or "replicated_rule"),
            "pg_autoscale_mode": payload.get("pg_autoscale_mode", "warn"),
            "target_size": payload.get("target_size"),
        }
        await _save_cluster_ceph(request, ceph)
        return _upid(node, "cephcreatepool")

    async def pool_get(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        name = str(payload["name"])
        ceph = await _load_cluster_ceph(request)
        pool = (ceph.get("pools") or {}).get(name)
        if not isinstance(pool, dict):
            raise ApiError(404, "pool does not exist")
        return [dict(pool)]

    async def pool_update(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        name = str(payload["name"])
        ceph = await _load_cluster_ceph(request)
        pools = ceph.setdefault("pools", {})
        if name not in pools or not isinstance(pools[name], dict):
            raise ApiError(404, "pool does not exist")
        current = dict(pools[name])
        for key in (
            "application",
            "crush_rule",
            "min_size",
            "pg_autoscale_mode",
            "pg_num",
            "pg_num_min",
            "size",
            "target_size",
            "target_size_ratio",
        ):
            if key in payload:
                current[key] = payload[key]
        pools[name] = current
        await _save_cluster_ceph(request, ceph)
        return _upid(node, "cephsetpool")

    async def pool_delete(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        name = str(payload["name"])
        ceph = await _load_cluster_ceph(request)
        pools = ceph.setdefault("pools", {})
        if name not in pools:
            raise ApiError(404, "pool does not exist")
        del pools[name]
        await _save_cluster_ceph(request, ceph)
        return _upid(node, "cephdestroypool")

    async def pool_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        name = str(payload["name"])
        ceph = await _load_cluster_ceph(request)
        pool = (ceph.get("pools") or {}).get(name)
        if not isinstance(pool, dict):
            raise ApiError(404, "pool does not exist")
        return {
            **pool,
            "pg_num": pool.get("pg_num", 128),
            "bytes_used": 0,
            "percent_used": 0.0,
            "healthy": True,
        }

    async def fs_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        ceph = await _load_cluster_ceph(request)
        return [dict(item) for _, item in sorted((ceph.get("fs") or {}).items())]

    async def fs_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        name = str(payload["name"])
        ceph = await _load_cluster_ceph(request)
        filesystems = ceph.setdefault("fs", {})
        if name in filesystems:
            raise ApiError(400, f"fs '{name}' already exists")
        filesystems[name] = {
            "name": name,
            "metadata": f"{name}_meta",
            "data": f"{name}_data",
            "pg_num": int(payload.get("pg_num") or 32),
        }
        await _save_cluster_ceph(request, ceph)
        return _upid(node, "cephcreatefs")

    async def fs_delete(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        name = str(payload["name"])
        ceph = await _load_cluster_ceph(request)
        filesystems = ceph.setdefault("fs", {})
        if name not in filesystems:
            raise ApiError(404, "fs does not exist")
        del filesystems[name]
        await _save_cluster_ceph(request, ceph)
        return _upid(node, "cephdestroyfs")

    async def mds_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ceph = await _load_node_ceph(request, node)
        return [
            {"name": name, **data}
            for name, data in sorted((ceph.get("mds") or {}).items())
            if isinstance(data, dict)
        ]

    async def mds_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        name = str(payload["name"])
        ceph = await _load_node_ceph(request, node)
        mds = ceph.setdefault("mds", {})
        if name in mds:
            raise ApiError(400, f"mds '{name}' already exists")
        mds[name] = {
            "name": name,
            "state": "up:active",
            "hotstandby": int(bool(payload.get("hotstandby"))),
        }
        await _save_node_ceph(request, node, ceph)
        return _upid(node, "cephcreatemds")

    async def mds_delete(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        name = str(payload["name"])
        ceph = await _load_node_ceph(request, node)
        mds = ceph.setdefault("mds", {})
        if name not in mds:
            raise ApiError(404, "mds does not exist")
        del mds[name]
        await _save_node_ceph(request, node, ceph)
        return _upid(node, "cephdestroymds")

    async def mgr_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ceph = await _load_node_ceph(request, node)
        return [
            {"name": name, **data}
            for name, data in sorted((ceph.get("mgr") or {}).items())
            if isinstance(data, dict)
        ]

    async def mgr_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        mgr_id = str(payload["id"])
        ceph = await _load_node_ceph(request, node)
        mgr = ceph.setdefault("mgr", {})
        if mgr_id in mgr:
            raise ApiError(400, f"mgr '{mgr_id}' already exists")
        mgr[mgr_id] = {"name": mgr_id, "state": "active"}
        await _save_node_ceph(request, node, ceph)
        return _upid(node, "cephcreatemgr")

    async def mgr_delete(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        mgr_id = str(payload["id"])
        ceph = await _load_node_ceph(request, node)
        mgr = ceph.setdefault("mgr", {})
        if mgr_id not in mgr:
            raise ApiError(404, "mgr does not exist")
        del mgr[mgr_id]
        await _save_node_ceph(request, node, ceph)
        return _upid(node, "cephdestroymgr")

    async def mon_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ceph = await _load_node_ceph(request, node)
        return [
            {"name": name, **data}
            for name, data in sorted((ceph.get("mon") or {}).items())
            if isinstance(data, dict)
        ]

    async def mon_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        monid = str(payload["monid"])
        ceph = await _load_node_ceph(request, node)
        mons = ceph.setdefault("mon", {})
        if monid in mons:
            raise ApiError(400, f"mon '{monid}' already exists")
        mons[monid] = {
            "name": monid,
            "addr": str(payload.get("mon-address") or f"{node}.local:6789"),
            "rank": len(mons),
        }
        await _save_node_ceph(request, node, ceph)
        return _upid(node, "cephcreatemon")

    async def mon_delete(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        monid = str(payload["monid"])
        ceph = await _load_node_ceph(request, node)
        mons = ceph.setdefault("mon", {})
        if monid not in mons:
            raise ApiError(404, "mon does not exist")
        del mons[monid]
        await _save_node_ceph(request, node, ceph)
        return _upid(node, "cephdestroymon")

    async def osd_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        rows = await database(request).pool.fetch(
            """SELECT r.external_id, r.state
            FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='ceph-osd'
            ORDER BY r.external_id""",
            node,
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = state(row["state"])
            osd_id = payload.get("osd_id", row["external_id"])
            result.append(
                {
                    "osd": int(osd_id) if str(osd_id).isdigit() else osd_id,
                    "status": payload.get("status", "up"),
                    "in": 1 if payload.get("in", True) else 0,
                    "weight": payload.get("weight", 1.0),
                    "device_class": payload.get("device_class", "hdd"),
                }
            )
        return result

    async def osd_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        next_id = await database(request).pool.fetchval(
            """SELECT COALESCE(
                MAX(NULLIF(regexp_replace(external_id, '\\D', '', 'g'), '')::int),
                -1
            ) + 1
            FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='ceph-osd'""",
            node,
        )
        osd_id = int(next_id or 0)
        external_id = f"osd.{osd_id}"
        node_id = await database(request).pool.fetchval(
            "SELECT id FROM nodes WHERE name=$1",
            node,
        )
        osd_state = {
            "osd_id": osd_id,
            "status": "up",
            "in": True,
            "weight": 1.0,
            "device_class": payload.get("crush-device-class") or "hdd",
            "dev": payload.get("dev"),
            "size_bytes": 0,
            "used_bytes": 0,
        }
        await database(request).pool.execute(
            """INSERT INTO resources(id, node_id, kind, external_id, state)
            VALUES(gen_random_uuid(), $1, 'ceph-osd', $2, $3::jsonb)""",
            node_id,
            external_id,
            json.dumps(osd_state, sort_keys=True),
        )
        return _upid(node, "cephcreateosd")

    async def osd_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        osdid = str(values(inputs)["osdid"])
        await require_node(request, node)
        row = await _osd_row(request, node, osdid)
        payload = state(row["state"])
        return {
            "osd": int(osdid) if osdid.isdigit() else osdid,
            "status": payload.get("status", "up"),
            "in": 1 if payload.get("in", True) else 0,
            "weight": payload.get("weight", 1.0),
            "size": payload.get("size_bytes", 0),
            "used": payload.get("used_bytes", 0),
            "device_class": payload.get("device_class", "hdd"),
        }

    async def osd_delete(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        osdid = str(payload["osdid"])
        await require_node(request, node)
        row = await _osd_row(request, node, osdid)
        await database(request).pool.execute("DELETE FROM resources WHERE id=$1", row["id"])
        return _upid(node, "cephdestroyosd")

    async def osd_in(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        osdid = str(payload["osdid"])
        await require_node(request, node)
        row = await _osd_row(request, node, osdid)
        current = state(row["state"])
        current["in"] = True
        await database(request).pool.execute(
            "UPDATE resources SET state=$2::jsonb, version=version+1 WHERE id=$1",
            row["id"],
            json.dumps(current, sort_keys=True),
        )

    async def osd_out(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        osdid = str(payload["osdid"])
        await require_node(request, node)
        row = await _osd_row(request, node, osdid)
        current = state(row["state"])
        current["in"] = False
        await database(request).pool.execute(
            "UPDATE resources SET state=$2::jsonb, version=version+1 WHERE id=$1",
            row["id"],
            json.dumps(current, sort_keys=True),
        )

    async def osd_scrub(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        osdid = str(payload["osdid"])
        await require_node(request, node)
        row = await _osd_row(request, node, osdid)
        current = state(row["state"])
        current["last_scrub"] = {
            "deep": int(bool(payload.get("deep"))),
            "token": secrets.token_hex(4),
        }
        await database(request).pool.execute(
            "UPDATE resources SET state=$2::jsonb, version=version+1 WHERE id=$1",
            row["id"],
            json.dumps(current, sort_keys=True),
        )

    async def osd_lv_info(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        node = str(payload["node"])
        osdid = str(payload["osdid"])
        await require_node(request, node)
        row = await _osd_row(request, node, osdid)
        current = state(row["state"])
        return {
            "lv_name": f"osd-block-{osdid}",
            "lv_path": f"/dev/ceph/{osdid}",
            "lv_size": current.get("size_bytes", 0),
            "type": payload.get("type") or "block",
        }

    async def osd_metadata(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        node = str(payload["node"])
        osdid = str(payload["osdid"])
        await require_node(request, node)
        row = await _osd_row(request, node, osdid)
        current = state(row["state"])
        return {
            "osd": {
                "id": int(osdid) if osdid.isdigit() else osdid,
                "uuid": current.get("uuid") or f"osd-uuid-{osdid}",
                "device_class": current.get("device_class", "hdd"),
            },
            "devices": [{"dev": current.get("dev") or f"/dev/sd{osdid}"}],
        }

    async def cluster_ceph_status(_request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        row = await database(_request).pool.fetchrow(
            """SELECT capacity_bytes, used_bytes FROM storages
            WHERE storage_type='ceph' ORDER BY storage_id LIMIT 1"""
        )
        total = int(row["capacity_bytes"] or 0) if row is not None else 0
        used = int(row["used_bytes"] or 0) if row is not None else 0
        osd_count = await database(_request).pool.fetchval(
            "SELECT count(*)::int FROM resources WHERE kind='ceph-osd'"
        )
        ceph = await _load_cluster_ceph(_request)
        return {
            "version": "17.2.7",
            "health": {"status": "HEALTH_OK" if ceph.get("running", True) else "HEALTH_WARN"},
            "osdmap": {
                "num_osds": osd_count,
                "num_up_osds": osd_count - 1,
                "num_in_osds": osd_count - 1,
            },
            "pgmap": {"bytes_used": used, "bytes_total": total},
            "fsmap": {"filesystems": list((ceph.get("fs") or {}).keys())},
        }

    base = "/nodes/{node}/ceph"
    registry.register(base, "GET", ceph_index)
    registry.register(f"{base}/cfg", "GET", cfg_index)
    registry.register(f"{base}/cfg/db", "GET", cfg_db)
    registry.register(f"{base}/cfg/raw", "GET", cfg_raw)
    registry.register(f"{base}/cfg/value", "GET", cfg_value)
    registry.register(f"{base}/cmd-safety", "GET", cmd_safety)
    registry.register(f"{base}/crush", "GET", crush)
    registry.register(f"{base}/fs", "GET", fs_list)
    registry.register(f"{base}/fs/{{name}}", "POST", fs_create)
    registry.register(f"{base}/fs/{{name}}", "DELETE", fs_delete)
    registry.register(f"{base}/init", "POST", init)
    registry.register(f"{base}/log", "GET", log)
    registry.register(f"{base}/mds", "GET", mds_list)
    registry.register(f"{base}/mds/{{name}}", "POST", mds_create)
    registry.register(f"{base}/mds/{{name}}", "DELETE", mds_delete)
    registry.register(f"{base}/mgr", "GET", mgr_list)
    registry.register(f"{base}/mgr/{{id}}", "POST", mgr_create)
    registry.register(f"{base}/mgr/{{id}}", "DELETE", mgr_delete)
    registry.register(f"{base}/mon", "GET", mon_list)
    registry.register(f"{base}/mon/{{monid}}", "POST", mon_create)
    registry.register(f"{base}/mon/{{monid}}", "DELETE", mon_delete)
    registry.register(f"{base}/osd", "GET", osd_list)
    registry.register(f"{base}/osd", "POST", osd_create)
    registry.register(f"{base}/osd/{{osdid}}", "GET", osd_get)
    registry.register(f"{base}/osd/{{osdid}}", "DELETE", osd_delete)
    registry.register(f"{base}/osd/{{osdid}}/in", "POST", osd_in)
    registry.register(f"{base}/osd/{{osdid}}/out", "POST", osd_out)
    registry.register(f"{base}/osd/{{osdid}}/scrub", "POST", osd_scrub)
    registry.register(f"{base}/osd/{{osdid}}/lv-info", "GET", osd_lv_info)
    registry.register(f"{base}/osd/{{osdid}}/metadata", "GET", osd_metadata)
    registry.register(f"{base}/pool", "GET", pool_list)
    registry.register(f"{base}/pool", "POST", pool_create)
    registry.register(f"{base}/pool/{{name}}", "GET", pool_get)
    registry.register(f"{base}/pool/{{name}}", "PUT", pool_update)
    registry.register(f"{base}/pool/{{name}}", "DELETE", pool_delete)
    registry.register(f"{base}/pool/{{name}}/status", "GET", pool_status)
    registry.register(f"{base}/rules", "GET", rules)
    registry.register(f"{base}/status", "GET", status)
    registry.register(f"{base}/start", "POST", start)
    registry.register(f"{base}/stop", "POST", stop)
    registry.register(f"{base}/restart", "POST", restart)
    registry.register("/cluster/ceph/status", "GET", cluster_ceph_status)
