"""Deterministic idempotent simulation seed profiles."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import asyncpg  # type: ignore[import-untyped]
from asyncpg import Connection

from app.security.auth import hash_secret

NAMESPACE = uuid.UUID("c9040a72-b391-4a7e-9864-3ae46291a531")


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
        f"UPID:pve1:0000000{index}:0000000{index}:6500000{index}:"
        f"{task_type}:{resource_id}:root@pam:",
        task_type,
        {"resource_id": resource_id, "seeded": True},
    )


def small_profile() -> SeedProfile:
    node = _node("pve1")
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
    raise ValueError(f"unknown seed profile: {name}")


async def apply_seed(connection: Connection, profile: SeedProfile) -> None:
    async with connection.transaction():
        await connection.execute(
            """DELETE FROM task_logs;
            DELETE FROM task_events;
            DELETE FROM resource_locks;
            DELETE FROM tasks;
            DELETE FROM pool_members;
            DELETE FROM pools;
            DELETE FROM resources;
            DELETE FROM nodes"""
        )
        await connection.executemany(
            "INSERT INTO nodes(id, name, status) VALUES($1, $2, $3)",
            [(node.id, node.name, node.status) for node in profile.nodes],
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
                    resource_id, cluster_id, storage_id, storage_type, shared, config
                ) VALUES($1, 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f', $2, $3, $4, $5::jsonb)""",
                [
                    (
                        resource.id,
                        resource.external_id,
                        "dir" if resource.external_id.startswith("local") else "nfs",
                        bool(resource.state.get("shared", False)),
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
