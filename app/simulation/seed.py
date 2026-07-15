"""Deterministic idempotent simulation seed profiles."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import asyncpg  # type: ignore[import-untyped]
from asyncpg import Connection

from app.security.auth import hash_secret

NAMESPACE = uuid.UUID("c9040a72-b391-4a7e-9864-3ae46291a531")
CLUSTER_ID = uuid.UUID("dc760c47-d8d7-57e6-9404-f0c6f2395d8f")


def default_node_ops_for_seed(node_name: str) -> dict[str, object]:
    from app.handlers.nodes import default_node_ops

    ops = default_node_ops()
    # Distinct but deterministic bridge addresses per node name.
    suffix = (stable_id(f"node-ip:{node_name}").int % 200) + 10
    network = ops.get("network")
    if isinstance(network, list):
        for item in network:
            if not isinstance(item, dict):
                continue
            if item.get("iface") == "vmbr0":
                item["address"] = f"10.0.0.{suffix}/24"
            elif item.get("iface") == "vmbr1":
                item["address"] = f"10.10.0.{suffix}/24"
    return ops


@dataclass(frozen=True, slots=True)
class SeedNode:
    id: uuid.UUID
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class SeedResource:
    id: uuid.UUID
    node_id: uuid.UUID
    kind: str
    external_id: str
    state: dict[str, object]


@dataclass(frozen=True, slots=True)
class SeedTask:
    id: uuid.UUID
    upid: str
    task_type: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class SeedProfile:
    name: str
    nodes: tuple[SeedNode, ...]
    resources: tuple[SeedResource, ...]
    tasks: tuple[SeedTask, ...] = ()

    def logical_state(self) -> dict[str, object]:
        nodes = [{"name": node.name, "status": node.status} for node in self.nodes]
        names = {node.id: node.name for node in self.nodes}
        resources = [
            {
                "kind": resource.kind,
                "external_id": resource.external_id,
                "node": names[resource.node_id],
                "state": resource.state,
            }
            for resource in self.resources
        ]
        tasks = [
            {"upid": task.upid, "task_type": task.task_type, "status": "success"}
            for task in self.tasks
        ]
        return {"profile": self.name, "nodes": nodes, "resources": resources, "tasks": tasks}


def stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


def _string_list(state: dict[str, object], key: str) -> tuple[str, ...]:
    value = state.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"seed state {key} must be a string list")
    return tuple(value)


def _node(name: str, status: str = "online") -> SeedNode:
    return SeedNode(stable_id(f"node:{name}"), name, status)


def _resource(
    node: SeedNode, kind: str, external_id: str, state: dict[str, object]
) -> SeedResource:
    return SeedResource(stable_id(f"{kind}:{external_id}"), node.id, kind, external_id, state)


def _completed_task(index: int, task_type: str, resource_id: str) -> SeedTask:
    return SeedTask(
        stable_id(f"task:{index}:{task_type}:{resource_id}"),
        f"UPID:pve01:0000000{index}:0000000{index}:6500000{index}:"
        f"{task_type}:{resource_id}:root@pam:",
        task_type,
        {"resource_id": resource_id, "seeded": True},
    )


def small_profile() -> SeedProfile:
    node = _node("pve01")
    resources = (
        _resource(node, "qemu", "100", {"name": "demo", "status": "stopped"}),
        _resource(node, "qemu", "101", {"name": "worker", "status": "stopped"}),
        _resource(node, "lxc", "200", {"name": "service", "status": "stopped"}),
        _resource(node, "storage", "local", {"content": ["iso", "backup"], "status": "available"}),
        _resource(
            node, "storage", "local-lvm", {"content": ["images", "rootdir"], "status": "available"}
        ),
    )
    tasks = (_completed_task(1, "qmstart", "100"), _completed_task(2, "qmstop", "100"))
    return SeedProfile("small", (node,), resources, tasks)


def medium_profile() -> SeedProfile:
    nodes = tuple(_node(f"pve{index}") for index in range(1, 4))
    resources: list[SeedResource] = []
    for vmid in range(100, 150):
        node = nodes[(vmid - 100) % len(nodes)]
        resources.append(
            _resource(node, "qemu", str(vmid), {"name": f"vm-{vmid}", "status": "stopped"})
        )
    for vmid in range(200, 220):
        node = nodes[(vmid - 200) % len(nodes)]
        resources.append(
            _resource(node, "lxc", str(vmid), {"name": f"ct-{vmid}", "status": "stopped"})
        )
    for node in nodes:
        resources.append(
            _resource(
                node,
                "storage",
                f"local-{node.name}",
                {"content": ["images"], "shared": False, "status": "available"},
            )
        )
    resources.append(
        _resource(
            nodes[0],
            "storage",
            "shared",
            {"content": ["images", "backup"], "shared": True, "status": "available"},
        )
    )
    resources.append(_resource(nodes[0], "pool", "development", {"members": ["100", "101", "200"]}))
    tasks = tuple(_completed_task(index, "qmstart", str(99 + index)) for index in range(1, 11))
    return SeedProfile("medium", nodes, tuple(resources), tasks)


def large_profile(*, node_count: int = 10, resource_count: int = 10_000) -> SeedProfile:
    if node_count < 1 or resource_count < 1:
        raise ValueError("large profile counts must be positive")
    nodes = tuple(_node(f"pve{index}") for index in range(1, node_count + 1))
    resources = tuple(
        _resource(
            nodes[index % node_count],
            "qemu" if index % 4 else "lxc",
            str(100 + index),
            {"name": f"guest-{100 + index}", "status": "stopped"},
        )
        for index in range(resource_count)
    )
    return SeedProfile("large", nodes, resources)


def ha_demo_profile() -> SeedProfile:
    profile = medium_profile()
    resources = (
        *profile.resources,
        _resource(profile.nodes[0], "ha", "vm:100", {"state": "started", "group": "primary"}),
    )
    return SeedProfile("ha-demo", profile.nodes, resources, profile.tasks)


def minimal_profile() -> SeedProfile:
    node = _node("pve01")
    resources = (
        _resource(node, "storage", "local", {"content": ["iso", "backup"], "status": "available"}),
        _resource(
            node, "storage", "local-lvm", {"content": ["images", "rootdir"], "status": "available"}
        ),
    )
    return SeedProfile("minimal", (node,), resources)


def broken_storage_profile() -> SeedProfile:
    profile = small_profile()
    resources = tuple(
        _resource(
            next(node for node in profile.nodes if node.id == resource.node_id),
            resource.kind,
            resource.external_id,
            {**resource.state, "status": "offline", "error": "simulated I/O failure"}
            if resource.kind == "storage" and resource.external_id == "local-lvm"
            else resource.state,
        )
        for resource in profile.resources
    )
    return SeedProfile("broken-storage", profile.nodes, resources, profile.tasks)


def build_profile(
    name: str, *, large_nodes: int = 10, large_resources: int = 10_000
) -> SeedProfile:
    if name == "small":
        return small_profile()
    if name == "medium":
        return medium_profile()
    if name == "large":
        return large_profile(node_count=large_nodes, resource_count=large_resources)
    if name == "ha-demo":
        return ha_demo_profile()
    if name == "broken-storage":
        return broken_storage_profile()
    if name == "minimal":
        return minimal_profile()
    if name == "demo-cluster":
        from app.simulation.demo_cluster import demo_cluster_profile

        return demo_cluster_profile()
    raise ValueError(f"unknown seed profile: {name}")


def _storage_type(resource: SeedResource) -> str:
    configured = resource.state.get("storage_type")
    if isinstance(configured, str) and configured:
        return configured
    if resource.external_id.startswith("local"):
        if "lvm" in resource.external_id:
            return "lvmthin"
        if "zfs" in resource.external_id:
            return "zfspool"
        return "dir"
    if resource.external_id.startswith("ceph"):
        return "ceph"
    if resource.external_id.startswith("nfs"):
        return "nfs"
    return "dir"


def _storage_capacity(resource: SeedResource) -> tuple[int | None, int | None]:
    total = resource.state.get("total_bytes", resource.state.get("capacity_bytes"))
    used = resource.state.get("used_bytes")
    total_bytes = int(total) if isinstance(total, int) else None
    used_bytes = int(used) if isinstance(used, int) else None
    return total_bytes, used_bytes


async def clear_simulation_state(connection: Connection) -> None:
    """Remove all mutable simulator state so a seed/reset never fails on leftovers.

    API-created guests, storages, users, groups, roles, ACL/tokens and custom
    realms must not block "Remove demo data" / reseed. Builtin auth realms
    (`pam`, `pve`, `test`) are kept because principals reference them.
    """
    for statement in (
        "DELETE FROM task_logs",
        "DELETE FROM task_events",
        "DELETE FROM resource_locks",
        "DELETE FROM tasks",
        "DELETE FROM pool_members",
        "DELETE FROM backups",
        "DELETE FROM snapshots",
        "DELETE FROM storage_contents",
        "DELETE FROM vm_disks",
        "DELETE FROM vm_network_interfaces",
        "DELETE FROM virtual_machines",
        "DELETE FROM containers",
        "DELETE FROM storages",
        "DELETE FROM pools",
        "DELETE FROM resources",
        "DELETE FROM nodes",
        "DELETE FROM openid_pending",
        "DELETE FROM tfa_entries",
        "DELETE FROM group_acl_entries",
        "DELETE FROM identity_group_members",
        "DELETE FROM acl_entries",
        "DELETE FROM api_tokens",
        "DELETE FROM auth_tickets",
        "DELETE FROM identity_groups",
        "DELETE FROM principals",
        "DELETE FROM roles",
        "DELETE FROM realms WHERE name NOT IN ('pam', 'pve', 'test')",
        "DELETE FROM fault_injections",
        "DELETE FROM scenario_rules",
        "DELETE FROM audit_events",
    ):
        await connection.execute(statement)
    await connection.execute(
        """UPDATE clusters
        SET name = 'pve-simulator',
            metadata = '{}'::jsonb,
            updated_at = now()
        WHERE id = $1""",
        CLUSTER_ID,
    )


async def simulation_state_summary(connection: Connection) -> dict[str, object]:
    row = await connection.fetchrow(
        """SELECT
            c.name AS cluster_name,
            COALESCE(c.metadata->>'profile', 'unknown') AS profile,
            (SELECT count(*)::int FROM nodes) AS nodes,
            (SELECT count(*)::int FROM resources WHERE kind = 'qemu') AS qemu,
            (SELECT count(*)::int FROM resources WHERE kind = 'lxc') AS lxc,
            (SELECT count(*)::int FROM resources WHERE kind = 'ceph-osd') AS ceph_osds,
            (SELECT count(*)::int FROM resources WHERE kind = 'storage') AS storages,
            (SELECT count(*)::int FROM backups) AS backups,
            (SELECT count(*)::int FROM tasks) AS tasks,
            (SELECT count(*)::int FROM task_logs) AS task_logs,
            (SELECT count(*)::int FROM snapshots) AS snapshots,
            (SELECT count(*)::int FROM principals) AS principals,
            COALESCE(
                (SELECT sum(capacity_bytes)::bigint FROM storages WHERE storage_type = 'ceph'),
                0
            ) AS ceph_capacity_bytes
        FROM clusters c
        WHERE c.id = $1""",
        CLUSTER_ID,
    )
    if row is None:
        return {"profile": "unknown", "loaded": False}
    payload = dict(row)
    payload["loaded"] = payload["profile"] == "demo-cluster"
    payload["ceph_capacity_pib"] = round((payload.get("ceph_capacity_bytes") or 0) / 1024**5, 2)
    return payload


async def apply_seed(connection: Connection, profile: SeedProfile) -> None:
    async with connection.transaction():
        await clear_simulation_state(connection)
        await connection.execute(
            """UPDATE clusters
            SET name = $2,
                metadata = $3::jsonb,
                updated_at = now()
            WHERE id = $1""",
            CLUSTER_ID,
            "prod-pve-cluster" if profile.name == "demo-cluster" else "pve-simulator",
            json.dumps(
                {
                    "profile": profile.name,
                    "nodes": len(profile.nodes),
                    "resources": len(profile.resources),
                },
                sort_keys=True,
            ),
        )
        await connection.executemany(
            "INSERT INTO nodes(id, name, status, metadata) VALUES($1, $2, $3, $4::jsonb)",
            [
                (
                    node.id,
                    node.name,
                    node.status,
                    json.dumps({"ops": default_node_ops_for_seed(node.name)}, sort_keys=True),
                )
                for node in profile.nodes
            ],
        )
        await connection.executemany(
            """INSERT INTO resources(id, node_id, kind, external_id, state)
            VALUES($1, $2, $3, $4, $5::jsonb)""",
            [
                (
                    resource.id,
                    resource.node_id,
                    resource.kind,
                    resource.external_id,
                    json.dumps(resource.state, sort_keys=True),
                )
                for resource in profile.resources
            ],
        )
        qemu = [resource for resource in profile.resources if resource.kind == "qemu"]
        if qemu:
            await connection.executemany(
                """INSERT INTO virtual_machines(resource_id, cluster_id, vmid, config)
                VALUES($1, 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f', $2, $3::jsonb)""",
                [
                    (
                        resource.id,
                        int(resource.external_id),
                        json.dumps(resource.state, sort_keys=True),
                    )
                    for resource in qemu
                ],
            )
        containers = [resource for resource in profile.resources if resource.kind == "lxc"]
        if containers:
            await connection.executemany(
                """INSERT INTO containers(resource_id, cluster_id, vmid, config)
                VALUES($1, 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f', $2, $3::jsonb)""",
                [
                    (
                        resource.id,
                        int(resource.external_id),
                        json.dumps(resource.state, sort_keys=True),
                    )
                    for resource in containers
                ],
            )
        storages = [resource for resource in profile.resources if resource.kind == "storage"]
        if storages:
            await connection.executemany(
                """INSERT INTO storages(
                    resource_id, cluster_id, storage_id, storage_type, shared,
                    capacity_bytes, used_bytes, config
                ) VALUES($1, $2, $3, $4, $5, $6, $7, $8::jsonb)""",
                [
                    (
                        resource.id,
                        str(CLUSTER_ID),
                        resource.external_id,
                        _storage_type(resource),
                        bool(resource.state.get("shared", False)),
                        *_storage_capacity(resource),
                        json.dumps(resource.state, sort_keys=True),
                    )
                    for resource in storages
                ],
            )
            contents = [
                (
                    stable_id(f"content:{resource.external_id}:{content}"),
                    resource.id,
                    f"{resource.external_id}:{content}/seeded",
                    str(content),
                )
                for resource in storages
                for content in _string_list(resource.state, "content")
            ]
            if contents:
                await connection.executemany(
                    """INSERT INTO storage_contents(
                        id, storage_resource_id, volume_id, content_type
                    ) VALUES($1, $2, $3, $4)""",
                    contents,
                )
        pools = [resource for resource in profile.resources if resource.kind == "pool"]
        if pools:
            await connection.executemany(
                """INSERT INTO pools(id, cluster_id, pool_id, metadata)
                VALUES($1, 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f', $2, $3::jsonb)""",
                [
                    (resource.id, resource.external_id, json.dumps(resource.state, sort_keys=True))
                    for resource in pools
                ],
            )
            members = [
                (pool.id, member.id)
                for pool in pools
                for external_id in _string_list(pool.state, "members")
                for member in profile.resources
                if member.external_id == external_id and member.kind in {"qemu", "lxc"}
            ]
            if members:
                await connection.executemany(
                    "INSERT INTO pool_members(pool_id, resource_id) VALUES($1, $2)", members
                )
        if profile.tasks:
            await connection.executemany(
                """INSERT INTO tasks(id, upid, status, payload, task_type, progress, result)
                VALUES($1, $2, 'success', $3::jsonb, $4, 100, '{\"seeded\":true}'::jsonb)""",
                [
                    (task.id, task.upid, json.dumps(task.payload, sort_keys=True), task.task_type)
                    for task in profile.tasks
                ],
            )
        await connection.execute(
            """INSERT INTO principals(id, name, password_hash, realm_name)
            VALUES($1, 'root@pam', $2, 'pam')
            ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
            realm_name=EXCLUDED.realm_name""",
            stable_id("principal:root@pam"),
            hash_secret("secret", salt=b"pve-simulator-v1"),
        )
        await connection.execute(
            """INSERT INTO api_tokens(principal_id, token_id, secret_hash, privileges)
            VALUES($1, 'automation', $2, $3)
            ON CONFLICT (principal_id, token_id) DO UPDATE
            SET secret_hash=EXCLUDED.secret_hash, privileges=EXCLUDED.privileges""",
            stable_id("principal:root@pam"),
            hash_secret("automation-secret", salt=b"pve-token-seed-v1"),
            ["VM.Audit", "VM.PowerMgmt", "Sys.Audit"],
        )
        auditor_id = stable_id("principal:auditor@pve")
        await connection.execute(
            """INSERT INTO principals(id, name, password_hash, realm_name)
            VALUES($1, 'auditor@pve', $2, 'pve')
            ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
            realm_name=EXCLUDED.realm_name""",
            auditor_id,
            hash_secret("auditor-secret", salt=b"pve-auditor-v1"),
        )
        await connection.execute(
            """INSERT INTO roles(name, privileges)
            VALUES('PVEAuditor', $1)
            ON CONFLICT (name) DO UPDATE SET privileges=EXCLUDED.privileges""",
            ["Sys.Audit", "VM.Audit"],
        )
        await connection.execute(
            "DELETE FROM acl_entries WHERE principal_id=$1 AND role_name='PVEAuditor'",
            auditor_id,
        )
        auditor_group_id = await connection.fetchval(
            """INSERT INTO identity_groups(id, group_id, comment)
            VALUES($1, 'auditors', 'Read-only operators')
            ON CONFLICT (group_id) DO UPDATE SET comment=EXCLUDED.comment
            RETURNING id""",
            stable_id("group:auditors"),
        )
        await connection.execute(
            """INSERT INTO identity_group_members(group_id, principal_id)
            VALUES($1, $2) ON CONFLICT DO NOTHING""",
            auditor_group_id,
            auditor_id,
        )
        await connection.execute(
            """INSERT INTO group_acl_entries(group_id, role_name, path, propagate)
            VALUES($1, 'PVEAuditor', '/', true)
            ON CONFLICT (group_id, role_name, path) DO UPDATE
            SET propagate=EXCLUDED.propagate""",
            auditor_group_id,
        )
        await connection.execute(
            """INSERT INTO api_tokens(principal_id, token_id, secret_hash, privileges)
            VALUES($1, 'readonly', $2, $3)
            ON CONFLICT (principal_id, token_id) DO UPDATE
            SET secret_hash=EXCLUDED.secret_hash, privileges=EXCLUDED.privileges""",
            auditor_id,
            hash_secret("readonly-secret", salt=b"pve-readonly-v1"),
            ["Sys.Audit", "VM.Audit"],
        )
        for username, role_name, privileges, acl_path, token_id, token_secret in (
            (
                "operator@pve",
                "PVEVMOperator",
                ["VM.Audit", "VM.PowerMgmt"],
                "/vms",
                "operator",
                "operator-secret",
            ),
            (
                "storage@pve",
                "PVEStorageUser",
                ["Datastore.Audit", "Datastore.AllocateSpace"],
                "/storage",
                "storage",
                "storage-secret",
            ),
        ):
            principal_id = stable_id(f"principal:{username}")
            await connection.execute(
                """INSERT INTO principals(id, name, password_hash, realm_name)
                VALUES($1, $2, $3, 'pve')
                ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
                realm_name=EXCLUDED.realm_name""",
                principal_id,
                username,
                hash_secret(f"{username}-password", salt=f"seed:{username}".encode()),
            )
            await connection.execute(
                """INSERT INTO roles(name, privileges) VALUES($1, $2)
                ON CONFLICT (name) DO UPDATE SET privileges=EXCLUDED.privileges""",
                role_name,
                privileges,
            )
            await connection.execute(
                """INSERT INTO acl_entries(principal_id, role_name, path, propagate)
                VALUES($1, $2, $3, true)
                ON CONFLICT (principal_id, role_name, path) DO UPDATE
                SET propagate=EXCLUDED.propagate""",
                principal_id,
                role_name,
                acl_path,
            )
            await connection.execute(
                """INSERT INTO api_tokens(principal_id, token_id, secret_hash, privileges)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (principal_id, token_id) DO UPDATE
                SET secret_hash=EXCLUDED.secret_hash, privileges=EXCLUDED.privileges,
                privilege_separation=true""",
                principal_id,
                token_id,
                hash_secret(token_secret, salt=f"token:{username}".encode()),
                privileges,
            )
        if profile.name == "demo-cluster":
            await _apply_demo_cluster_extras(connection, profile)


async def _apply_demo_cluster_extras(connection: Connection, profile: SeedProfile) -> None:
    names = {node.id: node.name for node in profile.nodes}
    guests = [resource for resource in profile.resources if resource.kind in {"qemu", "lxc"}]

    disks: list[tuple[uuid.UUID, uuid.UUID, str, str, int, str]] = []
    for index, resource in enumerate(guests):
        node_name = names[resource.node_id]
        disk_count = 1 + (index % 3)
        for disk_index in range(disk_count):
            device = "rootfs" if resource.kind == "lxc" and disk_index == 0 else f"scsi{disk_index}"
            storage_id = "ceph-prod" if (index + disk_index) % 4 == 0 else f"local-lvm-{node_name}"
            size_bytes = (20 + (index % 9) * 10 + disk_index * 15) * 1024**3
            disks.append(
                (
                    stable_id(f"disk:{resource.external_id}:{device}"),
                    resource.id,
                    device,
                    storage_id,
                    size_bytes,
                    json.dumps({"format": "raw" if disk_index else "qcow2"}, sort_keys=True),
                )
            )
    if disks:
        await connection.executemany(
            """INSERT INTO vm_disks(id, resource_id, device, storage_id, size_bytes, metadata)
            VALUES($1, $2, $3, $4, $5, $6::jsonb)""",
            disks,
        )

    interfaces: list[tuple[uuid.UUID, uuid.UUID, str, str]] = []
    for index, resource in enumerate(guests):
        interfaces.append(
            (
                stable_id(f"net:{resource.external_id}:net0"),
                resource.id,
                "net0",
                json.dumps(
                    {
                        "bridge": "vmbr0",
                        "firewall": index % 7 != 0,
                        "tag": (index % 12) * 10 or None,
                    },
                    sort_keys=True,
                ),
            )
        )
        if index % 5 == 0:
            interfaces.append(
                (
                    stable_id(f"net:{resource.external_id}:net1"),
                    resource.id,
                    "net1",
                    json.dumps({"bridge": "vmbr1", "firewall": True}, sort_keys=True),
                )
            )
    if interfaces:
        await connection.executemany(
            """INSERT INTO vm_network_interfaces(id, resource_id, device, config)
            VALUES($1, $2, $3, $4::jsonb)""",
            interfaces,
        )

    snapshots: list[tuple[uuid.UUID, uuid.UUID, str, str | None, str, str]] = []
    for index, resource in enumerate(guests):
        if index % 7 != 0:
            continue
        for snap_index in range(1 + (index % 3)):
            snap_name = f"snap-{snap_index:02d}"
            snapshots.append(
                (
                    stable_id(f"snapshot:{resource.external_id}:{snap_name}"),
                    resource.id,
                    snap_name,
                    None if snap_index == 0 else f"snap-{snap_index - 1:02d}",
                    f"Automated snapshot #{snap_index}",
                    json.dumps({"vmstate": index % 2 == 0}, sort_keys=True),
                )
            )
    if snapshots:
        await connection.executemany(
            """INSERT INTO snapshots(id, resource_id, name, parent_name, description, state)
            VALUES($1, $2, $3, $4, $5, $6::jsonb)""",
            snapshots,
        )

    storage_rows = await connection.fetch(
        """SELECT s.resource_id, s.storage_id, n.name AS node_name
        FROM storages s
        JOIN resources r ON r.id = s.resource_id
        JOIN nodes n ON n.id = r.node_id
        WHERE s.storage_id LIKE 'backup-%' OR s.storage_id IN ('ceph-prod', 'nfs-backup')"""
    )
    storage_by_id = {row["storage_id"]: row["resource_id"] for row in storage_rows}
    storage_by_node = {
        str(row["node_name"]): row["resource_id"]
        for row in storage_rows
        if str(row["storage_id"]).startswith("backup-")
    }
    fallback_backup = storage_by_id.get("nfs-backup") or storage_by_id.get("ceph-prod")
    if fallback_backup is not None:
        backups: list[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, str, int, str]] = []
        qemu_guests = [resource for resource in guests if resource.kind == "qemu"]
        for index, resource in enumerate(qemu_guests):
            node_name = names[resource.node_id]
            backup_storage = storage_by_node.get(node_name, fallback_backup)
            volume_id = f"backup/vzdump-qemu-{resource.external_id}-2026_07_15-{index:04d}.vma.zst"
            backups.append(
                (
                    stable_id(f"backup:{resource.external_id}:{index}"),
                    resource.id,
                    backup_storage,
                    volume_id,
                    (8 + (index % 40)) * 1024**3,
                    json.dumps(
                        {
                            "mode": "snapshot" if index % 3 else "suspend",
                            "notes-template": "Daily backup",
                            "node": node_name,
                        },
                        sort_keys=True,
                    ),
                )
            )
        if backups:
            await connection.executemany(
                """INSERT INTO backups(
                    id, resource_id, storage_resource_id, volume_id, size_bytes, metadata
                ) VALUES($1, $2, $3, $4, $5, $6::jsonb)""",
                backups,
            )

    guest_list = sorted(
        guests, key=lambda resource: (names[resource.node_id], resource.external_id)
    )
    extra_tasks: list[tuple[uuid.UUID, str, str, str, str]] = []
    for index in range(251, 321):
        guest = guest_list[(index - 251) % len(guest_list)]
        node_name = names[guest.node_id]
        node = next(node for node in profile.nodes if node.name == node_name)
        task_type = ("vzdump", "qmmigrate", "qmstart", "cephosd")[index % 4]
        status = "running" if index % 17 == 0 else "error" if index % 23 == 0 else "success"
        extra_tasks.append(
            (
                stable_id(f"demo-task-extra:{index}"),
                f"UPID:{node.name}:{index:07X}:{index:07X}:68{index:06X}:"
                f"{task_type}:{guest.external_id}:operator@pve:",
                status,
                json.dumps(
                    {"resource_id": guest.external_id, "node": node.name},
                    sort_keys=True,
                ),
                task_type,
            )
        )
    if extra_tasks:
        await connection.executemany(
            """INSERT INTO tasks(id, upid, status, payload, task_type, progress, result, error)
            VALUES($1, $2, $3, $4::jsonb, $5,
                CASE WHEN $3 = 'success' THEN 100 WHEN $3 = 'running' THEN 45 ELSE 0 END,
                CASE WHEN $3 = 'success' THEN '{\"seeded\":true}'::jsonb ELSE NULL END,
                CASE WHEN $3 = 'error' THEN 'simulated backup failure' ELSE NULL END)""",
            extra_tasks,
        )

    task_rows = await connection.fetch(
        "SELECT id, task_type, payload FROM tasks ORDER BY upid LIMIT 180"
    )
    logs: list[tuple[uuid.UUID, str]] = []
    for task in task_rows:
        payload = task["payload"]
        if isinstance(payload, dict):
            resource_id = payload.get("resource_id", "unknown")
            node_label = payload.get("node", "pve01")
        else:
            resource_id = "unknown"
            node_label = "unknown"
        messages: tuple[str, ...] = (
            f"starting task {task['task_type']} on {node_label}",
            f"processing guest {resource_id}",
            f"task {task['task_type']} finished successfully",
        )
        if task["task_type"] == "vzdump":
            messages = (
                f"INFO: starting backup of VM {resource_id} on {node_label}",
                f"INFO: snapshot create VM {resource_id}",
                f"INFO: archive file size: {(8 + hash(str(task['id'])) % 40)}GB",
                "INFO: Backup finished successfully",
            )
        logs.extend((task["id"], message) for message in messages)
    if logs:
        await connection.executemany(
            "INSERT INTO task_logs(task_id, message) VALUES($1, $2)",
            logs,
        )

    demo_users = (
        ("admin@pve", "PVEAdmin", ["/"], ["Sys.Modify", "Sys.Audit", "Datastore.Allocate"]),
        ("devops@pve", "PVEAdmin", ["/vms"], ["Sys.Audit", "VM.Allocate", "VM.PowerMgmt"]),
        (
            "backup-operator@pve",
            "PVEDatastoreAdmin",
            ["/storage"],
            ["Datastore.Allocate", "Datastore.Audit"],
        ),
        ("ceph-monitor@pve", "PVEAuditor", ["/"], ["Sys.Audit", "Datastore.Audit"]),
        ("junior@pve", "PVEAuditor", ["/vms"], ["Sys.Audit", "VM.Audit"]),
        ("security@pve", "PVEAuditor", ["/access"], ["Sys.Audit", "User.Modify"]),
    )
    for username, role_name, acl_paths, privileges in demo_users:
        principal_id = stable_id(f"principal:{username}")
        await connection.execute(
            """INSERT INTO principals(id, name, password_hash, realm_name)
            VALUES($1, $2, $3, 'pve')
            ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
            realm_name=EXCLUDED.realm_name""",
            principal_id,
            username,
            hash_secret(f"{username}-password", salt=f"seed:{username}".encode()),
        )
        await connection.execute(
            """INSERT INTO roles(name, privileges) VALUES($1, $2)
            ON CONFLICT (name) DO UPDATE SET privileges=EXCLUDED.privileges""",
            role_name,
            privileges,
        )
        for acl_path in acl_paths:
            await connection.execute(
                """INSERT INTO acl_entries(principal_id, role_name, path, propagate)
                VALUES($1, $2, $3, true)
                ON CONFLICT (principal_id, role_name, path) DO UPDATE
                SET propagate=EXCLUDED.propagate""",
                principal_id,
                role_name,
                acl_path,
            )


async def seed_url(
    database_url: str,
    profile_name: str = "small",
    *,
    large_nodes: int = 10,
    large_resources: int = 10_000,
) -> dict[str, object]:
    connection = await asyncpg.connect(database_url)
    try:
        profile = build_profile(
            profile_name, large_nodes=large_nodes, large_resources=large_resources
        )
        await apply_seed(connection, profile)
        return profile.logical_state()
    finally:
        await connection.close()
