"""Cluster config / join / totem handlers."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import (
    cluster_metadata,
    database,
    save_cluster_metadata,
    subdirs,
    values,
)


def _config(metadata: dict[str, Any]) -> dict[str, Any]:
    current = metadata.setdefault(
        "cluster_config",
        {
            "clustername": "pve-simulator",
            "votes": 1,
            "links": {},
            "join_info": {},
            "totem": {"version": 2, "secauth": "on", "cluster_name": "pve-simulator"},
            "qdevice": {"status": "disabled"},
            "apiversion": 1,
        },
    )
    if not isinstance(current, dict):
        current = {
            "clustername": "pve-simulator",
            "votes": 1,
            "links": {},
            "join_info": {},
            "totem": {"version": 2, "secauth": "on", "cluster_name": "pve-simulator"},
            "qdevice": {"status": "disabled"},
            "apiversion": 1,
        }
        metadata["cluster_config"] = current
    return current


def register_cluster_config_handlers(registry: HandlerRegistry) -> None:
    async def index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("apiversion", "join", "nodes", "qdevice", "totem")

    async def create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        metadata = await cluster_metadata(request)
        config = _config(metadata)
        if payload.get("clustername"):
            config["clustername"] = str(payload["clustername"])
            config.setdefault("totem", {})["cluster_name"] = str(payload["clustername"])
        if "votes" in payload:
            config["votes"] = payload["votes"]
        if "nodeid" in payload:
            config["creator_nodeid"] = payload["nodeid"]
        links = {key: value for key, value in payload.items() if key.startswith("link")}
        if links:
            config["links"] = links
        config["token"] = secrets.token_hex(16)
        await save_cluster_metadata(request, metadata)
        await database(request).pool.execute(
            """UPDATE clusters
            SET name=$1, updated_at=now()
            WHERE id=(SELECT id FROM clusters LIMIT 1)""",
            str(config["clustername"]),
        )

    async def apiversion(_request: Request, _inputs: dict[str, Any]) -> int:
        metadata = await cluster_metadata(_request)
        return int(_config(metadata).get("apiversion") or 1)

    async def join_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        config = _config(metadata)
        node = values(inputs).get("node")
        rows = await database(request).pool.fetch("SELECT name, status FROM nodes ORDER BY name")
        nodelist = [
            {"name": str(row["name"]), "online": 1 if row["status"] == "online" else 0}
            for row in rows
        ]
        return {
            "clustername": config.get("clustername"),
            "config_digest": secrets.token_hex(8),
            "nodelist": nodelist,
            "preferred_node": node or (nodelist[0]["name"] if nodelist else None),
            "totem": config.get("totem", {}),
            "links": config.get("links", {}),
        }

    async def join_post(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        metadata = await cluster_metadata(request)
        config = _config(metadata)
        hostname = str(payload.get("hostname") or payload.get("node") or "")
        if not hostname:
            raise ApiError(400, "parameter verification failed - 'hostname' missing")
        joins = config.setdefault("join_info", {})
        joins[hostname] = {
            "hostname": hostname,
            "fingerprint": payload.get("fingerprint"),
            "nodeid": payload.get("nodeid"),
            "votes": payload.get("votes", 1),
            "force": payload.get("force"),
        }
        # password accepted but not stored in clear form
        if payload.get("password"):
            joins[hostname]["password_set"] = True
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM nodes WHERE name=$1)",
            hostname,
        )
        if not exists:
            await database(request).pool.execute(
                """INSERT INTO nodes(id, name, status, metadata)
                VALUES(gen_random_uuid(), $1, 'online', '{}'::jsonb)""",
                hostname,
            )
        await save_cluster_metadata(request, metadata)

    async def nodes_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(request).pool.fetch("SELECT name, status FROM nodes ORDER BY name")
        metadata = await cluster_metadata(request)
        config = _config(metadata)
        result = []
        for index, row in enumerate(rows, start=1):
            result.append(
                {
                    "node": str(row["name"]),
                    "nodeid": index,
                    "ring0_addr": f"{row['name']}.local",
                    "quorum_votes": config.get("votes", 1),
                }
            )
        return result

    async def nodes_add(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        metadata = await cluster_metadata(request)
        config = _config(metadata)
        added = config.setdefault("added_nodes", {})
        added[node] = {
            "node": node,
            "nodeid": payload.get("nodeid"),
            "new_node_ip": payload.get("new_node_ip"),
            "votes": payload.get("votes", 1),
            "apiversion": payload.get("apiversion"),
            "force": payload.get("force"),
        }
        links = {key: value for key, value in payload.items() if key.startswith("link")}
        if links:
            added[node]["links"] = links
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM nodes WHERE name=$1)",
            node,
        )
        if not exists:
            await database(request).pool.execute(
                """INSERT INTO nodes(id, name, status, metadata)
                VALUES(gen_random_uuid(), $1, 'online', '{}'::jsonb)""",
                node,
            )
        await save_cluster_metadata(request, metadata)

    async def nodes_delete(request: Request, inputs: dict[str, Any]) -> None:
        node = str(values(inputs)["node"])
        metadata = await cluster_metadata(request)
        config = _config(metadata)
        added = config.setdefault("added_nodes", {})
        added.pop(node, None)
        joins = config.setdefault("join_info", {})
        joins.pop(node, None)
        await save_cluster_metadata(request, metadata)
        # Keep node row; mark offline to avoid cascading guest deletes.
        await database(request).pool.execute(
            "UPDATE nodes SET status='offline', updated_at=now() WHERE name=$1",
            node,
        )

    async def qdevice(request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        return dict(_config(metadata).get("qdevice") or {"status": "disabled"})

    async def totem(request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        return dict(_config(metadata).get("totem") or {})

    registry.register("/cluster/config", "GET", index)
    registry.register("/cluster/config", "POST", create)
    registry.register("/cluster/config/apiversion", "GET", apiversion)
    registry.register("/cluster/config/join", "GET", join_get)
    registry.register("/cluster/config/join", "POST", join_post)
    registry.register("/cluster/config/nodes", "GET", nodes_list)
    registry.register("/cluster/config/nodes/{node}", "POST", nodes_add)
    registry.register("/cluster/config/nodes/{node}", "DELETE", nodes_delete)
    registry.register("/cluster/config/qdevice", "GET", qdevice)
    registry.register("/cluster/config/totem", "GET", totem)
