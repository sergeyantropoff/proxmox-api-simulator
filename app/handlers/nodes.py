"""Node-level operational handlers (apt, network, disks, services)."""

from __future__ import annotations

import copy
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import (
    database,
    node_metadata,
    require_node,
    save_node_metadata,
    subdirs,
    values,
)
from app.tasks.repository import TaskRepository
from app.tasks.upid import Upid

DEFAULT_NODE_OPS: dict[str, Any] = {
    "network": [
        {
            "iface": "vmbr0",
            "type": "bridge",
            "active": 1,
            "method": "static",
            "address": "10.0.0.10/24",
        },
        {
            "iface": "vmbr1",
            "type": "bridge",
            "active": 1,
            "method": "static",
            "address": "10.10.0.10/24",
        },
        {"iface": "eno1", "type": "eth", "active": 1, "method": "manual"},
    ],
    "disks": {
        "list": [
            {
                "devpath": "/dev/sda",
                "size": 1_000_000_000_000,
                "model": "SIM-DISK-01",
                "serial": "SIM0001",
                "gpt": 1,
            },
            {
                "devpath": "/dev/sdb",
                "size": 2_000_000_000_000,
                "model": "SIM-SSD-01",
                "serial": "SIM0002",
                "gpt": 0,
            },
        ],
        "directory": [],
        "lvm": [],
        "lvmthin": [],
        "zfs": [],
        "smart": {},
    },
    "services": {
        "pveproxy": {"state": "running", "enabled": 1},
        "pvedaemon": {"state": "running", "enabled": 1},
        "pvestatd": {"state": "running", "enabled": 1},
        "corosync": {"state": "running", "enabled": 1},
    },
    "apt": {
        "packages": [
            {
                "Package": "pve-manager",
                "Version": "9.2.3",
                "OldVersion": "9.2.2",
                "Status": "upgradable",
            },
            {"Package": "libpve-common-perl", "Version": "9.0.3", "Status": "installed"},
        ],
        "repositories": [
            {
                "path": "/etc/apt/sources.list.d/pve-enterprise.list",
                "enabled": 1,
                "types": "deb",
                "uri": "http://download.proxmox.com/debian/pve",
                "suites": "bookworm",
                "components": "pve-no-subscription",
            }
        ],
        "update": {"status": "stopped", "exitstatus": "OK"},
        "changelogs": {},
    },
}


def default_node_ops() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_NODE_OPS)


async def load_node_ops(request: Request, node: str) -> dict[str, Any]:
    metadata = await node_metadata(request, node)
    ops = metadata.get("ops")
    if isinstance(ops, dict) and ops:
        return ops
    ops = default_node_ops()
    metadata["ops"] = ops
    await save_node_metadata(request, node, metadata)
    return ops


async def save_node_ops(request: Request, node: str, ops: dict[str, Any]) -> None:
    metadata = await node_metadata(request, node)
    metadata["ops"] = ops
    await save_node_metadata(request, node, metadata)


def register_node_ops_handlers(registry: HandlerRegistry) -> None:
    async def apt_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("changelog", "repositories", "update", "versions")

    async def apt_versions(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        packages = ops.get("apt", {}).get("packages", [])
        return list(packages) if isinstance(packages, list) else []

    async def apt_repositories(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        repositories = ops.get("apt", {}).get("repositories", [])
        return list(repositories) if isinstance(repositories, list) else []

    async def apt_changelog(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        name = str(values(inputs).get("name") or "pve-manager")
        ops = await load_node_ops(request, node)
        changelogs = ops.setdefault("apt", {}).setdefault("changelogs", {})
        if name not in changelogs:
            changelogs[name] = f"simulated changelog for {name}\n\n  * emulator build\n"
            await save_node_ops(request, node, ops)
        return str(changelogs[name])

    async def apt_update_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        update = ops.get("apt", {}).get("update", {"status": "stopped", "exitstatus": "OK"})
        if isinstance(update, dict):
            return dict(update)
        return {"status": "stopped", "exitstatus": "OK"}

    async def apt_update_start(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        apt = ops.setdefault("apt", {})
        apt["update"] = {"status": "running", "exitstatus": ""}
        await save_node_ops(request, node, ops)
        return await _node_task(request, node=node, task_type="aptupdate", worker="aptupdate")

    async def network_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        network = ops.get("network", [])
        return [dict(item) for item in network] if isinstance(network, list) else []

    async def network_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        iface = str(values(inputs)["iface"])
        for item in await network_list(request, inputs):
            if item.get("iface") == iface:
                return item
        raise ApiError(404, "interface does not exist")

    async def network_mutate(request: Request, inputs: dict[str, Any]) -> None:
        node = str(values(inputs)["node"])
        payload = values(inputs)
        ops = await load_node_ops(request, node)
        network = list(ops.get("network") or [])
        iface = payload.get("iface")
        method = request.method.upper()
        if method == "DELETE":
            target = str(iface or "")
            if not any(item.get("iface") == target for item in network):
                raise ApiError(404, "interface does not exist")
            ops["network"] = [item for item in network if item.get("iface") != target]
        elif method == "POST":
            name = str(iface or payload.get("iface") or "")
            if not name:
                raise ApiError(400, "parameter verification failed - 'iface' missing")
            if any(item.get("iface") == name for item in network):
                raise ApiError(400, f"interface '{name}' already exists")
            entry = {
                key: value
                for key, value in payload.items()
                if key not in {"node", "delete", "digest"}
            }
            entry["iface"] = name
            entry.setdefault("type", "bridge")
            entry.setdefault("active", 1)
            network.append(entry)
            ops["network"] = network
        elif method == "PUT" and iface is not None:
            name = str(iface)
            found = False
            updated: list[dict[str, Any]] = []
            for item in network:
                if item.get("iface") != name:
                    updated.append(item)
                    continue
                found = True
                merged = {
                    **item,
                    **{
                        key: value
                        for key, value in payload.items()
                        if key not in {"node", "iface", "delete", "digest"}
                    },
                }
                merged["iface"] = name
                updated.append(merged)
            if not found:
                raise ApiError(404, "interface does not exist")
            ops["network"] = updated
        else:
            ops["network_applied"] = True
        await save_node_ops(request, node, ops)

    async def disks_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("directory", "list", "lvm", "lvmthin", "smart", "zfs")

    async def _disks(request: Request, node: str) -> dict[str, Any]:
        ops = await load_node_ops(request, node)
        disks = ops.setdefault("disks", default_node_ops()["disks"])
        if not isinstance(disks, dict):
            disks = default_node_ops()["disks"]
            ops["disks"] = disks
            await save_node_ops(request, node, ops)
        return cast(dict[str, Any], disks)

    async def disks_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        disks = await _disks(request, node)
        items = disks.get("list", [])
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def disks_smart(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        disk = str(values(inputs).get("disk") or "/dev/sda")
        disks = await _disks(request, node)
        smart = disks.setdefault("smart", {})
        if disk not in smart:
            smart[disk] = {
                "health": "PASSED",
                "type": "scsi",
                "model": "SIM-DISK",
                "serial": disk.rsplit("/", 1)[-1],
            }
            ops = await load_node_ops(request, node)
            ops["disks"] = disks
            await save_node_ops(request, node, ops)
        return dict(smart[disk])

    async def disks_collection(
        request: Request, inputs: dict[str, Any], key: str
    ) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        disks = await _disks(request, node)
        items = disks.get(key, [])
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def disks_directory(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return await disks_collection(request, inputs, "directory")

    async def disks_lvm(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return await disks_collection(request, inputs, "lvm")

    async def disks_lvmthin(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return await disks_collection(request, inputs, "lvmthin")

    async def disks_zfs(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return await disks_collection(request, inputs, "zfs")

    async def disks_initgpt(request: Request, inputs: dict[str, Any]) -> None:
        node = str(values(inputs)["node"])
        disk = str(values(inputs).get("disk") or values(inputs).get("device") or "")
        if not disk:
            raise ApiError(400, "parameter verification failed - 'disk' missing")
        ops = await load_node_ops(request, node)
        disks = ops.setdefault("disks", default_node_ops()["disks"])
        items = list(disks.get("list") or [])
        found = False
        for item in items:
            if item.get("devpath") == disk:
                item["gpt"] = 1
                found = True
                break
        if not found:
            items.append(
                {
                    "devpath": disk,
                    "size": 0,
                    "model": "SIM-DISK",
                    "serial": disk,
                    "gpt": 1,
                }
            )
        disks["list"] = items
        ops["disks"] = disks
        await save_node_ops(request, node, ops)

    async def disks_wipedisk(request: Request, inputs: dict[str, Any]) -> None:
        node = str(values(inputs)["node"])
        disk = str(values(inputs).get("disk") or values(inputs).get("device") or "")
        if not disk:
            raise ApiError(400, "parameter verification failed - 'disk' missing")
        ops = await load_node_ops(request, node)
        disks = ops.setdefault("disks", default_node_ops()["disks"])
        items = list(disks.get("list") or [])
        for item in items:
            if item.get("devpath") == disk:
                item["wiped"] = 1
                item["gpt"] = 0
                break
        else:
            raise ApiError(404, "disk does not exist")
        disks["list"] = items
        smart = disks.setdefault("smart", {})
        smart.pop(disk, None)
        ops["disks"] = disks
        await save_node_ops(request, node, ops)

    async def services_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        services = ops.get("services") or {}
        return [{"subdir": name} for name in sorted(services)]

    async def service_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        service = str(values(inputs)["service"])
        ops = await load_node_ops(request, node)
        services = ops.setdefault("services", {})
        if service not in services:
            services[service] = {"state": "stopped", "enabled": 0}
            await save_node_ops(request, node, ops)
        payload = dict(services[service])
        payload["service"] = service
        return payload

    async def service_state(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await service_get(request, inputs)

    async def service_action(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        service = str(values(inputs)["service"])
        path = request.url.path.rstrip("/")
        action = path.rsplit("/", 1)[-1]
        ops = await load_node_ops(request, node)
        services = ops.setdefault("services", {})
        current = dict(services.get(service) or {"state": "stopped", "enabled": 0})
        if action == "start":
            current["state"] = "running"
            current["enabled"] = 1
        elif action == "stop":
            current["state"] = "stopped"
        elif action in {"restart", "reload"}:
            current["state"] = "running"
            current["enabled"] = 1
        else:
            raise ApiError(400, f"unknown service action: {action}")
        services[service] = current
        ops["services"] = services
        await save_node_ops(request, node, ops)
        return "OK"

    registry.register("/nodes/{node}/apt", "GET", apt_index)
    registry.register("/nodes/{node}/apt/versions", "GET", apt_versions)
    registry.register("/nodes/{node}/apt/repositories", "GET", apt_repositories)
    registry.register("/nodes/{node}/apt/changelog", "GET", apt_changelog)
    registry.register("/nodes/{node}/apt/update", "GET", apt_update_status)
    registry.register("/nodes/{node}/apt/update", "POST", apt_update_start)
    registry.register("/nodes/{node}/network", "GET", network_list)
    registry.register("/nodes/{node}/network", "POST", network_mutate)
    registry.register("/nodes/{node}/network", "PUT", network_mutate)
    registry.register("/nodes/{node}/network/{iface}", "GET", network_get)
    registry.register("/nodes/{node}/network/{iface}", "PUT", network_mutate)
    registry.register("/nodes/{node}/network/{iface}", "DELETE", network_mutate)
    registry.register("/nodes/{node}/disks", "GET", disks_index)
    registry.register("/nodes/{node}/disks/list", "GET", disks_list)
    registry.register("/nodes/{node}/disks/smart", "GET", disks_smart)
    registry.register("/nodes/{node}/disks/directory", "GET", disks_directory)
    registry.register("/nodes/{node}/disks/lvm", "GET", disks_lvm)
    registry.register("/nodes/{node}/disks/lvmthin", "GET", disks_lvmthin)
    registry.register("/nodes/{node}/disks/zfs", "GET", disks_zfs)
    registry.register("/nodes/{node}/disks/initgpt", "POST", disks_initgpt)
    registry.register("/nodes/{node}/disks/wipedisk", "PUT", disks_wipedisk)
    registry.register("/nodes/{node}/services", "GET", services_index)
    registry.register("/nodes/{node}/services/{service}", "GET", service_get)
    registry.register("/nodes/{node}/services/{service}/state", "GET", service_state)
    registry.register("/nodes/{node}/services/{service}/start", "POST", service_action)
    registry.register("/nodes/{node}/services/{service}/stop", "POST", service_action)
    registry.register("/nodes/{node}/services/{service}/restart", "POST", service_action)
    registry.register("/nodes/{node}/services/{service}/reload", "POST", service_action)


async def _node_task(request: Request, *, node: str, task_type: str, worker: str) -> str:
    from app.api.errors import ApiError
    from app.db.primitives import ConflictError

    pool = database(request).pool
    upid = str(Upid.allocate(node, worker, "0", str(request.state.principal)))
    try:
        task = await TaskRepository(pool).create(
            upid=upid,
            task_type=task_type,
            payload={"node": node},
            resource_key=f"node:{node}",
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid
