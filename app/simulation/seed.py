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
class SeedProfile:
    name: str
    nodes: tuple[SeedNode, ...]
    resources: tuple[SeedResource, ...]

    def logical_state(self) -> dict[str, object]:
        nodes = [{"name": node.name, "status": node.status} for node in self.nodes]
        resources = [
            {
                "kind": resource.kind,
                "external_id": resource.external_id,
                "node": next(node.name for node in self.nodes if node.id == resource.node_id),
                "state": resource.state,
            }
            for resource in self.resources
        ]
        return {"profile": self.name, "nodes": nodes, "resources": resources}


def stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


def small_profile() -> SeedProfile:
    first = SeedNode(stable_id("node:pve1"), "pve1", "online")
    second = SeedNode(stable_id("node:pve2"), "pve2", "online")
    resources = (
        SeedResource(
            stable_id("qemu:100"), first.id, "qemu", "100", {"name": "demo", "status": "stopped"}
        ),
        SeedResource(
            stable_id("qemu:101"),
            first.id,
            "qemu",
            "101",
            {"name": "worker", "status": "stopped"},
        ),
        SeedResource(
            stable_id("storage:local"), first.id, "storage", "local", {"content": ["iso", "backup"]}
        ),
    )
    return SeedProfile("small", (first, second), resources)


async def apply_seed(connection: Connection, profile: SeedProfile) -> None:
    async with connection.transaction():
        await connection.executemany(
            """INSERT INTO nodes(id, name, status) VALUES($1, $2, $3)
            ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, status=EXCLUDED.status""",
            [(node.id, node.name, node.status) for node in profile.nodes],
        )
        await connection.executemany(
            """INSERT INTO resources(id, node_id, kind, external_id, state)
            VALUES($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (id) DO UPDATE SET node_id=EXCLUDED.node_id,
            kind=EXCLUDED.kind, external_id=EXCLUDED.external_id, state=EXCLUDED.state""",
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
        await connection.execute(
            """INSERT INTO principals(id, name, password_hash, realm_name)
            VALUES($1, 'root@pam', $2, 'pam')
            ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
            realm_name=EXCLUDED.realm_name""",
            stable_id("principal:root@pam"),
            hash_secret("secret", salt=b"pve-simulator-v1"),
        )


async def seed_url(database_url: str) -> dict[str, object]:
    connection = await asyncpg.connect(database_url)
    try:
        profile = small_profile()
        await apply_seed(connection, profile)
        return profile.logical_state()
    finally:
        await connection.close()
