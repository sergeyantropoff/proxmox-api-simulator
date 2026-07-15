"""Worker semantics for backup/vzdump tasks."""

from __future__ import annotations

import json
from typing import Any

from app.simulation.clock import Clock
from app.simulation.seed import stable_id
from app.tasks.repository import Task, TaskRepository
from app.tasks.worker import TaskHandler


def backup_handler(repository: TaskRepository, clock: Clock) -> TaskHandler:
    async def execute(task: Task) -> dict[str, Any]:
        if task.task_type == "aptupdate":
            node = str(task.payload.get("node", "unknown"))
            await repository.append_log(task.id, f"starting apt update on {node}")
            await clock.sleep(1.0)
            async with repository.pool.acquire() as connection:
                metadata = await connection.fetchval(
                    "SELECT metadata FROM nodes WHERE name=$1",
                    node,
                )
                if metadata is not None:
                    payload = json.loads(metadata) if isinstance(metadata, str) else dict(metadata)
                    ops = payload.setdefault("ops", {})
                    apt = ops.setdefault("apt", {})
                    packages = list(apt.get("packages") or [])
                    for package in packages:
                        if isinstance(package, dict) and package.get("Status") == "upgradable":
                            package["Status"] = "installed"
                            if package.get("Version"):
                                package["OldVersion"] = package["Version"]
                    apt["packages"] = packages
                    apt["update"] = {"status": "stopped", "exitstatus": "OK"}
                    payload["ops"] = ops
                    await connection.execute(
                        "UPDATE nodes SET metadata=$2::jsonb, updated_at=now() WHERE name=$1",
                        node,
                        json.dumps(payload, sort_keys=True),
                    )
            await repository.append_log(task.id, "apt update finished")
            return {"status": "OK"}

        node = str(task.payload["node"])
        vmids = [str(item) for item in task.payload.get("vmids", [])]
        storage_id = str(task.payload.get("storage") or "nfs-backup")
        await repository.append_log(task.id, f"starting vzdump on {node} for {len(vmids)} guests")
        async with repository.pool.acquire() as connection:
            storage_resource_id = await connection.fetchval(
                "SELECT resource_id FROM storages WHERE storage_id=$1",
                storage_id,
            )
            if storage_resource_id is None:
                raise ValueError(f"storage {storage_id} does not exist")
            created = 0
            for index, vmid in enumerate(vmids):
                resource_id = await connection.fetchval(
                    """SELECT r.id FROM resources r JOIN nodes n ON n.id=r.node_id
                    WHERE n.name=$1 AND r.kind='qemu' AND r.external_id=$2""",
                    node,
                    vmid,
                )
                volume_id = f"backup/vzdump-qemu-{vmid}-{task.id.hex[:8]}-{index:04d}.vma.zst"
                await connection.execute(
                    """INSERT INTO backups(
                        id, resource_id, storage_resource_id, volume_id, size_bytes, metadata
                    ) VALUES($1, $2, $3, $4, $5, $6::jsonb)
                    ON CONFLICT (storage_resource_id, volume_id) DO NOTHING""",
                    stable_id(f"backup-task:{task.id}:{vmid}"),
                    resource_id,
                    storage_resource_id,
                    volume_id,
                    (8 + index) * 1024**3,
                    json.dumps(
                        {"mode": task.payload.get("mode", "snapshot"), "type": "vzdump"},
                        sort_keys=True,
                    ),
                )
                created += 1
                await repository.append_log(task.id, f"backup archive created: {volume_id}")
        await repository.append_log(task.id, f"vzdump finished ({created} archives)")
        return {"created": created}

    return execute
