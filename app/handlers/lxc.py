"""Persistent LXC semantic handlers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.db.primitives import ConflictError
from app.handlers.common import (
    disk_size_bytes,
    replace_disk_size,
    require_node,
    resize_size_bytes,
    subdirs,
)
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


def register_lxc_handlers(registry: HandlerRegistry) -> None:
    async def lxc_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(_values(inputs)["node"])
        rows = await _database(request).pool.fetch(
            """SELECT r.external_id::integer AS vmid, r.state
            FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='lxc' ORDER BY r.external_id::integer""",
            node,
        )
        return [{"vmid": int(row["vmid"]), **_state(row["state"])} for row in rows]

    async def lxc_config(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node, vmid = str(_values(inputs)["node"]), str(_values(inputs)["vmid"])
        row = await _lxc_resource(request, node, vmid)
        return {"vmid": int(vmid), **_state(row["config"]), **_state(row["state"])}

    async def lxc_current(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await lxc_config(request, inputs)

    async def lxc_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await lxc_config(request, inputs)

    async def mutate(operation: str, request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        database = _database(request)
        row = await database.pool.fetchrow(
            """SELECT r.id, r.state FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='lxc' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "container does not exist")
        current = str(_state(row["state"]).get("status", "stopped"))
        try:
            plan_transition(VmState(current), operation)
        except (InvalidTransitionError, ValueError) as error:
            raise ApiError(409, f"cannot {operation} container while it is {current}") from error
        upid = str(Upid.allocate(node, f"pct{operation}", vmid, str(request.state.principal)))
        try:
            task = await TaskRepository(database.pool).create(
                upid=upid,
                task_type=f"lxc-{operation}",
                payload={"node": node, "vmid": vmid, "resource_id": str(row["id"])},
                resource_key=f"lxc:{vmid}",
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        except ConflictError as error:
            raise ApiError(409, str(error)) from error
        return task.upid

    async def start(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("start", request, inputs)

    async def stop(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("stop", request, inputs)

    async def shutdown(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("shutdown", request, inputs)

    async def reboot(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("reboot", request, inputs)

    async def suspend(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("suspend", request, inputs)

    async def resume(request: Request, inputs: dict[str, Any]) -> str:
        return await mutate("resume", request, inputs)

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
            if key not in {"node", "vmid", "force", "start", "ostemplate"}
        }
        if "ostemplate" in values:
            config["ostemplate"] = values["ostemplate"]
        return await _create_task(
            request,
            node=node,
            vmid=str(vmid),
            task_type="lxc-create",
            payload={
                "node": node,
                "vmid": vmid,
                "config": config,
                "start": bool(values.get("start")),
            },
        )

    async def update(request: Request, inputs: dict[str, Any]) -> None:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        database = _database(request)
        row = await database.pool.fetchrow(
            """SELECT r.id, r.version, r.state, c.config FROM resources r
            JOIN nodes n ON n.id=r.node_id
            JOIN containers c ON c.resource_id=r.id
            WHERE n.name=$1 AND r.kind='lxc' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "container does not exist")
        control = {"node", "vmid", "digest", "delete", "revert", "skiplock"}
        provided = frozenset(str(item) for item in inputs.get("provided", values))
        changes = {
            key: value for key, value in values.items() if key in provided and key not in control
        }
        delete = str(values.get("delete", "")) if "delete" in provided else ""
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
            "UPDATE containers SET config=$2::jsonb WHERE resource_id=$1",
            row["id"],
            json.dumps(config, sort_keys=True),
        )

    async def delete(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        node, vmid = str(values["node"]), str(values["vmid"])
        database = _database(request)
        row = await database.pool.fetchrow(
            """SELECT r.id, r.state FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE n.name=$1 AND r.kind='lxc' AND r.external_id=$2""",
            node,
            vmid,
        )
        if row is None:
            raise ApiError(404, "container does not exist")
        if str(_state(row["state"]).get("status")) != "stopped":
            raise ApiError(409, "cannot delete a running container")
        return await _create_task(
            request,
            node=node,
            vmid=vmid,
            task_type="lxc-delete",
            payload={"node": node, "vmid": vmid, "resource_id": str(row["id"])},
        )

    async def snapshot_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        values = _values(inputs)
        resource = await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
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
        resource = await _lxc_resource(request, node, vmid)
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
            task_type=f"lxc-{operation}",
            payload={
                "node": node,
                "vmid": vmid,
                "resource_id": str(resource["id"]),
                "snapname": snapname,
                "description": str(values.get("description", "")),
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
        source = await _lxc_resource(request, node, vmid)
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
            task_type="lxc-clone",
            payload={
                "source_resource_id": str(source["id"]),
                "source_vmid": vmid,
                "node": target,
                "vmid": int(newid),
                "name": values.get("hostname") or values.get("name"),
                "full": bool(values.get("full", False)),
            },
        )

    async def migrate_preconditions(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
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
        resource = await _lxc_resource(request, node, vmid)
        if target == node:
            raise ApiError(400, "target node is the same as source node")
        await migrate_preconditions(request, inputs)
        return await _create_task(
            request,
            node=node,
            vmid=vmid,
            task_type="lxc-migrate",
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
        resource = await _lxc_resource(request, node, vmid)
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
            task_type="lxc-remote-migrate",
            payload={
                "resource_id": str(resource["id"]),
                "node": node,
                "target": target,
                "vmid": vmid,
                "target-endpoint": target_endpoint,
                "online": bool(values.get("online", False)),
            },
        )

    async def pending(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        values = _values(inputs)
        resource = await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        config = _state(resource["config"])
        changes = cast(Mapping[str, Any], state.get("pending", {}))
        return [
            {"key": key, "value": str(config.get(key, "")), "pending": str(value)}
            for key, value in sorted(changes.items())
        ]

    async def lxc_feature(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        await _lxc_resource(request, str(payload["node"]), str(payload["vmid"]))
        return {
            "hasFeature": {
                "snapshot": 1,
                "clone": 1,
                "copy": 1,
                "template": 1,
                "move_volume": 1,
            }
        }

    async def lxc_resize(request: Request, inputs: dict[str, Any]) -> None:
        payload = _values(inputs)
        node, vmid = str(payload["node"]), str(payload["vmid"])
        disk = str(payload.get("disk") or "rootfs")
        resource = await _lxc_resource(request, node, vmid)
        config = _state(resource["config"])
        if disk not in config:
            raise ApiError(400, f"disk {disk} does not exist")
        try:
            current = disk_size_bytes(str(config[disk]))
            size = resize_size_bytes(str(payload["size"]), current)
        except ValueError as error:
            raise ApiError(400, str(error)) from error
        config[disk] = replace_disk_size(str(config[disk]), size)
        await _database(request).pool.execute(
            "UPDATE containers SET config=$2::jsonb WHERE resource_id=$1",
            resource["id"],
            json.dumps(config, sort_keys=True),
        )
        await _database(request).pool.execute(
            """UPDATE resources SET state=state || $2::jsonb, version=version+1,
            updated_at=now() WHERE id=$1""",
            resource["id"],
            json.dumps({disk: config[disk]}, sort_keys=True),
        )

    async def lxc_template(request: Request, inputs: dict[str, Any]) -> None:
        payload = _values(inputs)
        node, vmid = str(payload["node"]), str(payload["vmid"])
        resource = await _lxc_resource(request, node, vmid)
        state = _state(resource["state"])
        if state.get("status") != "stopped":
            raise ApiError(409, "container must be stopped to convert to template")
        await _database(request).pool.execute(
            "UPDATE containers SET template=true WHERE resource_id=$1",
            resource["id"],
        )
        state["template"] = True
        await _database(request).pool.execute(
            "UPDATE resources SET state=$2::jsonb WHERE id=$1",
            resource["id"],
            json.dumps(state, sort_keys=True),
        )

    async def lxc_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        payload = _values(inputs)
        node, vmid = str(payload["node"]), str(payload["vmid"])
        await require_node(request, node)
        await _lxc_resource(request, node, vmid)
        return subdirs(
            "clone",
            "config",
            "feature",
            "firewall",
            "migrate",
            "pending",
            "resize",
            "snapshot",
            "status",
            "template",
        )

    registry.register("/nodes/{node}/lxc", "GET", lxc_list)
    registry.register("/nodes/{node}/lxc", "POST", create)
    registry.register("/nodes/{node}/lxc/{vmid}", "GET", lxc_index)
    registry.register("/nodes/{node}/lxc/{vmid}", "DELETE", delete)
    registry.register("/nodes/{node}/lxc/{vmid}/config", "GET", lxc_config)
    registry.register("/nodes/{node}/lxc/{vmid}/config", "PUT", update)
    registry.register("/nodes/{node}/lxc/{vmid}/status", "GET", lxc_status)
    registry.register("/nodes/{node}/lxc/{vmid}/status/current", "GET", lxc_current)
    registry.register("/nodes/{node}/lxc/{vmid}/status/start", "POST", start)
    registry.register("/nodes/{node}/lxc/{vmid}/status/stop", "POST", stop)
    registry.register("/nodes/{node}/lxc/{vmid}/status/shutdown", "POST", shutdown)
    registry.register("/nodes/{node}/lxc/{vmid}/status/reboot", "POST", reboot)
    registry.register("/nodes/{node}/lxc/{vmid}/status/suspend", "POST", suspend)
    registry.register("/nodes/{node}/lxc/{vmid}/status/resume", "POST", resume)
    registry.register("/nodes/{node}/lxc/{vmid}/snapshot", "GET", snapshot_list)
    registry.register("/nodes/{node}/lxc/{vmid}/snapshot", "POST", snapshot_create)
    registry.register("/nodes/{node}/lxc/{vmid}/snapshot/{snapname}", "GET", snapshot_get)
    registry.register("/nodes/{node}/lxc/{vmid}/snapshot/{snapname}", "DELETE", snapshot_delete)
    registry.register("/nodes/{node}/lxc/{vmid}/snapshot/{snapname}/config", "GET", snapshot_config)
    registry.register("/nodes/{node}/lxc/{vmid}/snapshot/{snapname}/config", "PUT", snapshot_update)
    registry.register(
        "/nodes/{node}/lxc/{vmid}/snapshot/{snapname}/rollback", "POST", snapshot_rollback
    )
    registry.register("/nodes/{node}/lxc/{vmid}/clone", "POST", clone)
    registry.register("/nodes/{node}/lxc/{vmid}/migrate", "GET", migrate_preconditions)
    registry.register("/nodes/{node}/lxc/{vmid}/migrate", "POST", migrate)
    registry.register("/nodes/{node}/lxc/{vmid}/remote_migrate", "POST", remote_migrate)
    registry.register("/nodes/{node}/lxc/{vmid}/pending", "GET", pending)
    registry.register("/nodes/{node}/lxc/{vmid}/feature", "GET", lxc_feature)
    registry.register("/nodes/{node}/lxc/{vmid}/resize", "PUT", lxc_resize)
    registry.register("/nodes/{node}/lxc/{vmid}/template", "POST", lxc_template)
    from app.handlers.lxc_extra import register_lxc_extra_handlers

    register_lxc_extra_handlers(registry)


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
        "lxc-create": "pctcreate",
        "lxc-delete": "pctdestroy",
        "lxc-snapshot-create": "pctsnapshot",
        "lxc-snapshot-delete": "pctdelsnapshot",
        "lxc-snapshot-rollback": "pctrollback",
        "lxc-clone": "pctclone",
        "lxc-migrate": "pctmigrate",
        "lxc-remote-migrate": "pctremote",
    }[task_type]
    upid = str(Upid.allocate(node, worker_type, vmid, str(request.state.principal)))
    try:
        task = await TaskRepository(database.pool).create(
            upid=upid,
            task_type=task_type,
            payload=payload,
            resource_key=f"lxc:{vmid}",
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid


async def _lxc_resource(request: Request, node: str, vmid: str) -> Any:
    row = await _database(request).pool.fetchrow(
        """SELECT r.id, r.state, c.config FROM resources r
        JOIN nodes n ON n.id=r.node_id
        JOIN containers c ON c.resource_id=r.id
        WHERE n.name=$1 AND r.kind='lxc' AND r.external_id=$2""",
        node,
        vmid,
    )
    if row is None:
        raise ApiError(404, "container does not exist")
    return row


async def _snapshot(request: Request, values: dict[str, Any]) -> Any:
    row = await _database(request).pool.fetchrow(
        """SELECT s.* FROM snapshots s
        JOIN resources r ON r.id=s.resource_id JOIN nodes n ON n.id=r.node_id
        WHERE n.name=$1 AND r.kind='lxc' AND r.external_id=$2 AND s.name=$3""",
        str(values["node"]),
        str(values["vmid"]),
        str(values["snapname"]),
    )
    if row is None:
        raise ApiError(404, "snapshot does not exist")
    return row
