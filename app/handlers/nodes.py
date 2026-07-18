"""Node-level operational handlers (apt, network, disks, services)."""

from __future__ import annotations

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


async def load_node_ops(request: Request, node: str) -> dict[str, Any]:
    metadata = await node_metadata(request, node)
    ops = metadata.get("ops")
    if isinstance(ops, dict):
        return ops
    return {}


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
        if not isinstance(packages, list):
            return []
        result: list[dict[str, Any]] = []
        for item in packages:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            status = str(entry.pop("Status", entry.get("CurrentState", "Installed")))
            if status.lower() == "upgradable":
                entry["CurrentState"] = "Installed"
                entry.setdefault("OldVersion", entry.get("Version", ""))
            else:
                entry["CurrentState"] = "Installed" if status.lower() == "installed" else status
            entry.setdefault("Package", entry.get("Package") or "unknown")
            entry.setdefault("Version", entry.get("Version") or "")
            entry.setdefault("Arch", "amd64")
            entry.setdefault("Origin", "Proxmox")
            result.append(entry)
        return result

    async def apt_repositories(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        repositories = ops.get("apt", {}).get("repositories")
        if isinstance(repositories, dict) and "files" in repositories:
            return {
                "digest": str(repositories.get("digest") or "seedapt"),
                "files": list(repositories.get("files") or []),
                "errors": list(repositories.get("errors") or []),
                "infos": list(repositories.get("infos") or []),
                "standard-repos": list(repositories.get("standard-repos") or []),
            }
        legacy = list(repositories) if isinstance(repositories, list) else []
        return {
            "digest": "seedapt",
            "files": [
                {
                    "path": "/etc/apt/sources.list.d/pve-enterprise.list",
                    "file-type": "list",
                    "digest": "seedapt-file0",
                    "repositories": legacy,
                }
            ],
            "errors": [],
            "infos": [],
            "standard-repos": [
                {
                    "handle": "no-subscription",
                    "name": "Proxmox VE No-Subscription Repository",
                    "status": 1,
                }
            ],
        }

    async def apt_changelog(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        name = str(values(inputs).get("name") or "pve-manager")
        ops = await load_node_ops(request, node)
        apt = ops.get("apt")
        changelogs = apt.get("changelogs") if isinstance(apt, dict) else None
        if not isinstance(changelogs, dict):
            return ""
        return str(changelogs.get(name) or "")

    async def apt_update_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        apt = ops.get("apt")
        update = apt.get("update") if isinstance(apt, dict) else None
        return dict(update) if isinstance(update, dict) else {}

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

    async def network_mutate(request: Request, inputs: dict[str, Any]) -> str | None:
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
            # PUT /nodes/{node}/network without iface → reload (returns UPID string).
            ops["network_applied"] = True
            await save_node_ops(request, node, ops)
            return await _node_task(
                request, node=node, task_type="network-reload", worker="srvreload"
            )
        await save_node_ops(request, node, ops)
        return None

    async def disks_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("directory", "list", "lvm", "lvmthin", "smart", "zfs")

    async def _disks(request: Request, node: str) -> dict[str, Any]:
        ops = await load_node_ops(request, node)
        disks = ops.get("disks")
        if not isinstance(disks, dict):
            return {}
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
        smart = disks.get("smart")
        if not isinstance(smart, dict) or disk not in smart:
            return {}
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

    async def disks_initgpt(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        disk = str(values(inputs).get("disk") or values(inputs).get("device") or "")
        if not disk:
            raise ApiError(400, "parameter verification failed - 'disk' missing")
        ops = await load_node_ops(request, node)
        disks = ops.get("disks")
        if not isinstance(disks, dict):
            disks = {}
            ops["disks"] = disks
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
        return await _node_task(request, node=node, task_type="disk-initgpt", worker="diskinit")

    async def disks_wipedisk(request: Request, inputs: dict[str, Any]) -> str:
        node = str(values(inputs)["node"])
        disk = str(values(inputs).get("disk") or values(inputs).get("device") or "")
        if not disk:
            raise ApiError(400, "parameter verification failed - 'disk' missing")
        ops = await load_node_ops(request, node)
        disks = ops.get("disks")
        if not isinstance(disks, dict):
            raise ApiError(404, "disk does not exist")
        items = list(disks.get("list") or [])
        for item in items:
            if item.get("devpath") == disk:
                item["wiped"] = 1
                item["gpt"] = 0
                break
        else:
            raise ApiError(404, "disk does not exist")
        disks["list"] = items
        smart = disks.get("smart")
        if isinstance(smart, dict):
            smart.pop(disk, None)
        ops["disks"] = disks
        await save_node_ops(request, node, ops)
        return await _node_task(request, node=node, task_type="disk-wipe", worker="diskwipe")

    async def services_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        ops = await load_node_ops(request, node)
        services = ops.get("services") or {}
        result: list[dict[str, Any]] = []
        for name in sorted(services):
            payload = dict(services[name]) if isinstance(services[name], dict) else {}
            state_name = str(payload.get("state", "stopped"))
            enabled = bool(int(payload.get("enabled", 0) or 0))
            result.append(
                {
                    "service": name,
                    "name": f"{name}.service",
                    "desc": str(payload.get("desc") or name),
                    "state": state_name,
                    "active-state": "active" if state_name == "running" else "inactive",
                    "unit-state": "enabled" if enabled else "disabled",
                }
            )
        return result

    async def service_get(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        node = str(values(inputs)["node"])
        service = str(values(inputs)["service"])
        ops = await load_node_ops(request, node)
        services = ops.setdefault("services", {})
        if service not in services:
            services[service] = {"state": "stopped", "enabled": 0}
            await save_node_ops(request, node, ops)
        return subdirs("state", "start", "stop", "restart", "reload")

    async def service_state(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        service = str(values(inputs)["service"])
        ops = await load_node_ops(request, node)
        services = ops.setdefault("services", {})
        if service not in services:
            services[service] = {"state": "stopped", "enabled": 0}
            await save_node_ops(request, node, ops)
        payload = dict(services[service]) if isinstance(services[service], dict) else {}
        state_name = str(payload.get("state", "stopped"))
        enabled = bool(int(payload.get("enabled", 0) or 0))
        return {
            "service": service,
            "state": state_name,
            "active-state": "active" if state_name == "running" else "inactive",
            "unit-state": "enabled" if enabled else "disabled",
        }

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
        return await _node_task(
            request,
            node=node,
            task_type=f"service-{action}",
            worker=f"srv{action}",
        )

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
    import secrets

    from app.api.errors import ApiError
    from app.db.primitives import ConflictError

    pool = database(request).pool
    upid = str(Upid.allocate(node, worker, "0", str(request.state.principal)))
    try:
        task = await TaskRepository(pool).create(
            upid=upid,
            task_type=task_type,
            payload={"node": node},
            resource_key=f"node:{node}:{task_type}:{secrets.token_hex(4)}",
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid
