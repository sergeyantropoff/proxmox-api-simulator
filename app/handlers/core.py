"""First read/login semantic service handlers."""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.config import Settings
from app.contracts.runtime import runtime_version_payload
from app.db.pool import AsyncpgDatabase
from app.handlers.access import register_access_handlers
from app.handlers.acme import register_acme_handlers
from app.handlers.backup import register_backup_handlers
from app.handlers.ceph import register_ceph_handlers
from app.handlers.cluster import register_cluster_handlers
from app.handlers.cluster_config import register_cluster_config_handlers
from app.handlers.cluster_extra import register_cluster_extra_handlers
from app.handlers.common import cluster_metadata, require_node, subdirs
from app.handlers.firewall import register_firewall_handlers
from app.handlers.ha import register_ha_handlers
from app.handlers.legacy_aliases import register_legacy_aliases
from app.handlers.lxc import register_lxc_handlers
from app.handlers.mapping import register_mapping_handlers
from app.handlers.nodes import register_node_ops_handlers
from app.handlers.nodes_extra import register_nodes_extra_handlers
from app.handlers.notifications import register_notifications_handlers
from app.handlers.pools import register_pool_handlers
from app.handlers.qemu import register_qemu_handlers
from app.handlers.sdn import register_sdn_handlers
from app.handlers.storage import register_storage_handlers
from app.security.auth import csrf_token, issue_ticket, verify_secret


def _database(request: Request) -> AsyncpgDatabase:
    return cast(AsyncpgDatabase, request.app.state.database)


def build_core_handlers(settings: Settings) -> HandlerRegistry:
    registry = HandlerRegistry()

    async def version(request: Request, _inputs: dict[str, Any]) -> dict[str, str]:
        return runtime_version_payload(request)

    async def login(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = cast(dict[str, Any], inputs["values"])
        username = str(values["username"])
        password = str(values["password"])
        row = await _database(request).pool.fetchrow(
            "SELECT name, password_hash FROM principals WHERE name=$1", username
        )
        if (
            row is None
            or row["password_hash"] is None
            or not verify_secret(password, str(row["password_hash"]))
        ):
            raise ApiError(401, "authentication failure")
        key = settings.ticket_signing_key.get_secret_value().encode()
        ticket = issue_ticket(username, key)
        cluster_name = await _database(request).pool.fetchval(
            "SELECT name FROM clusters ORDER BY created_at LIMIT 1"
        )
        return {
            "username": username,
            "ticket": ticket,
            "CSRFPreventionToken": csrf_token(ticket, key),
            "clustername": str(cluster_name or "pve-simulator"),
            "cap": {"vms": {"VM.Audit": 1, "VM.PowerMgmt": 1}},
        }

    async def nodes(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        from app.handlers.nodes import load_node_ops

        rows = await _database(request).pool.fetch(
            "SELECT name AS node, status FROM nodes ORDER BY name"
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            name = str(row["node"])
            ops = await load_node_ops(request, name)
            status_payload = ops.get("status")
            status_dict = dict(status_payload) if isinstance(status_payload, dict) else {}
            fingerprint = status_dict.get("ssl_fingerprint") or status_dict.get("fingerprint")
            if fingerprint in (None, "", 0) or isinstance(fingerprint, dict | list):
                from app.simulation.seed import _seed_fingerprint

                fingerprint = _seed_fingerprint(name)

            def _as_float(value: object, default: float) -> float:
                if isinstance(value, bool) or value is None or isinstance(value, dict | list):
                    return default
                try:
                    return float(str(value))
                except (TypeError, ValueError):
                    return default

            def _as_int(value: object, default: int) -> int:
                if isinstance(value, bool) or value is None or isinstance(value, dict | list):
                    return default
                try:
                    return int(float(str(value)))
                except (TypeError, ValueError):
                    return default

            item: dict[str, Any] = {
                "node": name,
                "status": str(row["status"]),
                "type": "node",
                "ssl_fingerprint": str(fingerprint),
                "cpu": _as_float(status_dict.get("cpu"), 0.0),
                "maxcpu": _as_int(status_dict.get("maxcpu"), 4),
                "mem": _as_int(status_dict.get("mem"), _as_int(status_dict.get("memory"), 0)),
                "maxmem": _as_int(status_dict.get("maxmem"), 8 * 1024**3),
                "uptime": _as_int(status_dict.get("uptime"), 0),
                "level": str(status_dict.get("level") or ""),
            }
            result.append(item)
        return result

    async def node_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        from app.handlers.nodes import load_node_ops

        node = str(cast(dict[str, Any], inputs["values"])["node"])
        row = await _database(request).pool.fetchrow(
            "SELECT name, status FROM nodes WHERE name=$1", node
        )
        if row is None:
            raise ApiError(404, "node does not exist")
        ops = await load_node_ops(request, node)
        status = ops.get("status")
        payload = dict(status) if isinstance(status, dict) else {}
        mem_used = int(payload.get("mem") or 0)
        mem_total = int(payload.get("maxmem") or 8 * 1024**3)
        memory = payload.get("memory")
        if isinstance(memory, dict):
            mem_used = int(memory.get("used") or mem_used)
            mem_total = int(memory.get("total") or mem_total)
        rootfs = payload.get("rootfs")
        if not isinstance(rootfs, dict):
            rootfs = {
                "used": int(payload.get("rootfs_used") or mem_used // 8),
                "total": int(payload.get("rootfs_total") or 100 * 1024**3),
                "avail": int(payload.get("rootfs_avail") or 80 * 1024**3),
                "free": int(payload.get("rootfs_free") or 80 * 1024**3),
            }
        cpuinfo = payload.get("cpuinfo")
        if not isinstance(cpuinfo, dict):
            cpuinfo = {
                "cpus": int(payload.get("maxcpu") or 4),
                "cores": int(payload.get("maxcpu") or 4),
                "sockets": 1,
                "model": str(payload.get("cpu_model") or "QEMU Virtual CPU"),
                "flags": "",
            }
        boot_info = payload.get("boot-info")
        if not isinstance(boot_info, dict):
            boot_info = {"mode": "efi", "secureboot": 0}
        current_kernel = payload.get("current-kernel")
        if not isinstance(current_kernel, dict):
            kversion = str(payload.get("kversion") or "6.8.12-1-pve")
            current_kernel = {
                "sysname": "Linux",
                "release": kversion,
                "version": f"#1 SMP PREEMPT_DYNAMIC {kversion}",
                "machine": "x86_64",
            }
        return {
            "status": str(row["status"]),
            "uptime": int(payload.get("uptime") or 0),
            "wait": float(payload.get("wait") or 0.0),
            "idle": float(payload.get("idle") or 0.95),
            "cpu": float(payload.get("cpu") or 0.0),
            "loadavg": list(payload.get("loadavg") or ["0.00", "0.00", "0.00"]),
            "memory": {
                "used": mem_used,
                "total": mem_total,
                "free": max(mem_total - mem_used, 0),
                "available": max(mem_total - mem_used, 0),
            },
            "rootfs": rootfs,
            "swap": payload.get("swap")
            if isinstance(payload.get("swap"), dict)
            else {"used": 0, "total": 0, "free": 0},
            "cpuinfo": cpuinfo,
            "kversion": str(payload.get("kversion") or current_kernel.get("release") or ""),
            "pveversion": str(payload.get("pveversion") or "pve-manager/9.2.3"),
            "current-kernel": current_kernel,
            "boot-info": boot_info,
        }

    async def resources(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        """Cluster-wide inventory in Proxmox ``/cluster/resources`` shape.

        Do not dump guest ``state`` / config blobs: QEMU ``cpu`` is a model
        string (e.g. ``qemu64``), while this endpoint's ``cpu`` is utilization
        (float). Bridged clients (bpg / pulumi-proxmoxve) decode strictly.
        """

        def _as_dict(raw: object) -> dict[str, Any]:
            if isinstance(raw, str):
                loaded = json.loads(raw)
                return dict(loaded) if isinstance(loaded, dict) else {}
            return dict(raw) if isinstance(raw, dict) else {}

        def _num(value: object, default: float | int) -> float | int:
            if isinstance(value, bool) or value is None or isinstance(value, dict | list):
                return default
            try:
                if isinstance(default, float):
                    return float(str(value))
                return int(float(str(value)))
            except (TypeError, ValueError):
                return default

        def _memory_bytes(state: dict[str, Any]) -> int:
            raw = state.get("maxmem", state.get("memory"))
            if raw in (None, ""):
                return 0
            value = _num(raw, 0)
            # QEMU config stores memory in MiB; cluster resources use bytes.
            if isinstance(raw, str) or (isinstance(value, int) and 0 < value < 10_000_000):
                return int(value) * 1024 * 1024
            return int(value)

        def _maxcpu(state: dict[str, Any]) -> int:
            cores = int(_num(state.get("cores", state.get("cpus", 1)), 1))
            sockets = int(_num(state.get("sockets", 1), 1))
            return max(cores * sockets, 1)

        def _cpu_util(state: dict[str, Any], *, running: bool) -> float:
            if not running:
                return 0.0
            samples = state.get("rrddata")
            if isinstance(samples, list) and samples:
                last = samples[-1]
                if isinstance(last, dict):
                    return float(_num(last.get("cpu"), 0.0))
            return (
                float(_num(state.get("cpu"), 0.0)) if not isinstance(state.get("cpu"), str) else 0.0
            )

        type_filter = cast(dict[str, Any], inputs.get("values") or {}).get("type")
        result: list[dict[str, Any]] = []

        if type_filter in (None, "node"):
            node_rows = await _database(request).pool.fetch(
                "SELECT name AS node, status FROM nodes ORDER BY name"
            )
            from app.handlers.nodes import load_node_ops

            for row in node_rows:
                name = str(row["node"])
                ops = await load_node_ops(request, name)
                status_payload = ops.get("status")
                status_dict = dict(status_payload) if isinstance(status_payload, dict) else {}
                mem_raw = status_dict.get("mem", status_dict.get("memory"))
                if isinstance(mem_raw, dict):
                    mem_val = int(_num(mem_raw.get("used"), 0))
                    maxmem_val = int(
                        _num(status_dict.get("maxmem", mem_raw.get("total")), 8 * 1024**3)
                    )
                else:
                    mem_val = int(_num(mem_raw, 0))
                    maxmem_val = int(_num(status_dict.get("maxmem"), 8 * 1024**3))
                result.append(
                    {
                        "type": "node",
                        "id": f"node/{name}",
                        "node": name,
                        "status": str(row["status"]),
                        "cpu": float(_num(status_dict.get("cpu"), 0.0)),
                        "maxcpu": int(_num(status_dict.get("maxcpu"), 4)),
                        "mem": mem_val,
                        "maxmem": maxmem_val,
                        "uptime": int(_num(status_dict.get("uptime"), 0)),
                        "level": str(status_dict.get("level") or ""),
                    }
                )

        kind_filter: tuple[str, ...] | None
        if type_filter == "vm":
            kind_filter = ("qemu", "lxc")
        elif type_filter == "storage":
            kind_filter = ("storage",)
        elif type_filter in (None,):
            kind_filter = ("qemu", "lxc", "storage", "pool")
        elif type_filter in {"qemu", "lxc", "storage", "pool", "sdn"}:
            kind_filter = (str(type_filter),)
        else:
            kind_filter = ()

        ha_by_guest: dict[str, str] = {}
        if kind_filter and ("qemu" in kind_filter or "lxc" in kind_filter):
            ha_rows = await _database(request).pool.fetch(
                "SELECT external_id, state FROM resources WHERE kind='ha'"
            )
            for ha_row in ha_rows:
                sid = str(ha_row["external_id"])
                ha_state = _as_dict(ha_row["state"])
                ha_by_guest[sid] = str(ha_state.get("state") or "started")

        pool_by_vmid: dict[str, str] = {}
        if kind_filter and ("qemu" in kind_filter or "lxc" in kind_filter or "pool" in kind_filter):
            membership = await _database(request).pool.fetch(
                """SELECT p.pool_id AS pool, r.external_id AS vmid
                FROM pool_members pm
                JOIN pools p ON p.id=pm.pool_id
                JOIN resources r ON r.id=pm.resource_id"""
            )
            for row in membership:
                pool_by_vmid[str(row["vmid"])] = str(row["pool"])

        node_names = [
            str(item["node"])
            for item in await _database(request).pool.fetch(
                "SELECT name AS node FROM nodes ORDER BY name"
            )
        ]

        if kind_filter:
            rows = await _database(request).pool.fetch(
                """SELECT r.kind AS type, r.external_id, r.state, n.name AS node
                FROM resources r JOIN nodes n ON n.id=r.node_id
                WHERE r.kind = ANY($1::text[])
                ORDER BY r.kind, r.external_id""",
                list(kind_filter),
            )
            for row in rows:
                kind = str(row["type"])
                external_id = str(row["external_id"])
                node = str(row["node"])
                state = _as_dict(row["state"])
                if kind in {"qemu", "lxc"}:
                    status = str(state.get("status") or "stopped")
                    running = status in {"running", "paused"}
                    vmid = int(external_id)
                    sid = f"{'vm' if kind == 'qemu' else 'ct'}:{external_id}"
                    item: dict[str, Any] = {
                        "type": kind,
                        "id": f"{kind}/{external_id}",
                        "node": node,
                        "vmid": vmid,
                        "name": str(state.get("name") or f"{kind}-{external_id}"),
                        "status": status,
                        "template": bool(state.get("template") in (True, "1", 1)),
                        "cpu": _cpu_util(state, running=running),
                        "maxcpu": _maxcpu(state),
                        "mem": int(_num(state.get("mem"), 0)) if running else 0,
                        "maxmem": _memory_bytes(state),
                        "disk": int(_num(state.get("disk"), 0)),
                        "maxdisk": int(_num(state.get("maxdisk"), 0)),
                        "uptime": int(_num(state.get("uptime"), 0)) if running else 0,
                    }
                    if sid in ha_by_guest:
                        item["hastate"] = ha_by_guest[sid]
                    if external_id in pool_by_vmid:
                        item["pool"] = pool_by_vmid[external_id]
                    result.append(item)
                elif kind == "storage":
                    content = state.get("content")
                    if isinstance(content, list):
                        content_text = ",".join(str(part) for part in content)
                    else:
                        content_text = str(content or "")
                    shared = bool(_num(state.get("shared"), 0))
                    # Schema allows one storages row per storage_id; expand to every
                    # node like a real PVE dump (local + shared storages).
                    targets = node_names if (shared or len(node_names) > 1) else [node]
                    if not shared and external_id not in {"local", "local-lvm", "ceph"}:
                        targets = [node]
                    for target in targets:
                        result.append(
                            {
                                "type": "storage",
                                "id": f"storage/{target}/{external_id}",
                                "node": target,
                                "storage": external_id,
                                "status": str(state.get("status") or "available"),
                                "content": content_text,
                                "disk": int(_num(state.get("disk"), 0)),
                                "maxdisk": int(_num(state.get("maxdisk"), 1 * 1024**3)),
                                "shared": shared,
                                "plugintype": str(
                                    state.get("plugintype") or state.get("type") or "dir"
                                ),
                            }
                        )
                elif kind == "pool":
                    result.append(
                        {
                            "type": "pool",
                            "id": f"pool/{external_id}",
                            "pool": external_id,
                            "comment": str(state.get("comment") or ""),
                        }
                    )

        if type_filter in (None, "sdn"):
            metadata = await cluster_metadata(request)
            sdn = metadata.get("sdn")
            zones = sdn.get("zones") if isinstance(sdn, dict) else None
            if isinstance(zones, dict):
                for zone_name, zone in sorted(zones.items()):
                    if not isinstance(zone, dict):
                        continue
                    result.append(
                        {
                            "type": "sdn",
                            "id": f"sdn/{zone_name}",
                            "sdn": zone_name,
                            "status": str(zone.get("status") or "ok"),
                        }
                    )
        return result

    async def node_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        node = str(cast(dict[str, Any], inputs["values"])["node"])
        await require_node(request, node)
        return subdirs(
            "apt",
            "ceph",
            "disks",
            "firewall",
            "lxc",
            "network",
            "qemu",
            "services",
            "status",
            "storage",
            "tasks",
            "version",
            "vzdump",
        )

    async def node_version(request: Request, inputs: dict[str, Any]) -> dict[str, str]:
        node = str(cast(dict[str, Any], inputs["values"])["node"])
        await require_node(request, node)
        return runtime_version_payload(request)

    registry.register("/version", "GET", version)
    registry.register("/access/ticket", "POST", login)
    registry.register("/nodes", "GET", nodes)
    registry.register("/nodes/{node}", "GET", node_index)
    registry.register("/nodes/{node}/status", "GET", node_status)
    registry.register("/nodes/{node}/version", "GET", node_version)
    registry.register("/cluster/resources", "GET", resources)
    register_access_handlers(registry)
    register_cluster_handlers(registry)
    register_notifications_handlers(registry)
    register_mapping_handlers(registry)
    register_acme_handlers(registry)
    register_cluster_config_handlers(registry)
    register_sdn_handlers(registry)
    register_storage_handlers(registry)

    register_pool_handlers(registry)
    register_ceph_handlers(registry)
    register_backup_handlers(registry)
    register_ha_handlers(registry)
    register_node_ops_handlers(registry)
    register_firewall_handlers(registry)
    register_qemu_handlers(registry)
    register_lxc_handlers(registry)
    register_nodes_extra_handlers(registry)
    register_cluster_extra_handlers(registry)
    register_legacy_aliases(registry)
    return registry
