"""Resource pool semantic handlers."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import database, state, values
from app.simulation.seed import CLUSTER_ID, stable_id


async def _pool_members(request: Request, pool_id: uuid.UUID) -> list[str]:
    rows = await database(request).pool.fetch(
        """SELECT r.external_id FROM pool_members pm
        JOIN resources r ON r.id = pm.resource_id
        WHERE pm.pool_id=$1 ORDER BY r.external_id::integer""",
        pool_id,
    )
    return [str(row["external_id"]) for row in rows]


def register_pool_handlers(registry: HandlerRegistry) -> None:
    async def pool_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        payload = values(inputs)
        filter_poolid = payload.get("poolid")
        rows = await database(request).pool.fetch(
            """SELECT id, pool_id, comment, metadata FROM pools
            WHERE ($1::text IS NULL OR pool_id=$1)
            ORDER BY pool_id""",
            str(filter_poolid) if filter_poolid is not None else None,
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            metadata = state(row["metadata"])
            members = await _pool_members(request, row["id"])
            if not members and isinstance(metadata.get("members"), list):
                members = [str(item) for item in metadata["members"]]
            item: dict[str, Any] = {
                "poolid": str(row["pool_id"]),
                "members": members,
            }
            if row["comment"] is not None:
                item["comment"] = str(row["comment"])
            elif metadata.get("comment"):
                item["comment"] = str(metadata["comment"])
            result.append(item)
        return result

    async def pool_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        items = await pool_list(request, inputs)
        if not items:
            raise ApiError(404, "pool does not exist")
        return items[0]

    async def pool_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        poolid = str(payload["poolid"])
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pools WHERE pool_id=$1)",
            poolid,
        )
        if exists:
            raise ApiError(409, "pool already exists")
        await database(request).pool.execute(
            """INSERT INTO pools(id, cluster_id, pool_id, comment, metadata)
            VALUES($1, $2, $3, $4, $5::jsonb)""",
            stable_id(f"pool:{poolid}"),
            CLUSTER_ID,
            poolid,
            payload.get("comment"),
            json.dumps({"members": []}, sort_keys=True),
        )

    async def pool_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        poolid = str(payload["poolid"])
        pool_row = await database(request).pool.fetchrow(
            "SELECT id FROM pools WHERE pool_id=$1",
            poolid,
        )
        if pool_row is None:
            raise ApiError(404, "pool does not exist")
        if payload.get("comment") is not None:
            await database(request).pool.execute(
                "UPDATE pools SET comment=$2 WHERE pool_id=$1",
                poolid,
                payload.get("comment"),
            )
        if "vms" in payload:
            vmids = [item.strip() for item in str(payload["vms"]).split(",") if item.strip()]
            for vmid in vmids:
                resource = await database(request).pool.fetchrow(
                    """SELECT id FROM resources
                    WHERE kind IN ('qemu', 'lxc') AND external_id=$1""",
                    vmid,
                )
                if resource is None:
                    continue
                await database(request).pool.execute(
                    """INSERT INTO pool_members(pool_id, resource_id)
                    VALUES($1, $2) ON CONFLICT DO NOTHING""",
                    pool_row["id"],
                    resource["id"],
                )
        if "delete" in payload:
            vmids = [item.strip() for item in str(payload["delete"]).split(",") if item.strip()]
            await database(request).pool.execute(
                """DELETE FROM pool_members pm USING resources r
                WHERE pm.pool_id=$1 AND pm.resource_id=r.id AND r.external_id = ANY($2::text[])""",
                pool_row["id"],
                vmids,
            )

    async def pool_delete(request: Request, inputs: dict[str, Any]) -> None:
        poolid = str(values(inputs)["poolid"])
        status = await database(request).pool.execute(
            "DELETE FROM pools WHERE pool_id=$1",
            poolid,
        )
        if status != "DELETE 1":
            raise ApiError(404, "pool does not exist")

    registry.register("/pools", "GET", pool_list)
    registry.register("/pools", "POST", pool_create)
    registry.register("/pools", "PUT", pool_update)
    registry.register("/pools", "DELETE", pool_delete)
    registry.register("/pools/{poolid}", "GET", pool_get)
    registry.register("/pools/{poolid}", "PUT", pool_update)
    registry.register("/pools/{poolid}", "DELETE", pool_delete)
