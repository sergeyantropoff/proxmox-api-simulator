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
    current = metadata.get("cluster_config")
    return current if isinstance(current, dict) else {}


def register_cluster_config_handlers(registry: HandlerRegistry) -> None:
    async def index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("apiversion", "join", "nodes", "qdevice", "totem")

    async def create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        metadata = await cluster_metadata(request)
        config = dict(_config(metadata))
        if payload.get("clustername"):
            config["clustername"] = str(payload["clustername"])
            totem = dict(config.get("totem") or {})
            totem["cluster_name"] = str(payload["clustername"])
            config["totem"] = totem
        if "votes" in payload:
            config["votes"] = payload["votes"]
        if "nodeid" in payload:
            config["creator_nodeid"] = payload["nodeid"]
        links = {key: value for key, value in payload.items() if key.startswith("link")}
        if links:
            config["links"] = links
        config["token"] = secrets.token_hex(16)
        metadata["cluster_config"] = config
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
        config = dict(_config(metadata))
        hostname = str(payload.get("hostname") or payload.get("node") or "")
        if not hostname:
            raise ApiError(400, "parameter verification failed - 'hostname' missing")
        joins = dict(config.get("join_info") or {})
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
        config["join_info"] = joins
        metadata["cluster_config"] = config
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
        added_raw = config.get("added_nodes")
        added: dict[str, Any] = dict(added_raw) if isinstance(added_raw, dict) else {}
        result = []
        for index, row in enumerate(rows, start=1):
            name = str(row["name"])
            entry_raw = added.get(name)
            entry: dict[str, Any] = dict(entry_raw) if isinstance(entry_raw, dict) else {}
            result.append(
                {
                    "node": name,
                    "nodeid": entry.get("nodeid", index),
                    "ring0_addr": entry.get("ring0_addr", ""),
                    "quorum_votes": entry.get("quorum_votes", config.get("votes", 0)),
                }
            )
        return result

    async def nodes_add(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        metadata = await cluster_metadata(request)
        config = dict(_config(metadata))
        added = dict(config.get("added_nodes") or {})
        added[node] = {
            "node": node,
            "nodeid": payload.get("nodeid"),
            "new_node_ip": payload.get("new_node_ip"),
            "votes": payload.get("votes", 1),
            "apiversion": payload.get("apiversion"),
            "force": payload.get("force"),
            "ring0_addr": payload.get("ring0_addr") or f"{node}.local",
            "quorum_votes": payload.get("quorum_votes", payload.get("votes", 1)),
        }
        links = {key: value for key, value in payload.items() if key.startswith("link")}
        if links:
            added[node]["links"] = links
        config["added_nodes"] = added
        metadata["cluster_config"] = config
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
        config = dict(_config(metadata))
        added = dict(config.get("added_nodes") or {})
        added.pop(node, None)
        joins = dict(config.get("join_info") or {})
        joins.pop(node, None)
        config["added_nodes"] = added
        config["join_info"] = joins
        metadata["cluster_config"] = config
        await save_cluster_metadata(request, metadata)
        # Keep node row; mark offline to avoid cascading guest deletes.
        await database(request).pool.execute(
            "UPDATE nodes SET status='offline', updated_at=now() WHERE name=$1",
            node,
        )

    async def qdevice(request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        qdevice = _config(metadata).get("qdevice")
        return dict(qdevice) if isinstance(qdevice, dict) else {}

    async def totem(request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        totem = _config(metadata).get("totem")
        return dict(totem) if isinstance(totem, dict) else {}

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
