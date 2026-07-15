"""Basic persistent QEMU and task semantic handlers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.db.primitives import ConflictError
from app.handlers.common import require_node, subdirs
from app.simulation.transitions import InvalidTransitionError, VmState, plan_transition
from app.tasks.repository import TaskRepository
from app.tasks.upid import Upid


def _database(request: Request) -> AsyncpgDatabase:
    return cast(AsyncpgDatabase, request.app.state.database)


def _values(inputs: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], inputs["values"])


def _state(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        return cast(dict[str, Any], json.loads(value))
    return dict(cast(Mapping[str, Any], value))


def register_qemu_handlers(registry: HandlerRegistry) -> None:
    async def qemu_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(_values(inputs)["node"])
        rows = await _database(request).pool.fetch(
            """SELECT r.external_id::integer AS vmid, r.state
            FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='qemu' ORDER BY r.external_id::integer""",
            node,
        )
        return [{"vmid": int(row["vmid"]), **_state(row["state"])} for row in rows]

    async def qemu_status_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        payload = _values(inputs)
        await _qemu_resource(request, str(payload["node"]), str(payload["vmid"]))
        return subdirs(
            "current",
            "reboot",
            "reset",
            "resume",
            "shutdown",
            "start",
            "stop",
            "suspend",
        )

    async def qemu_status_current(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        node, vmid = str(payload["node"]), int(payload["vmid"])
        resource = await _qemu_resource(request, node, str(vmid))
        vm_state = _state(resource["state"])
        config = _state(resource["config"])
        status = str(vm_state.get("status", "stopped"))
        running = status in {"running", "paused"}
        memory_mb = int(config.get("memory", config.get("mem", 2048)))
        maxmem = memory_mb * 2**20
        mem_used = int(vm_state.get("mem", maxmem // 2 if running else 0))
        uptime = int(
            vm_state.get(
                "uptime",
                int(
                    await _database(request).pool.fetchval(
                        "SELECT extract(epoch from now())::bigint"
                    )
                )
                % 86_400
                if running
                else 0,
            )
        )
        return {
            "vmid": vmid,
            "name": str(config.get("name", f"vm-{vmid}")),
            "status": status,
            "qmpstatus": status if running else "stopped",
            "lock": str(vm_state.get("lock", "")),
            "pid": int(vm_state.get("pid", 12_345 if running else 0)),
            "cpus": int(config.get("cores", config.get("cpus", 1))),
            "maxmem": maxmem,
            "mem": mem_used,
            "balloon": int(vm_state.get("balloon", 0)),
            "ballooninfo": {
                "actual": mem_used,
                "max_mem": maxmem,
                "mem_swapped_in": 0,
                "mem_swapped_out": 0,
            },
            "uptime": uptime,
            "template": int(bool(vm_state.get("template", False))),
            "ha": {"managed": int(vm_state.get("ha_managed", 0))},
            "agent": 1 if running and str(config.get("agent", "0")).startswith("1") else 0,
        }

    async def qemu_config(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node, vmid = str(_values(inputs)["node"]), str(_values(inputs)["vmid"])
        row = await _database(request).pool.fetchrow(
            """SELECT r.state, v.config FROM resources r
            JOIN nodes n ON n.id=r.node_id
            JOIN virtual_machines v ON v.resource_id=r.id
            WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "virtual machine does not exist")
        return {"vmid": int(vmid), **_state(row["config"]), **_state(row["state"])}

    async def mutate(operation: str, request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        database = _database(request)
        row = await database.pool.fetchrow(
            """SELECT r.id, r.state FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "virtual machine does not exist")
        current = str(_state(row["state"]).get("status", "stopped"))
        try:
            plan_transition(VmState(current), operation)
        except (InvalidTransitionError, ValueError) as error:
            raise ApiError(409, f"cannot {operation} VM while it is {current}") from error
        upid = str(Upid.allocate(node, f"qm{operation}", vmid, str(request.state.principal)))
        try:
            task = await TaskRepository(database.pool).create(
                upid=upid,
                task_type=f"qemu-{operation}",
                payload={"node": node, "vmid": vmid, "resource_id": str(row["id"])},
                resource_key=f"qemu:{vmid}",
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        except ConflictError as error:
            raise ApiError(409, str(error)) from error
        return task.upid

    async def create(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid = str(values["node"]), int(values["vmid"])
        database = _database(request)
        if not await database.pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM nodes WHERE name=$1)", node
        ):
            raise ApiError(404, "node does not exist")
        if await database.pool.fetchval(
            """SELECT EXISTS(SELECT 1 FROM resources
            WHERE external_id=$1 AND kind IN ('qemu','lxc'))""",
            str(vmid),
        ):
            raise ApiError(409, "VMID already exists")
        config = {
            key: value
            for key, value in values.items()
            if key not in {"node", "vmid", "force", "archive", "start"}
        }
        return await _create_task(
            request,
            node=node,
            vmid=str(vmid),
            task_type="qemu-create",
            payload={"node": node, "vmid": vmid, "config": config},
        )

    async def update(request: Request, inputs: dict[str, Any], *, asynchronous: bool) -> str | None:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        database = _database(request)
        row = await database.pool.fetchrow(
            """SELECT r.id, r.version, r.state, v.config FROM resources r
            JOIN nodes n ON n.id=r.node_id
            JOIN virtual_machines v ON v.resource_id=r.id
            WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "virtual machine does not exist")
        control = {"node", "vmid", "digest", "delete", "revert", "skiplock", "background_delay"}
        provided = frozenset(str(item) for item in inputs.get("provided", values))
        changes = {
            key: value for key, value in values.items() if key in provided and key not in control
        }
        delete = str(values.get("delete", "")) if "delete" in provided else ""
        if asynchronous:
            return await _create_task(
                request,
                node=node,
                vmid=vmid,
                task_type="qemu-update",
                payload={
                    "node": node,
                    "vmid": vmid,
                    "resource_id": str(row["id"]),
                    "changes": changes,
                    "delete": delete,
                },
            )
        state = _state(row["state"])
        config = _state(row["config"])
        state.update(changes)
        config.update(changes)
        for key in delete.split(","):
            if key:
                state.pop(key, None)
                config.pop(key, None)
        status = await database.pool.execute(
            """UPDATE resources SET state=$3::jsonb, version=version+1,
            updated_at=now() WHERE id=$1 AND version=$2""",
            row["id"],
            row["version"],
            json.dumps(state, sort_keys=True),
        )
        if status != "UPDATE 1":
            raise ApiError(409, "configuration changed concurrently")
        await database.pool.execute(
            """UPDATE virtual_machines SET config=$2::jsonb
            WHERE resource_id=$1""",
            row["id"],
            json.dumps(config, sort_keys=True),
        )
        return None

    async def update_async(request: Request, inputs: dict[str, Any]) -> str:
        result = await update(request, inputs, asynchronous=True)
        if not isinstance(result, str):
            raise RuntimeError("async QEMU update did not create a task")
        return result

    async def update_sync(request: Request, inputs: dict[str, Any]) -> None:
        await update(request, inputs, asynchronous=False)

    async def delete(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        database = _database(request)
        row = await database.pool.fetchrow(
            """SELECT r.id, r.state FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "virtual machine does not exist")
        if str(_state(row["state"]).get("status")) != "stopped":
            raise ApiError(409, "cannot delete a running virtual machine")
        return await _create_task(
            request,
            node=node,
            vmid=vmid,
            task_type="qemu-delete",
            payload={"node": node, "vmid": vmid, "resource_id": str(row["id"])},
        )

    async def start(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("start", request, inputs)

    async def stop(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("stop", request, inputs)

    async def shutdown(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("shutdown", request, inputs)

    async def reboot(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("reboot", request, inputs)

    async def reset(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("reset", request, inputs)

    async def suspend(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("suspend", request, inputs)

    async def resume(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("resume", request, inputs)

    async def snapshot_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        rows = await _database(request).pool.fetch(
            """SELECT name, parent_name, description, created_at FROM snapshots
            WHERE resource_id=$1 ORDER BY created_at, name""",
            resource["id"],
        )
        return [
            {
                "name": row["name"],
                "parent": row["parent_name"],
                "description": row["description"] or "",
                "snaptime": int(row["created_at"].timestamp()),
            }
            for row in rows
        ]

    async def snapshot_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        row = await _snapshot(request, values)
        state = _state(row["state"])
        return {
            "name": row["name"],
            "parent": row["parent_name"],
            "description": row["description"] or "",
            "snaptime": int(row["created_at"].timestamp()),
            **state,
        }

    async def snapshot_config(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        row = await _snapshot(request, _values(inputs))
        return {"description": row["description"] or "", **_state(row["state"])}

    async def snapshot_update(request: Request, inputs: dict[str, Any]) -> None:
        values = _values(inputs)
        row = await _snapshot(request, values)
        await _database(request).pool.execute(
            "UPDATE snapshots SET description=$2 WHERE id=$1",
            row["id"],
            str(values.get("description", "")),
        )

    async def snapshot_task(operation: str, request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid, snapname = (
            str(values["node"]),
            str(values["vmid"]),
            str(values["snapname"]),
        )
        resource = await _qemu_resource(request, node, vmid)
        if operation == "snapshot-create":
            exists = await _database(request).pool.fetchval(
                "SELECT EXISTS(SELECT 1 FROM snapshots WHERE resource_id=$1 AND name=$2)",
                resource["id"],
                snapname,
            )
            if exists:
                raise ApiError(409, "snapshot already exists")
        else:
            await _snapshot(request, values)
        return await _create_task(
            request,
            node=node,
            vmid=vmid,
            task_type=f"qemu-{operation}",
            payload={
                "node": node,
                "vmid": vmid,
                "resource_id": str(resource["id"]),
                "snapname": snapname,
                "description": str(values.get("description", "")),
                "vmstate": bool(values.get("vmstate", False)),
                "start": bool(values.get("start", False)),
            },
        )

    async def snapshot_create(request: Request, inputs: dict[str, Any]) -> str:
        return await snapshot_task("snapshot-create", request, inputs)

    async def snapshot_delete(request: Request, inputs: dict[str, Any]) -> str:
        return await snapshot_task("snapshot-delete", request, inputs)

    async def snapshot_rollback(request: Request, inputs: dict[str, Any]) -> str:
        return await snapshot_task("snapshot-rollback", request, inputs)

    async def clone(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid, newid = str(values["node"]), str(values["vmid"]), str(values["newid"])
        source = await _qemu_resource(request, node, vmid)
        if await _database(request).pool.fetchval(
            """SELECT EXISTS(SELECT 1 FROM resources
            WHERE external_id=$1 AND kind IN ('qemu','lxc'))""",
            newid,
        ):
            raise ApiError(409, "VMID already exists")
        target = str(values.get("target") or node)
        if not await _database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM nodes WHERE name=$1)", target
        ):
            raise ApiError(404, "target node does not exist")
        return await _create_task(
            request,
            node=target,
            vmid=newid,
            task_type="qemu-clone",
            payload={
                "source_resource_id": str(source["id"]),
                "source_vmid": vmid,
                "node": target,
                "vmid": int(newid),
                "name": values.get("name"),
                "description": values.get("description"),
                "full": bool(values.get("full", False)),
            },
        )

    async def migrate_preconditions(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        target = values.get("target")
        if target in {None, ""}:
            raise ApiError(400, "parameter 'target' is required")
        target = str(target)
        exists = await _database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM nodes WHERE name=$1)", target
        )
        if not exists:
            raise ApiError(404, "target node does not exist")
        return {"local_disks": [], "local_resources": [], "running": False}

    async def migrate(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        target = values.get("target")
        if target in {None, ""}:
            raise ApiError(400, "parameter 'target' is required")
        target = str(target)
        resource = await _qemu_resource(request, node, vmid)
        if target == node:
            raise ApiError(400, "target node is the same as source node")
        await migrate_preconditions(request, inputs)
        return await _create_task(
            request,
            node=node,
            vmid=vmid,
            task_type="qemu-migrate",
            payload={
                "resource_id": str(resource["id"]),
                "node": node,
                "target": target,
                "vmid": vmid,
                "online": bool(values.get("online", False)),
            },
        )

    async def remote_migrate(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        target_endpoint = str(values.get("target-endpoint") or values.get("target_endpoint") or "")
        target = str(values.get("target") or "")
        if not target_endpoint:
            raise ApiError(400, "parameter target-endpoint is required")
        if not target:
            raise ApiError(400, "parameter target is required")
        node, vmid = str(values["node"]), str(values["vmid"])
        resource = await _qemu_resource(request, node, vmid)
        if target == node:
            raise ApiError(400, "target node is the same as source node")
        if not await _database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM nodes WHERE name=$1)", target
        ):
            raise ApiError(404, "target node does not exist")
        return await _create_task(
            request,
            node=node,
            vmid=vmid,
            task_type="qemu-remote-migrate",
            payload={
                "resource_id": str(resource["id"]),
                "node": node,
                "target": target,
                "vmid": vmid,
                "target-endpoint": target_endpoint,
                "online": bool(values.get("online", False)),
            },
        )

    async def resize(request: Request, inputs: dict[str, Any]) -> None:
        values = _values(inputs)
        node, vmid, disk = str(values["node"]), str(values["vmid"]), str(values["disk"])
        resource = await _qemu_resource(request, node, vmid)
        config = _state(resource["config"])
        if disk not in config:
            raise ApiError(400, f"disk {disk} does not exist")
        current = _disk_size_bytes(str(config[disk]))
        size = _resize_bytes(str(values["size"]), current)
        config[disk] = _replace_disk_size(str(config[disk]), size)
        status = await _database(request).pool.execute(
            """UPDATE virtual_machines SET config=$2::jsonb
            WHERE resource_id=$1""",
            resource["id"],
            json.dumps(config, sort_keys=True),
        )
        if status != "UPDATE 1":
            raise ApiError(409, "configuration changed concurrently")
        await _database(request).pool.execute(
            """UPDATE resources SET state=state || $2::jsonb,version=version+1,
            updated_at=now() WHERE id=$1""",
            resource["id"],
            json.dumps({disk: config[disk]}, sort_keys=True),
        )
        await _database(request).pool.execute(
            """INSERT INTO vm_disks(id,resource_id,device,storage_id,size_bytes)
            VALUES(gen_random_uuid(),$1,$2,$3,$4)
            ON CONFLICT(resource_id,device) DO UPDATE SET size_bytes=EXCLUDED.size_bytes""",
            resource["id"],
            disk,
            str(config[disk]).split(":", 1)[0],
            size,
        )

    async def move_disk(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid, disk = str(values["node"]), str(values["vmid"]), str(values["disk"])
        resource = await _qemu_resource(request, node, vmid)
        if disk not in _state(resource["config"]):
            raise ApiError(400, f"disk {disk} does not exist")
        return await _create_task(
            request,
            node=node,
            vmid=vmid,
            task_type="qemu-move-disk",
            payload={
                "resource_id": str(resource["id"]),
                "disk": disk,
                "storage": str(values.get("storage") or "local-lvm"),
                "target_vmid": int(values.get("target-vmid") or vmid),
                "target_disk": str(values.get("target-disk") or disk),
                "delete": bool(values.get("delete", True)),
            },
        )

    async def pending(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        config = _state(resource["config"])
        changes = cast(Mapping[str, Any], state.get("pending", {}))
        return [
            {"key": key, "value": str(config.get(key, "")), "pending": str(value)}
            for key, value in sorted(changes.items())
        ]

    async def agent_result(
        command: str, request: Request, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        resource = await _agent_resource(request, _values(inputs))
        config = _state(resource["config"])
        vmid = str(_values(inputs)["vmid"])
        results: dict[str, Any] = {
            "info": {
                "version": "9.2.0-simulator",
                "supported_commands": [
                    {"name": name, "enabled": True, "success-response": True}
                    for name in ("guest-ping", "guest-info", "guest-get-osinfo")
                ],
            },
            "get-osinfo": {
                "name": str(config.get("ostype", "linux")),
                "pretty-name": "Proxmox Simulator Guest",
                "version": "1.0",
                "machine": "x86_64",
            },
            "get-host-name": {"host-name": str(config.get("name", f"vm-{vmid}"))},
            "network-get-interfaces": [
                {
                    "name": "eth0",
                    "hardware-address": "02:00:00:00:00:01",
                    "ip-addresses": [
                        {"ip-address": "192.0.2.10", "ip-address-type": "ipv4", "prefix": 24}
                    ],
                }
            ],
            "ping": {},
        }
        if command == "get-time":
            seconds = int(
                await _database(request).pool.fetchval("SELECT extract(epoch from now())::bigint")
            )
            return {"result": {"seconds": seconds, "nanoseconds": 0}}
        return {"result": results[command]}

    async def agent_info(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_result("info", request, inputs)

    async def agent_osinfo(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_result("get-osinfo", request, inputs)

    async def agent_hostname(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_result("get-host-name", request, inputs)

    async def agent_network(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_result("network-get-interfaces", request, inputs)

    async def agent_time(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_result("get-time", request, inputs)

    async def agent_ping(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_result("ping", request, inputs)

    async def task_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        tasks = await TaskRepository(_database(request).pool).list_for_node(
            str(_values(inputs)["node"])
        )
        return [
            {"upid": task.upid, "status": task.status, "type": task.task_type} for task in tasks
        ]

    async def task_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        task = await TaskRepository(_database(request).pool).get_by_upid(
            str(_values(inputs)["upid"])
        )
        if task is None:
            raise ApiError(404, "task does not exist")
        result: dict[str, Any] = {
            "upid": task.upid,
            "status": "stopped" if task.status in {"success", "error", "cancelled"} else "running",
            "progress": task.progress,
        }
        if task.status in {"success", "error", "cancelled"}:
            result["exitstatus"] = "OK" if task.status == "success" else task.status.upper()
        return result

    async def task_log(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        repository = TaskRepository(_database(request).pool)
        task = await repository.get_by_upid(str(_values(inputs)["upid"]))
        if task is None:
            raise ApiError(404, "task does not exist")
        return [
            {"n": index + 1, "t": message}
            for index, message in enumerate(await repository.logs(task.id))
        ]

    async def qemu_feature(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        await _qemu_resource(request, str(payload["node"]), str(payload["vmid"]))
        return {
            "hasFeature": {
                "snapshot": 1,
                "clone": 1,
                "copy": 1,
                "template": 1,
                "move_disk": 1,
                "agent": 1,
            }
        }

    async def qemu_template(request: Request, inputs: dict[str, Any]) -> None:
        payload = _values(inputs)
        node, vmid = str(payload["node"]), str(payload["vmid"])
        resource = await _qemu_resource(request, node, vmid)
        state = _state(resource["state"])
        if state.get("status") != "stopped":
            raise ApiError(409, "virtual machine must be stopped to convert to template")
        await _database(request).pool.execute(
            "UPDATE virtual_machines SET template=true WHERE resource_id=$1",
            resource["id"],
        )
        state["template"] = True
        await _database(request).pool.execute(
            "UPDATE resources SET state=$2::jsonb WHERE id=$1",
            resource["id"],
            json.dumps(state, sort_keys=True),
        )

    async def qemu_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        payload = _values(inputs)
        node, vmid = str(payload["node"]), str(payload["vmid"])
        await require_node(request, node)
        await _qemu_resource(request, node, vmid)
        return subdirs(
            "agent",
            "clone",
            "config",
            "feature",
            "firewall",
            "migrate",
            "move_disk",
            "pending",
            "resize",
            "snapshot",
            "status",
            "template",
        )

    async def task_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        payload = _values(inputs)
        node, upid = str(payload["node"]), str(payload["upid"])
        await require_node(request, node)
        task = await TaskRepository(_database(request).pool).get_by_upid(upid)
        if task is None:
            raise ApiError(404, "task does not exist")
        return subdirs("log", "status")

    async def task_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = _values(inputs)
        upid = str(payload["upid"])
        repository = TaskRepository(_database(request).pool)
        task = await repository.get_by_upid(upid)
        if task is None:
            raise ApiError(404, "task does not exist")
        if task.status in {"success", "error", "cancelled"}:
            return
        await repository.request_cancel(task.id)

    registry.register("/nodes/{node}/qemu", "GET", qemu_list)
    registry.register("/nodes/{node}/qemu", "POST", create)
    registry.register("/nodes/{node}/qemu/{vmid}", "GET", qemu_index)
    registry.register("/nodes/{node}/qemu/{vmid}", "DELETE", delete)
    registry.register("/nodes/{node}/qemu/{vmid}/config", "GET", qemu_config)
    registry.register("/nodes/{node}/qemu/{vmid}/config", "POST", update_async)
    registry.register("/nodes/{node}/qemu/{vmid}/config", "PUT", update_sync)
    registry.register("/nodes/{node}/qemu/{vmid}/status", "GET", qemu_status_index)
    registry.register("/nodes/{node}/qemu/{vmid}/status/current", "GET", qemu_status_current)
    registry.register("/nodes/{node}/qemu/{vmid}/status/start", "POST", start)
    registry.register("/nodes/{node}/qemu/{vmid}/status/stop", "POST", stop)
    registry.register("/nodes/{node}/qemu/{vmid}/status/shutdown", "POST", shutdown)
    registry.register("/nodes/{node}/qemu/{vmid}/status/reboot", "POST", reboot)
    registry.register("/nodes/{node}/qemu/{vmid}/status/reset", "POST", reset)
    registry.register("/nodes/{node}/qemu/{vmid}/status/suspend", "POST", suspend)
    registry.register("/nodes/{node}/qemu/{vmid}/status/resume", "POST", resume)
    registry.register("/nodes/{node}/qemu/{vmid}/snapshot", "GET", snapshot_list)
    registry.register("/nodes/{node}/qemu/{vmid}/snapshot", "POST", snapshot_create)
    registry.register("/nodes/{node}/qemu/{vmid}/snapshot/{snapname}", "GET", snapshot_get)
    registry.register("/nodes/{node}/qemu/{vmid}/snapshot/{snapname}", "DELETE", snapshot_delete)
    registry.register(
        "/nodes/{node}/qemu/{vmid}/snapshot/{snapname}/config", "GET", snapshot_config
    )
    registry.register(
        "/nodes/{node}/qemu/{vmid}/snapshot/{snapname}/config", "PUT", snapshot_update
    )
    registry.register(
        "/nodes/{node}/qemu/{vmid}/snapshot/{snapname}/rollback", "POST", snapshot_rollback
    )
    registry.register("/nodes/{node}/qemu/{vmid}/clone", "POST", clone)
    registry.register("/nodes/{node}/qemu/{vmid}/migrate", "GET", migrate_preconditions)
    registry.register("/nodes/{node}/qemu/{vmid}/migrate", "POST", migrate)
    registry.register("/nodes/{node}/qemu/{vmid}/remote_migrate", "POST", remote_migrate)
    registry.register("/nodes/{node}/qemu/{vmid}/resize", "PUT", resize)
    registry.register("/nodes/{node}/qemu/{vmid}/move_disk", "POST", move_disk)
    registry.register("/nodes/{node}/qemu/{vmid}/pending", "GET", pending)
    registry.register("/nodes/{node}/qemu/{vmid}/agent/info", "GET", agent_info)
    registry.register("/nodes/{node}/qemu/{vmid}/agent/get-osinfo", "GET", agent_osinfo)
    registry.register("/nodes/{node}/qemu/{vmid}/agent/get-host-name", "GET", agent_hostname)
    registry.register(
        "/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces", "GET", agent_network
    )
    registry.register("/nodes/{node}/qemu/{vmid}/agent/get-time", "GET", agent_time)
    registry.register("/nodes/{node}/qemu/{vmid}/agent/ping", "POST", agent_ping)
    registry.register("/nodes/{node}/qemu/{vmid}/feature", "GET", qemu_feature)
    registry.register("/nodes/{node}/qemu/{vmid}/template", "POST", qemu_template)
    registry.register("/nodes/{node}/tasks", "GET", task_list)
    registry.register("/nodes/{node}/tasks/{upid}", "GET", task_index)
    registry.register("/nodes/{node}/tasks/{upid}", "DELETE", task_delete)
    registry.register("/nodes/{node}/tasks/{upid}/status", "GET", task_status)
    registry.register("/nodes/{node}/tasks/{upid}/log", "GET", task_log)
    from app.handlers.qemu_extra import register_qemu_extra_handlers

    register_qemu_extra_handlers(registry)


async def _create_task(
    request: Request,
    *,
    node: str,
    vmid: str,
    task_type: str,
    payload: dict[str, Any],
) -> str:
    database = _database(request)
    worker_type = {
        "qemu-create": "qmcreate",
        "qemu-delete": "qmdestroy",
        "qemu-update": "qmconfig",
        "qemu-snapshot-create": "qmsnapshot",
        "qemu-snapshot-delete": "qmdelsnapshot",
        "qemu-snapshot-rollback": "qmrollback",
        "qemu-clone": "qmclone",
        "qemu-migrate": "qmigrate",
        "qemu-remote-migrate": "qmremote",
        "qemu-move-disk": "qmmove",
    }[task_type]
    upid = str(Upid.allocate(node, worker_type, vmid, str(request.state.principal)))
    try:
        task = await TaskRepository(database.pool).create(
            upid=upid,
            task_type=task_type,
            payload=payload,
            resource_key=f"qemu:{vmid}",
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid


async def _qemu_resource(request: Request, node: str, vmid: str) -> Any:
    row = await _database(request).pool.fetchrow(
        """SELECT r.id, r.state, v.config FROM resources r
        JOIN nodes n ON n.id=r.node_id
        JOIN virtual_machines v ON v.resource_id=r.id
        WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
        node,
        vmid,
    )
    if row is None:
        raise ApiError(404, "virtual machine does not exist")
    return row


async def _snapshot(request: Request, values: dict[str, Any]) -> Any:
    row = await _database(request).pool.fetchrow(
        """SELECT s.* FROM snapshots s
        JOIN resources r ON r.id=s.resource_id JOIN nodes n ON n.id=r.node_id
        WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2 AND s.name=$3""",
        str(values["node"]),
        str(values["vmid"]),
        str(values["snapname"]),
    )
    if row is None:
        raise ApiError(404, "snapshot does not exist")
    return row


async def _agent_resource(request: Request, values: dict[str, Any]) -> Any:
    resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
    config = _state(resource["config"])
    state = _state(resource["state"])
    if str(config.get("agent", "0")).split(",", 1)[0].lower() not in {"1", "true", "yes"}:
        raise ApiError(409, "QEMU guest agent is not enabled")
    if state.get("status") != "running":
        raise ApiError(409, "QEMU guest agent is not running")
    return resource


_SIZE_RE = re.compile(r"^(?P<value>\d+)(?P<unit>[KMGT]?)$", re.IGNORECASE)


def _size_bytes(value: str) -> int:
    match = _SIZE_RE.fullmatch(value.strip())
    if match is None:
        raise ApiError(400, f"invalid disk size: {value}")
    units = {"": 1, "K": 2**10, "M": 2**20, "G": 2**30, "T": 2**40}
    return int(match.group("value")) * units[match.group("unit").upper()]


def _disk_size_bytes(value: str) -> int:
    for part in value.split(","):
        if part.startswith("size="):
            return _size_bytes(part.removeprefix("size="))
    return 0


def _resize_bytes(value: str, current: int) -> int:
    if value.startswith("+"):
        return current + _size_bytes(value[1:])
    result = _size_bytes(value)
    if result < current:
        raise ApiError(400, "shrinking disks is not supported")
    return result


def _replace_disk_size(value: str, size: int) -> str:
    parts = [part for part in value.split(",") if not part.startswith("size=")]
    parts.append(f"size={size // 2**30}G" if size % 2**30 == 0 else f"size={size}")
    return ",".join(parts)
