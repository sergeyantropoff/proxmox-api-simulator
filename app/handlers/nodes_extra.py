"""Additional node-level handlers with durable ops persistence."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import database, require_node, subdirs, values
from app.handlers.nodes import load_node_ops, save_node_ops
from app.tasks.repository import TaskRepository
from app.tasks.upid import Upid


def _certificates(ops: dict[str, Any]) -> dict[str, Any]:
    certs = ops.get("certificates")
    if not isinstance(certs, dict):
        return {"custom": None, "acme": {}, "info": []}
    return certs


def _hardware(ops: dict[str, Any]) -> dict[str, Any]:
    hardware = ops.get("hardware")
    if not isinstance(hardware, dict):
        return {"pci": [], "usb": [], "mdev": {}}
    return {
        "pci": list(hardware.get("pci") or []) if isinstance(hardware.get("pci"), list) else [],
        "usb": list(hardware.get("usb") or []) if isinstance(hardware.get("usb"), list) else [],
        "mdev": dict(hardware.get("mdev") or {}) if isinstance(hardware.get("mdev"), dict) else {},
    }


def _scan_cache(ops: dict[str, Any]) -> dict[str, Any]:
    scan = ops.get("scan")
    if not isinstance(scan, dict):
        return {}
    return scan


def _subscription(ops: dict[str, Any]) -> dict[str, Any]:
    subscription = ops.get("subscription")
    if not isinstance(subscription, dict):
        return {}
    return subscription


def _disk_items(ops: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    disks = ops.get("disks")
    if not isinstance(disks, dict):
        disks = {}
        ops["disks"] = disks
    items = disks.get(kind)
    if not isinstance(items, list):
        items = []
        disks[kind] = items
    return items


def _public_cert(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {key: value for key, value in entry.items() if key not in {"key", "private-key"}}


async def _node_task(request: Request, *, node: str, task_type: str, worker: str) -> str:
    from app.db.primitives import ConflictError

    pool = database(request).pool
    upid = str(Upid.allocate(node, worker, "0", str(request.state.principal)))
    try:
        task = await TaskRepository(pool).create(
            upid=upid,
            task_type=task_type,
            payload={"node": node},
            resource_key=f"node:{node}:{task_type}",
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid


async def _set_guest_status(request: Request, node: str, status: str) -> None:
    await database(request).pool.execute(
        """UPDATE resources AS r
        SET state = jsonb_set(COALESCE(r.state, '{}'::jsonb), '{status}', to_jsonb($2::text), true),
            updated_at=now()
        WHERE r.node_id=(SELECT id FROM nodes WHERE name=$1) AND r.kind IN ('qemu', 'lxc')""",
        node,
        status,
    )


async def _migrate_guests(request: Request, node: str, target: str) -> None:
    target_row = await database(request).pool.fetchrow("SELECT id FROM nodes WHERE name=$1", target)
    if target_row is None:
        raise ApiError(404, "target node does not exist")
    await database(request).pool.execute(
        """UPDATE resources SET node_id=$2, updated_at=now()
        WHERE node_id=(SELECT id FROM nodes WHERE name=$1) AND kind IN ('qemu', 'lxc')""",
        node,
        target_row["id"],
    )


def register_nodes_extra_handlers(registry: HandlerRegistry) -> None:
    async def disks_create(request: Request, inputs: dict[str, Any], kind: str) -> dict[str, Any]:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        name = str(
            payload.get("name")
            or payload.get("device")
            or payload.get("vgname")
            or payload.get("pool")
            or f"{kind}-{secrets.token_hex(2)}"
        )
        ops = await load_node_ops(request, node)
        items = _disk_items(ops, kind)
        if any(str(item.get("name")) == name for item in items):
            raise ApiError(400, f"{kind} '{name}' already exists")
        entry = {
            key: value for key, value in payload.items() if key not in {"node", "delete", "digest"}
        }
        entry["name"] = name
        items.append(entry)
        disks = ops.get("disks")
        if not isinstance(disks, dict):
            disks = {}
            ops["disks"] = disks
        disks[kind] = items
        await save_node_ops(request, node, ops)
        return entry

    async def disks_delete(request: Request, inputs: dict[str, Any], kind: str) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        name = str(payload["name"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        items = _disk_items(ops, kind)
        remaining = [item for item in items if str(item.get("name")) != name]
        if len(remaining) == len(items):
            raise ApiError(404, f"{kind} does not exist")
        ops.setdefault("disks", {})[kind] = remaining
        await save_node_ops(request, node, ops)

    async def disks_zfs_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        node = str(payload["node"])
        name = str(payload["name"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        for item in _disk_items(ops, "zfs"):
            if str(item.get("name")) == name:
                return dict(item)
        raise ApiError(404, "zfs pool does not exist")

    async def certificates_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("acme", "custom", "info")

    async def certificates_acme_index(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("certificate")

    async def certificates_acme_mutate(request: Request, inputs: dict[str, Any]) -> str | None:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        certs = _certificates(ops)
        acme = dict(certs.get("acme") or {})
        method = request.method.upper()
        if method == "DELETE":
            acme["certificate"] = None
            acme["domains"] = []
        else:
            domains = payload.get("domains") or payload.get("domain") or acme.get("domains") or []
            if isinstance(domains, str):
                domains = [part.strip() for part in domains.split(",") if part.strip()]
            acme["domains"] = list(domains)
            acme["account"] = str(payload.get("account") or acme.get("account") or "default")
            acme["certificate"] = {
                "pem": str(payload.get("certificates") or payload.get("certificate") or "SIM-ACME"),
                "issued": int(time.time()),
            }
        certs["acme"] = acme
        ops["certificates"] = certs
        await save_node_ops(request, node, ops)
        if method == "DELETE":
            return None
        return await _node_task(request, node=node, task_type="acme", worker="acme")

    async def certificates_custom(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        certs = _certificates(ops)
        if request.method.upper() == "DELETE":
            certs["custom"] = None
        else:
            certificates = str(payload.get("certificates") or payload.get("cert") or "")
            if not certificates:
                raise ApiError(400, "parameter verification failed - 'certificates' missing")
            key = str(payload.get("key") or payload.get("private-key") or "")
            certs["custom"] = {
                "certificates": certificates,
                "key": key,
                "restart": int(payload.get("restart") or 0),
                "filename": str(payload.get("filename") or "pveproxy-ssl.pem"),
            }
            info = list(certs.get("info") or [])
            info = [item for item in info if item.get("filename") != certs["custom"]["filename"]]
            info.append(
                {
                    "filename": certs["custom"]["filename"],
                    "fingerprint": secrets.token_hex(20),
                    "issuer": "CN=Simulator",
                    "subject": "CN=pve.local",
                    "notbefore": int(time.time()) - 86_400,
                    "notafter": int(time.time()) + 365 * 86_400,
                    "san": ["DNS:pve.local"],
                    "public-key-type": "rsa",
                    "public-key-bits": 2048,
                }
            )
            certs["info"] = info
        ops["certificates"] = certs
        await save_node_ops(request, node, ops)

    async def certificates_info(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        certs = _certificates(ops)
        info = list(certs.get("info") or [])
        custom = _public_cert(
            certs.get("custom") if isinstance(certs.get("custom"), dict) else None
        )
        if custom and not any(item.get("filename") == custom.get("filename") for item in info):
            info.append(
                {
                    "filename": custom.get("filename", "pveproxy-ssl.pem"),
                    "fingerprint": secrets.token_hex(20),
                    "issuer": "CN=Custom",
                    "subject": "CN=pve.local",
                }
            )
            certs["info"] = info
            ops["certificates"] = certs
            await save_node_ops(request, node, ops)
        return [dict(item) for item in info]

    async def scan_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("cifs", "iscsi", "lvm", "lvmthin", "nfs", "pbs", "zfs")

    async def scan_kind(
        request: Request, inputs: dict[str, Any], kind: str
    ) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        scan = _scan_cache(ops)
        ops["scan"] = scan
        await save_node_ops(request, node, ops)
        items = scan.get(kind, [])
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def capabilities_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("qemu")

    async def capabilities_qemu(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("cpu", "cpu-flags", "machines", "migration")

    async def capabilities_cpu(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        caps = ops.get("capabilities")
        items = caps.get("cpu") if isinstance(caps, dict) else None
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def capabilities_cpu_flags(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        caps = ops.get("capabilities")
        items = caps.get("cpu_flags") if isinstance(caps, dict) else None
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def capabilities_machines(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        caps = ops.get("capabilities")
        items = caps.get("machines") if isinstance(caps, dict) else None
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def capabilities_migration(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        caps = ops.get("capabilities")
        migration = caps.get("migration") if isinstance(caps, dict) else None
        return dict(migration) if isinstance(migration, dict) else {}

    async def hardware_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("pci", "usb")

    async def hardware_pci(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        hardware = _hardware(ops)
        return [dict(item) for item in hardware.get("pci", [])]

    async def hardware_pci_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        node = str(payload["node"])
        pci_id = str(payload.get("pci-id-or-mapping") or payload.get("pciid") or "")
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        for item in _hardware(ops).get("pci", []):
            if str(item.get("id")) == pci_id:
                return dict(item)
        raise ApiError(404, "pci device does not exist")

    async def hardware_pci_mdev(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        payload = values(inputs)
        node = str(payload["node"])
        pci_id = str(payload.get("pci-id-or-mapping") or payload.get("pciid") or "")
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        hardware = _hardware(ops)
        mdev = hardware.get("mdev", {})
        items = mdev.get(pci_id, []) if isinstance(mdev, dict) else []
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def hardware_usb(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        hardware = _hardware(ops)
        return [dict(item) for item in hardware.get("usb", [])]

    async def subscription_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        public = dict(_subscription(ops))
        public.pop("key", None)
        return public

    async def subscription_mutate(
        request: Request, inputs: dict[str, Any]
    ) -> dict[str, Any] | None:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        current = _subscription(ops)
        method = request.method.upper()
        if method == "DELETE":
            ops["subscription"] = {
                "status": "notfound",
                "message": "There is no subscription key",
            }
            await save_node_ops(request, node, ops)
            return None
        if method == "POST":
            current["checktime"] = int(time.time())
            current["status"] = current.get("status") or "Active"
            ops["subscription"] = current
            await save_node_ops(request, node, ops)
            return dict(current)
        key = str(payload.get("key") or current.get("key") or "")
        updated = {
            **current,
            **{k: v for k, v in payload.items() if k not in {"node", "delete", "digest"}},
            "key": key,
            "status": "Active" if key else current.get("status", "notfound"),
            "message": "OK" if key else current.get("message", "There is no subscription key"),
        }
        ops["subscription"] = updated
        await save_node_ops(request, node, ops)
        public = dict(updated)
        public.pop("key", None)
        return public

    async def aplinfo_get(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        items = ops.get("aplinfo")
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    async def aplinfo_download(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        downloads = list(ops.get("aplinfo_downloads") or [])
        downloads.append(
            {
                "template": str(payload.get("template") or payload.get("storage") or "unknown"),
                "at": int(time.time()),
            }
        )
        ops["aplinfo_downloads"] = downloads
        await save_node_ops(request, node, ops)
        return await _node_task(request, node=node, task_type="download", worker="download")

    async def apt_repositories_mutate(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        apt = ops.get("apt")
        if not isinstance(apt, dict):
            apt = {}
            ops["apt"] = apt
        repositories = list(apt.get("repositories") or [])
        method = request.method.upper()
        if method == "POST":
            entry = {
                key: value
                for key, value in payload.items()
                if key not in {"node", "delete", "digest"}
            }
            entry.setdefault("path", f"/etc/apt/sources.list.d/sim-{secrets.token_hex(2)}.list")
            entry.setdefault("enabled", 1)
            repositories.append(entry)
        else:
            path = payload.get("path")
            handle = payload.get("handle")
            index = payload.get("index")
            updated: list[dict[str, Any]] = []
            for idx, item in enumerate(repositories):
                match = False
                if path is not None and item.get("path") == path:
                    match = True
                if handle is not None and item.get("handle") == handle:
                    match = True
                if index is not None and idx == int(index):
                    match = True
                if match or (path is None and handle is None and index is None and idx == 0):
                    merged = {
                        **item,
                        **{
                            key: value
                            for key, value in payload.items()
                            if key not in {"node", "delete", "digest", "path", "handle", "index"}
                        },
                    }
                    updated.append(merged)
                else:
                    updated.append(item)
            repositories = updated
        apt["repositories"] = repositories
        ops["apt"] = apt
        await save_node_ops(request, node, ops)

    async def node_config_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        config = ops.get("config")
        return dict(config) if isinstance(config, dict) else {}

    async def node_config_put(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        config = dict(ops.get("config") or {})
        config.update(
            {
                key: value
                for key, value in payload.items()
                if key not in {"node", "digest", "delete"}
            }
        )
        ops["config"] = config
        await save_node_ops(request, node, ops)
        return config

    async def dns_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        dns = ops.get("dns")
        return dict(dns) if isinstance(dns, dict) else {}

    async def dns_put(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        dns = dict(ops.get("dns") or {})
        dns.update(
            {
                key: value
                for key, value in payload.items()
                if key not in {"node", "digest", "delete"}
            }
        )
        ops["dns"] = dns
        await save_node_ops(request, node, ops)
        return dns

    async def time_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        current = dict(ops.get("time") or {})
        now = int(time.time())
        current["time"] = now
        current["localtime"] = now
        return current

    async def time_put(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        current = dict(ops.get("time") or {})
        if "timezone" in payload:
            current["timezone"] = str(payload["timezone"])
        now = int(time.time())
        current["time"] = now
        current["localtime"] = now
        ops["time"] = current
        await save_node_ops(request, node, ops)
        return current

    async def execute(request: Request, inputs: dict[str, Any]) -> list[str]:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        commands = payload.get("commands") or payload.get("command") or []
        if isinstance(commands, str):
            try:
                parsed = json.loads(commands)
                commands = parsed if isinstance(parsed, list) else [commands]
            except json.JSONDecodeError:
                commands = [commands]
        ops = await load_node_ops(request, node)
        log = list(ops.get("execute_log") or [])
        output: list[str] = []
        for command in commands:
            entry = {"command": str(command), "at": int(time.time())}
            log.append(entry)
            output.append(f"OK: {command}")
        ops["execute_log"] = log[-100:]
        await save_node_ops(request, node, ops)
        return output

    async def hosts_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        hosts = ops.get("hosts")
        if not isinstance(hosts, dict):
            return {"data": "", "digest": ""}
        return {"data": str(hosts.get("data", "")), "digest": str(hosts.get("digest", ""))}

    async def hosts_post(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        ops["hosts"] = {
            "data": str(payload.get("data") or ""),
            "digest": secrets.token_hex(8),
        }
        await save_node_ops(request, node, ops)

    async def journal(request: Request, inputs: dict[str, Any]) -> list[str]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        start = int(values(inputs).get("startcursor") or values(inputs).get("start") or 0)
        limit = int(values(inputs).get("limit") or 50)
        ops = await load_node_ops(request, node)
        lines = ops.get("journal")
        if not isinstance(lines, list):
            return []
        sliced = lines[start : start + limit]
        return [str(item) for item in sliced]

    async def syslog(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        limit = int(values(inputs).get("limit") or 50)
        ops = await load_node_ops(request, node)
        lines = ops.get("syslog")
        if not isinstance(lines, list):
            return []
        return [dict(item) for item in lines[:limit] if isinstance(item, dict)]

    async def netstat(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        items = ops.get("netstat")
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def report(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        report_text = ops.get("report")
        return str(report_text) if report_text is not None else ""

    async def rrd(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        rrd_state = ops.get("rrd")
        return dict(rrd_state) if isinstance(rrd_state, dict) else {}

    async def rrddata(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        series = ops.get("rrddata")
        return [dict(item) for item in series] if isinstance(series, list) else []

    async def startall(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        await _set_guest_status(request, node, "running")
        return await _node_task(request, node=node, task_type="startall", worker="startall")

    async def stopall(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        await _set_guest_status(request, node, "stopped")
        return await _node_task(request, node=node, task_type="stopall", worker="stopall")

    async def suspendall(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        await _set_guest_status(request, node, "paused")
        return await _node_task(request, node=node, task_type="suspendall", worker="suspendall")

    async def migrateall(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        target = str(payload.get("target") or "")
        await require_node(request, node)
        if not target:
            raise ApiError(400, "parameter verification failed - 'target' missing")
        await _migrate_guests(request, node, target)
        return await _node_task(request, node=node, task_type="migrateall", worker="migrateall")

    async def status_post(request: Request, inputs: dict[str, Any]) -> str | None:
        payload = values(inputs)
        node = str(payload["node"])
        await require_node(request, node)
        command = str(payload.get("command") or "reboot")
        ops = await load_node_ops(request, node)
        ops["last_status_command"] = {"command": command, "at": int(time.time())}
        await save_node_ops(request, node, ops)
        return await _node_task(request, node=node, task_type=command, worker=command)

    async def wakeonlan(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        ops["wakeonlan"] = {"at": int(time.time())}
        await save_node_ops(request, node, ops)
        return "OK"

    async def _shell_proxy(request: Request, inputs: dict[str, Any], kind: str) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        payload = {
            "port": 5900 if kind == "vnc" else 22 if kind == "term" else 3128,
            "ticket": secrets.token_urlsafe(24),
            "user": str(getattr(request.state, "principal", "root@pam")),
            "upid": f"UPID:{node}:{secrets.token_hex(4)}:{kind}shell:0:root@pam:",
        }
        ops = await load_node_ops(request, node)
        shells = ops.setdefault("shells", {})
        shells[kind] = {key: value for key, value in payload.items() if key != "ticket"}
        ops["shells"] = shells
        await save_node_ops(request, node, ops)
        return payload

    async def spiceshell(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _shell_proxy(request, inputs, "spice")

    async def termproxy(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _shell_proxy(request, inputs, "term")

    async def vncshell(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _shell_proxy(request, inputs, "vnc")

    async def network_reload(request: Request, inputs: dict[str, Any]) -> None:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        if not isinstance(ops.get("network"), list):
            ops["network"] = []
        ops["network_applied"] = False
        await save_node_ops(request, node, ops)

    async def query_oci_repo_tags(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        repo = str(values(inputs).get("repo") or "library/alpine")
        ops = await load_node_ops(request, node)
        cache = ops.get("oci_tags")
        if not isinstance(cache, dict):
            return []
        items = cache.get(repo)
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    async def query_url_metadata(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        url = str(values(inputs).get("url") or "")
        ops = await load_node_ops(request, node)
        cache = ops.get("url_metadata")
        if not isinstance(cache, dict):
            return {}
        payload = cache.get(url)
        return dict(payload) if isinstance(payload, dict) else {}

    async def vncwebsocket(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        ops = await load_node_ops(request, node)
        shell = (ops.get("shells") or {}).get("vnc") or {"port": 5900}
        return {
            "port": shell.get("port", 5900),
            "ticket": secrets.token_urlsafe(24),
        }

    # Disks mutations (GET collections already registered in nodes.py)
    registry.register(
        "/nodes/{node}/disks/directory",
        "POST",
        lambda request, inputs: disks_create(request, inputs, "directory"),
    )
    registry.register(
        "/nodes/{node}/disks/directory/{name}",
        "DELETE",
        lambda request, inputs: disks_delete(request, inputs, "directory"),
    )
    registry.register(
        "/nodes/{node}/disks/lvm",
        "POST",
        lambda request, inputs: disks_create(request, inputs, "lvm"),
    )
    registry.register(
        "/nodes/{node}/disks/lvm/{name}",
        "DELETE",
        lambda request, inputs: disks_delete(request, inputs, "lvm"),
    )
    registry.register(
        "/nodes/{node}/disks/lvmthin",
        "POST",
        lambda request, inputs: disks_create(request, inputs, "lvmthin"),
    )
    registry.register(
        "/nodes/{node}/disks/lvmthin/{name}",
        "DELETE",
        lambda request, inputs: disks_delete(request, inputs, "lvmthin"),
    )
    registry.register(
        "/nodes/{node}/disks/zfs",
        "POST",
        lambda request, inputs: disks_create(request, inputs, "zfs"),
    )
    registry.register("/nodes/{node}/disks/zfs/{name}", "GET", disks_zfs_get)
    registry.register(
        "/nodes/{node}/disks/zfs/{name}",
        "DELETE",
        lambda request, inputs: disks_delete(request, inputs, "zfs"),
    )

    registry.register("/nodes/{node}/certificates", "GET", certificates_index)
    registry.register("/nodes/{node}/certificates/acme", "GET", certificates_acme_index)
    registry.register(
        "/nodes/{node}/certificates/acme/certificate", "POST", certificates_acme_mutate
    )
    registry.register(
        "/nodes/{node}/certificates/acme/certificate", "PUT", certificates_acme_mutate
    )
    registry.register(
        "/nodes/{node}/certificates/acme/certificate", "DELETE", certificates_acme_mutate
    )
    registry.register("/nodes/{node}/certificates/custom", "POST", certificates_custom)
    registry.register("/nodes/{node}/certificates/custom", "DELETE", certificates_custom)
    registry.register("/nodes/{node}/certificates/info", "GET", certificates_info)

    registry.register("/nodes/{node}/scan", "GET", scan_index)
    registry.register("/nodes/{node}/scan/cifs", "GET", lambda r, i: scan_kind(r, i, "cifs"))
    registry.register("/nodes/{node}/scan/iscsi", "GET", lambda r, i: scan_kind(r, i, "iscsi"))
    registry.register("/nodes/{node}/scan/lvm", "GET", lambda r, i: scan_kind(r, i, "lvm"))
    registry.register("/nodes/{node}/scan/lvmthin", "GET", lambda r, i: scan_kind(r, i, "lvmthin"))
    registry.register("/nodes/{node}/scan/nfs", "GET", lambda r, i: scan_kind(r, i, "nfs"))
    registry.register("/nodes/{node}/scan/pbs", "GET", lambda r, i: scan_kind(r, i, "pbs"))
    registry.register("/nodes/{node}/scan/zfs", "GET", lambda r, i: scan_kind(r, i, "zfs"))

    registry.register("/nodes/{node}/capabilities", "GET", capabilities_index)
    registry.register("/nodes/{node}/capabilities/qemu", "GET", capabilities_qemu)
    registry.register("/nodes/{node}/capabilities/qemu/cpu", "GET", capabilities_cpu)
    registry.register("/nodes/{node}/capabilities/qemu/cpu-flags", "GET", capabilities_cpu_flags)
    registry.register("/nodes/{node}/capabilities/qemu/machines", "GET", capabilities_machines)
    registry.register("/nodes/{node}/capabilities/qemu/migration", "GET", capabilities_migration)

    registry.register("/nodes/{node}/hardware", "GET", hardware_index)
    registry.register("/nodes/{node}/hardware/pci", "GET", hardware_pci)
    registry.register("/nodes/{node}/hardware/pci/{pci-id-or-mapping}", "GET", hardware_pci_get)
    registry.register(
        "/nodes/{node}/hardware/pci/{pci-id-or-mapping}/mdev", "GET", hardware_pci_mdev
    )
    registry.register("/nodes/{node}/hardware/usb", "GET", hardware_usb)

    registry.register("/nodes/{node}/subscription", "GET", subscription_get)
    registry.register("/nodes/{node}/subscription", "PUT", subscription_mutate)
    registry.register("/nodes/{node}/subscription", "POST", subscription_mutate)
    registry.register("/nodes/{node}/subscription", "DELETE", subscription_mutate)

    registry.register("/nodes/{node}/aplinfo", "GET", aplinfo_get)
    registry.register("/nodes/{node}/aplinfo", "POST", aplinfo_download)
    registry.register("/nodes/{node}/apt/repositories", "POST", apt_repositories_mutate)
    registry.register("/nodes/{node}/apt/repositories", "PUT", apt_repositories_mutate)
    registry.register("/nodes/{node}/config", "GET", node_config_get)
    registry.register("/nodes/{node}/config", "PUT", node_config_put)
    registry.register("/nodes/{node}/dns", "GET", dns_get)
    registry.register("/nodes/{node}/dns", "PUT", dns_put)
    registry.register("/nodes/{node}/time", "GET", time_get)
    registry.register("/nodes/{node}/time", "PUT", time_put)
    registry.register("/nodes/{node}/execute", "POST", execute)
    registry.register("/nodes/{node}/hosts", "GET", hosts_get)
    registry.register("/nodes/{node}/hosts", "POST", hosts_post)
    registry.register("/nodes/{node}/journal", "GET", journal)
    registry.register("/nodes/{node}/syslog", "GET", syslog)
    registry.register("/nodes/{node}/netstat", "GET", netstat)
    registry.register("/nodes/{node}/report", "GET", report)
    registry.register("/nodes/{node}/rrd", "GET", rrd)
    registry.register("/nodes/{node}/rrddata", "GET", rrddata)
    registry.register("/nodes/{node}/migrateall", "POST", migrateall)
    registry.register("/nodes/{node}/startall", "POST", startall)
    registry.register("/nodes/{node}/stopall", "POST", stopall)
    registry.register("/nodes/{node}/suspendall", "POST", suspendall)
    registry.register("/nodes/{node}/status", "POST", status_post)
    registry.register("/nodes/{node}/wakeonlan", "POST", wakeonlan)
    registry.register("/nodes/{node}/spiceshell", "POST", spiceshell)
    registry.register("/nodes/{node}/termproxy", "POST", termproxy)
    registry.register("/nodes/{node}/vncshell", "POST", vncshell)
    registry.register("/nodes/{node}/network", "DELETE", network_reload)
    registry.register("/nodes/{node}/query-oci-repo-tags", "GET", query_oci_repo_tags)
    registry.register("/nodes/{node}/query-url-metadata", "GET", query_url_metadata)
    registry.register("/nodes/{node}/vncwebsocket", "GET", vncwebsocket)
