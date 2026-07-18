"""Cluster config / join / totem handlers."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import (
    cluster_metadata,
    database,
    require_value,
    save_cluster_metadata,
    values,
)
from app.tasks.repository import TaskRepository
from app.tasks.upid import Upid


def _config(metadata: dict[str, Any]) -> dict[str, Any]:
    current = metadata.get("cluster_config")
    return current if isinstance(current, dict) else {}


def _principal(request: Request) -> str:
    return str(getattr(request.state, "principal", None) or "root@pam")


def _fingerprint_sha256() -> str:
    return ":".join(f"{byte:02X}" for byte in secrets.token_bytes(32))


def _stable_digest(material: str) -> str:
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _node_addr(node: str, index: int, entry: dict[str, Any]) -> str:
    for key in ("pve_addr", "new_node_ip", "ring0_addr"):
        value = entry.get(key)
        if isinstance(value, str) and value and not value.endswith(".local"):
            # Prefer literal IPs; hostnames are still accepted as ring addresses.
            if key != "ring0_addr" or all(part.isdigit() for part in value.split(".")):
                return value
    return f"10.0.0.{index}"


def _ring0_addr(node: str, index: int, entry: dict[str, Any], links: dict[str, Any]) -> str:
    if entry.get("ring0_addr"):
        return str(entry["ring0_addr"])
    link0 = links.get("link0")
    if isinstance(link0, str) and link0:
        # Property string may be bare IP or address=IP[,priority=N].
        if link0.startswith("address="):
            return link0.removeprefix("address=").split(",", 1)[0]
        return link0.split(",", 1)[0]
    if entry.get("new_node_ip"):
        return str(entry["new_node_ip"])
    return f"10.0.0.{index}"


def _render_corosync_conf(config: dict[str, Any], node_names: list[str]) -> str:
    clustername = str(config.get("clustername") or "proxmox")
    totem = dict(config.get("totem") or {})
    added_raw = config.get("added_nodes")
    added: dict[str, Any] = dict(added_raw) if isinstance(added_raw, dict) else {}
    links = dict(config.get("links") or {})
    lines = [
        "totem {",
        "  version: 2",
        f"  cluster_name: {totem.get('cluster_name', clustername)}",
        f"  secauth: {totem.get('secauth', 'on')}",
        "}",
        "nodelist {",
    ]
    for index, name in enumerate(node_names, start=1):
        entry_raw = added.get(name)
        entry: dict[str, Any] = dict(entry_raw) if isinstance(entry_raw, dict) else {}
        nodeid = int(entry.get("nodeid") or index)
        votes = int(entry.get("quorum_votes") or entry.get("votes") or config.get("votes") or 1)
        ring0 = _ring0_addr(name, index, entry, links)
        lines.extend(
            [
                "  node {",
                f"    name: {name}",
                f"    nodeid: {nodeid}",
                f"    quorum_votes: {votes}",
                f"    ring0_addr: {ring0}",
                "  }",
            ]
        )
    lines.append("}")
    lines.extend(["quorum {", "  provider: corosync_votequorum", "}"])
    return "\n".join(lines) + "\n"


def _ensure_corosync_materials(
    config: dict[str, Any], node_names: list[str]
) -> tuple[str, str, str]:
    authkey = config.get("corosync_authkey")
    if not isinstance(authkey, str) or not authkey:
        authkey = secrets.token_hex(32)
        config["corosync_authkey"] = authkey
    conf = _render_corosync_conf(config, node_names)
    config["corosync_conf"] = conf
    digest = _stable_digest(conf)
    config["config_digest"] = digest
    return authkey, conf, digest


async def _cluster_task(
    request: Request, *, task_type: str, worker: str, task_id: str = "0"
) -> str:
    from app.db.primitives import ConflictError

    pool = database(request).pool
    node = await pool.fetchval("SELECT name FROM nodes ORDER BY name LIMIT 1") or "localhost"
    upid = str(Upid.allocate(str(node), worker, task_id, _principal(request)))
    try:
        task = await TaskRepository(pool).create(
            upid=upid,
            task_type=task_type,
            payload={"cluster": True, "worker": worker},
            resource_key=f"cluster:{task_type}:{secrets.token_hex(4)}",
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid


def register_cluster_config_handlers(registry: HandlerRegistry) -> None:
    async def index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        # PVE uses {name}; contract child link is href="{name}".
        return [{"name": name} for name in ("nodes", "totem", "join", "qdevice", "apiversion")]

    async def create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        clustername = str(require_value(payload, "clustername"))
        metadata = await cluster_metadata(request)
        config = dict(_config(metadata))
        # Match PVE: refuse when corosync materials already exist (seeded or prior create).
        if config.get("corosync_conf") or config.get("config_digest"):
            raise ApiError(400, "cluster config already exists")
        config["clustername"] = clustername
        totem = dict(config.get("totem") or {})
        totem["version"] = int(totem.get("version") or 2)
        totem["secauth"] = totem.get("secauth") or "on"
        totem["cluster_name"] = clustername
        # PVE defaults token-coefficient to 125 when omitted (majors that expose it).
        totem["token_coefficient"] = payload.get("token-coefficient", 125)
        config["totem"] = totem
        if "votes" in payload:
            config["votes"] = payload["votes"]
        if "nodeid" in payload:
            config["creator_nodeid"] = payload["nodeid"]
        links = {key: value for key, value in payload.items() if key.startswith("link")}
        if links:
            config["links"] = links
        config["token"] = secrets.token_hex(16)

        rows = await database(request).pool.fetch("SELECT name FROM nodes ORDER BY name")
        node_names = [str(row["name"]) for row in rows]
        if not node_names:
            node_names = ["localhost"]
        creator = node_names[0]
        added = dict(config.get("added_nodes") or {})
        creator_entry = dict(added.get(creator) or {})
        creator_entry.update(
            {
                "node": creator,
                "nodeid": payload.get("nodeid") or creator_entry.get("nodeid") or 1,
                "quorum_votes": payload.get("votes") or creator_entry.get("quorum_votes") or 1,
                "ring0_addr": _ring0_addr(
                    creator, 1, creator_entry, dict(config.get("links") or {})
                ),
                "pve_addr": creator_entry.get("pve_addr") or _node_addr(creator, 1, creator_entry),
                "pve_fp": creator_entry.get("pve_fp") or _fingerprint_sha256(),
            }
        )
        added[creator] = creator_entry
        config["added_nodes"] = added
        _ensure_corosync_materials(config, node_names)

        metadata["cluster_config"] = config
        await save_cluster_metadata(request, metadata)
        await database(request).pool.execute(
            """UPDATE clusters
            SET name=$1, updated_at=now()
            WHERE id=(SELECT id FROM clusters LIMIT 1)""",
            clustername,
        )
        return await _cluster_task(
            request,
            task_type="cluster-create",
            worker="clustercreate",
            task_id=clustername,
        )

    async def apiversion(_request: Request, _inputs: dict[str, Any]) -> int:
        metadata = await cluster_metadata(_request)
        return int(_config(metadata).get("apiversion") or 1)

    async def join_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        config = _config(metadata)
        preferred_raw = values(inputs).get("node")
        # Contract documents the omitted-node default as this phrase; PVE uses local nodename.
        if preferred_raw in {None, "", "current connected node"}:
            preferred = None
        else:
            preferred = str(preferred_raw)
        rows = await database(request).pool.fetch("SELECT name, status FROM nodes ORDER BY name")
        added_raw = config.get("added_nodes")
        added: dict[str, Any] = dict(added_raw) if isinstance(added_raw, dict) else {}
        links = dict(config.get("links") or {})
        nodelist: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            name = str(row["name"])
            entry_raw = added.get(name)
            entry: dict[str, Any] = dict(entry_raw) if isinstance(entry_raw, dict) else {}
            if "pve_fp" not in entry:
                entry["pve_fp"] = _fingerprint_sha256()
                added[name] = entry
            if "pve_addr" not in entry:
                entry["pve_addr"] = _node_addr(name, index, entry)
                added[name] = entry
            nodelist.append(
                {
                    "name": name,
                    "nodeid": int(entry.get("nodeid") or index),
                    "quorum_votes": int(
                        entry.get("quorum_votes") or entry.get("votes") or config.get("votes") or 1
                    ),
                    "ring0_addr": _ring0_addr(name, index, entry, links),
                    "pve_addr": str(entry["pve_addr"]),
                    "pve_fp": str(entry["pve_fp"]),
                }
            )
        if added != dict(added_raw or {}):
            updated = dict(config)
            updated["added_nodes"] = added
            if not updated.get("config_digest"):
                _ensure_corosync_materials(updated, [item["name"] for item in nodelist])
            metadata["cluster_config"] = updated
            await save_cluster_metadata(request, metadata)
            config = updated
        preferred_node = preferred or (nodelist[0]["name"] if nodelist else None)
        digest = config.get("config_digest")
        if not isinstance(digest, str) or not digest:
            updated = dict(config)
            _, _, digest = _ensure_corosync_materials(updated, [item["name"] for item in nodelist])
            metadata["cluster_config"] = updated
            await save_cluster_metadata(request, metadata)
            config = updated
        return {
            "nodelist": nodelist,
            "preferred_node": preferred_node,
            "totem": dict(config.get("totem") or {}),
            "config_digest": digest,
        }

    async def join_post(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        hostname = str(require_value(payload, "hostname"))
        require_value(payload, "fingerprint")
        require_value(payload, "password")
        metadata = await cluster_metadata(request)
        config = dict(_config(metadata))
        joins = dict(config.get("join_info") or {})
        joins[hostname] = {
            "hostname": hostname,
            "fingerprint": payload.get("fingerprint"),
            "nodeid": payload.get("nodeid"),
            "votes": payload.get("votes", 1),
            "force": payload.get("force"),
            "password_set": True,
        }
        links = {key: value for key, value in payload.items() if key.startswith("link")}
        if links:
            joins[hostname]["links"] = links
        config["join_info"] = joins
        rows = await database(request).pool.fetch("SELECT name FROM nodes ORDER BY name")
        node_names = [str(row["name"]) for row in rows]
        _ensure_corosync_materials(config, node_names or ["localhost"])
        metadata["cluster_config"] = config
        await save_cluster_metadata(request, metadata)
        return await _cluster_task(
            request,
            task_type="cluster-join",
            worker="clusterjoin",
        )

    async def nodes_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(request).pool.fetch("SELECT name, status FROM nodes ORDER BY name")
        metadata = await cluster_metadata(request)
        config = _config(metadata)
        added_raw = config.get("added_nodes")
        added: dict[str, Any] = dict(added_raw) if isinstance(added_raw, dict) else {}
        links = dict(config.get("links") or {})
        result = []
        for index, row in enumerate(rows, start=1):
            name = str(row["name"])
            entry_raw = added.get(name)
            entry: dict[str, Any] = dict(entry_raw) if isinstance(entry_raw, dict) else {}
            result.append(
                {
                    "node": name,
                    "nodeid": entry.get("nodeid", index),
                    "ring0_addr": _ring0_addr(name, index, entry, links),
                    "quorum_votes": entry.get("quorum_votes", config.get("votes", 0)),
                }
            )
        return result

    async def nodes_add(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        node = str(require_value(payload, "node"))
        metadata = await cluster_metadata(request)
        config = dict(_config(metadata))
        added = dict(config.get("added_nodes") or {})
        if node in added and not payload.get("force"):
            raise ApiError(400, f"can't add existing node '{node}'")
        index = len(added) + 1
        links = {key: value for key, value in payload.items() if key.startswith("link")}
        entry = {
            "node": node,
            "nodeid": payload.get("nodeid") or index,
            "new_node_ip": payload.get("new_node_ip"),
            "votes": payload.get("votes", 1),
            "apiversion": payload.get("apiversion"),
            "force": payload.get("force"),
            "ring0_addr": payload.get("ring0_addr")
            or payload.get("new_node_ip")
            or _ring0_addr(node, index, {}, links or dict(config.get("links") or {})),
            "quorum_votes": payload.get("quorum_votes", payload.get("votes", 1)),
            "pve_addr": payload.get("new_node_ip") or _node_addr(node, index, {}),
            "pve_fp": _fingerprint_sha256(),
        }
        if links:
            entry["links"] = links
        added[node] = entry
        config["added_nodes"] = added
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
        rows = await database(request).pool.fetch("SELECT name FROM nodes ORDER BY name")
        node_names = [str(row["name"]) for row in rows]
        if node not in node_names:
            node_names.append(node)
        authkey, conf, _digest = _ensure_corosync_materials(config, node_names)
        metadata["cluster_config"] = config
        await save_cluster_metadata(request, metadata)
        return {
            "corosync_authkey": authkey,
            "corosync_conf": conf,
            "warnings": [],
        }

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
        rows = await database(request).pool.fetch("SELECT name FROM nodes ORDER BY name")
        node_names = [str(row["name"]) for row in rows if str(row["name"]) != node]
        _ensure_corosync_materials(config, node_names or ["localhost"])
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
