"""Typed resource persistence with explicit optimistic locking."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from asyncpg import Pool  # type: ignore[import-untyped]

from app.db.primitives import ConflictError, transaction


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    id: uuid.UUID
    cluster_id: uuid.UUID
    node: str
    kind: str
    external_id: str
    state: dict[str, Any]
    metadata: dict[str, Any]
    version: int


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        return cast(dict[str, Any], json.loads(value))
    return dict(cast(Mapping[str, Any], value))


def _record(row: Mapping[str, object]) -> ResourceRecord:
    return ResourceRecord(
        id=cast(uuid.UUID, row["id"]),
        cluster_id=cast(uuid.UUID, row["cluster_id"]),
        node=str(row["node"]),
        kind=str(row["kind"]),
        external_id=str(row["external_id"]),
        state=_json_object(row["state"]),
        metadata=_json_object(row["metadata"]),
        version=int(cast(int, row["version"])),
    )


class ResourceRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def list(
        self, *, kind: str | None = None, node: str | None = None
    ) -> list[ResourceRecord]:
        rows = await self._pool.fetch(
            """SELECT r.id, r.cluster_id, n.name AS node, r.kind, r.external_id,
            r.state, r.metadata, r.version
            FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE ($1::text IS NULL OR r.kind=$1)
              AND ($2::text IS NULL OR n.name=$2)
            ORDER BY r.kind, r.external_id""",
            kind,
            node,
        )
        return [_record(row) for row in rows]

    async def get(self, *, kind: str, external_id: str) -> ResourceRecord | None:
        row = await self._pool.fetchrow(
            """SELECT r.id, r.cluster_id, n.name AS node, r.kind, r.external_id,
            r.state, r.metadata, r.version
            FROM resources r JOIN nodes n ON n.id=r.node_id
            WHERE r.kind=$1 AND r.external_id=$2""",
            kind,
            external_id,
        )
        return None if row is None else _record(row)

    async def update_state(
        self,
        resource_id: uuid.UUID,
        *,
        expected_version: int,
        state: Mapping[str, object],
    ) -> ResourceRecord:
        async with transaction(self._pool) as connection:
            row = await connection.fetchrow(
                """UPDATE resources SET state=$3::jsonb, version=version+1,
                updated_at=now() WHERE id=$1 AND version=$2
                RETURNING id, cluster_id,
                    (SELECT name FROM nodes WHERE id=resources.node_id) AS node,
                    kind, external_id, state, metadata, version""",
                resource_id,
                expected_version,
                json.dumps(dict(state), sort_keys=True),
            )
            if row is None:
                raise ConflictError("resource version conflict or resource missing")
            return _record(row)
