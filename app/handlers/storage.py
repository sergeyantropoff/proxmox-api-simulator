"""Storage semantic handlers."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import (
    database,
    require_node,
    require_value,
    state,
    storage_payload,
    subdirs,
    values,
)
from app.simulation.seed import CLUSTER_ID, stable_id


def register_storage_handlers(registry: HandlerRegistry) -> None:
    async def _storage_row(request: Request, node: str | None, storage_id: str) -> Any:
        row = await database(request).pool.fetchrow(
            """SELECT s.storage_id, s.storage_type, s.shared, s.capacity_bytes, s.used_bytes,
                s.config, n.name AS node_name
            FROM storages s
            JOIN resources r ON r.id = s.resource_id
            JOIN nodes n ON n.id = r.node_id
            WHERE s.storage_id=$1 AND ($2::text IS NULL OR n.name=$2)""",
            storage_id,
            node,
        )
        if row is None:
            raise ApiError(404, "storage does not exist")
        return row

    async def storage_ids(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        rows = await database(_request).pool.fetch(
            "SELECT DISTINCT storage_id FROM storages ORDER BY storage_id"
        )
        return [{"storage": str(row["storage_id"])} for row in rows]

    async def storage_create(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        storage_id = str(payload["storage"])
        storage_type = str(payload.get("type") or "dir")
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM storages WHERE storage_id=$1)",
            storage_id,
        )
        if exists:
            raise ApiError(409, "storage ID already exists")
        node = await database(request).pool.fetchrow(
            "SELECT id, name FROM nodes ORDER BY name LIMIT 1"
        )
        if node is None:
            raise ApiError(503, "no nodes available")
        resource_id = stable_id(f"storage:{storage_id}")
        config = {
            key: value
            for key, value in payload.items()
            if key not in {"storage", "type", "nodes", "delete"}
        }
        if "content" in payload:
            config["content"] = [
                item.strip() for item in str(payload["content"]).split(",") if item.strip()
            ]
        async with database(request).pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO resources(id, node_id, kind, external_id, state, cluster_id)
                    VALUES($1, $2, 'storage', $3, $4::jsonb, $5)""",
                    resource_id,
                    node["id"],
                    storage_id,
                    json.dumps({**config, "status": "available"}, sort_keys=True),
                    CLUSTER_ID,
                )
                await connection.execute(
                    """INSERT INTO storages(
                        resource_id, cluster_id, storage_id, storage_type, shared, config
                    ) VALUES($1, $2, $3, $4, $5, $6::jsonb)""",
                    resource_id,
                    CLUSTER_ID,
                    storage_id,
                    storage_type,
                    bool(payload.get("shared", False)),
                    json.dumps(config, sort_keys=True),
                )
        return {"storage": storage_id, "type": storage_type, "config": config}

    async def storage_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        storage_id = str(values(inputs)["storage"])
        row = await _storage_row(request, None, storage_id)
        config = state(row["config"])
        return {
            "storage": storage_id,
            "type": str(row["storage_type"]),
            "shared": int(bool(row["shared"])),
            **config,
        }

    async def storage_update(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        storage_id = str(values(inputs)["storage"])
        row = await database(request).pool.fetchrow(
            """SELECT s.resource_id, s.config FROM storages s WHERE s.storage_id=$1""",
            storage_id,
        )
        if row is None:
            raise ApiError(404, "storage does not exist")
        current = state(row["config"])
        provided = values(inputs)
        updated = {
            **current,
            **{
                key: value
                for key, value in provided.items()
                if key not in {"storage", "delete", "digest"}
            },
        }
        await database(request).pool.execute(
            "UPDATE storages SET config=$2::jsonb WHERE storage_id=$1",
            storage_id,
            json.dumps(updated, sort_keys=True),
        )
        return updated

    async def storage_delete(request: Request, inputs: dict[str, Any]) -> None:
        storage_id = str(values(inputs)["storage"])
        status = await database(request).pool.execute(
            """DELETE FROM resources r USING storages s
            WHERE s.resource_id=r.id AND s.storage_id=$1""",
            storage_id,
        )
        if status != "DELETE 1":
            raise ApiError(404, "storage does not exist")

    async def node_storage_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        rows = await database(request).pool.fetch(
            """SELECT s.storage_id, s.storage_type, s.shared,
                      s.capacity_bytes, s.used_bytes, s.config
            FROM storages s
            JOIN resources r ON r.id = s.resource_id
            JOIN nodes n ON n.id = r.node_id
            WHERE n.name=$1 OR s.shared = true
            ORDER BY s.storage_id""",
            node,
        )
        return [storage_payload(row) for row in rows]

    async def node_storage_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        node = str(values(inputs)["node"])
        storage_id = str(values(inputs)["storage"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        return subdirs("content", "status", "upload")

    async def node_storage_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        storage_id = str(values(inputs)["storage"])
        await require_node(request, node)
        row = await _storage_row(request, None, storage_id)
        return storage_payload(row)

    async def node_storage_content(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        storage_id = str(values(inputs)["storage"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        contents = await database(request).pool.fetch(
            """SELECT volume_id, content_type, size_bytes, metadata, created_at
            FROM storage_contents WHERE storage_resource_id=$1 ORDER BY created_at DESC""",
            resource_id,
        )
        backups = await database(request).pool.fetch(
            """SELECT b.volume_id, b.size_bytes, b.metadata, b.created_at, r.external_id AS vmid
            FROM backups b
            LEFT JOIN resources r ON r.id = b.resource_id
            WHERE b.storage_resource_id=$1
            ORDER BY b.created_at DESC""",
            resource_id,
        )
        result: list[dict[str, Any]] = []
        for item in contents:
            metadata = state(item["metadata"])
            result.append(
                {
                    "volid": str(item["volume_id"]),
                    "content": str(item["content_type"]),
                    "size": int(item["size_bytes"]),
                    "format": metadata.get("format", "raw"),
                    "ctime": int(item["created_at"].timestamp()),
                }
            )
        for item in backups:
            metadata = state(item["metadata"])
            result.append(
                {
                    "volid": str(item["volume_id"]),
                    "content": "backup",
                    "size": int(item["size_bytes"]),
                    "format": "vma.zst",
                    "vmid": int(item["vmid"]) if item["vmid"] is not None else None,
                    "notes": metadata.get("notes-template"),
                    "ctime": int(item["created_at"].timestamp()),
                }
            )
        return result

    async def _content_item(
        request: Request, storage_resource_id: object, volume_id: str
    ) -> dict[str, Any]:
        row = await database(request).pool.fetchrow(
            """SELECT volume_id, content_type, size_bytes, metadata, created_at
            FROM storage_contents WHERE storage_resource_id=$1 AND volume_id=$2""",
            storage_resource_id,
            volume_id,
        )
        if row is not None:
            metadata = state(row["metadata"])
            return {
                "volid": str(row["volume_id"]),
                "content": str(row["content_type"]),
                "size": int(row["size_bytes"]),
                "format": metadata.get("format", "raw"),
                "ctime": int(row["created_at"].timestamp()),
            }
        backup = await database(request).pool.fetchrow(
            """SELECT b.volume_id, b.size_bytes, b.metadata, b.created_at, r.external_id AS vmid
            FROM backups b
            LEFT JOIN resources r ON r.id = b.resource_id
            WHERE b.storage_resource_id=$1 AND b.volume_id=$2""",
            storage_resource_id,
            volume_id,
        )
        if backup is None:
            raise ApiError(404, "volume does not exist")
        metadata = state(backup["metadata"])
        return {
            "volid": str(backup["volume_id"]),
            "content": "backup",
            "size": int(backup["size_bytes"]),
            "format": "vma.zst",
            "vmid": int(backup["vmid"]) if backup["vmid"] is not None else None,
            "notes": metadata.get("notes-template"),
            "ctime": int(backup["created_at"].timestamp()),
        }

    async def node_storage_content_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        storage_id = str(values(inputs)["storage"])
        volume_id = str(values(inputs)["volume"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        return await _content_item(request, resource_id, volume_id)

    async def node_storage_content_delete(request: Request, inputs: dict[str, Any]) -> None:
        node = str(values(inputs)["node"])
        storage_id = str(values(inputs)["storage"])
        volume_id = str(values(inputs)["volume"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        status = await database(request).pool.execute(
            "DELETE FROM storage_contents WHERE storage_resource_id=$1 AND volume_id=$2",
            resource_id,
            volume_id,
        )
        if status == "DELETE 1":
            return
        status = await database(request).pool.execute(
            "DELETE FROM backups WHERE storage_resource_id=$1 AND volume_id=$2",
            resource_id,
            volume_id,
        )
        if status != "DELETE 1":
            raise ApiError(404, "volume does not exist")

    async def node_storage_upload(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        storage_id = str(values(inputs)["storage"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        payload = values(inputs)
        filename = str(payload.get("filename") or "upload.bin")
        content_type = str(payload.get("content") or "iso")
        raw_size = payload.get("size") or 0
        try:
            size = int(raw_size)
        except (TypeError, ValueError) as error:
            raise ApiError(400, "invalid size") from error
        volume_id = f"{storage_id}:{content_type}/{filename}"
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        await database(request).pool.execute(
            """INSERT INTO storage_contents(
                id, storage_resource_id, volume_id, content_type, size_bytes, metadata
            ) VALUES(gen_random_uuid(), $1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (storage_resource_id, volume_id) DO UPDATE
            SET size_bytes=EXCLUDED.size_bytes,
                content_type=EXCLUDED.content_type,
                metadata=EXCLUDED.metadata""",
            resource_id,
            volume_id,
            content_type,
            size,
            json.dumps({"filename": filename, "source": "upload"}, sort_keys=True),
        )
        return {"uploadid": volume_id, "filename": filename, "size": size, "volid": volume_id}

    async def node_storage_prunebackups(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        node = str(values(inputs)["node"])
        storage_id = str(values(inputs)["storage"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        if request.method == "DELETE":
            keep = int(values(inputs).get("keep-last") or values(inputs).get("keep_last") or 1)
            await database(request).pool.execute(
                """DELETE FROM backups
                WHERE storage_resource_id=$1 AND id IN (
                    SELECT id FROM backups
                    WHERE storage_resource_id=$1
                    ORDER BY created_at DESC
                    OFFSET $2
                )""",
                resource_id,
                keep,
            )
            return None
        rows = await database(request).pool.fetch(
            """SELECT volume_id, size_bytes, created_at FROM backups
            WHERE storage_resource_id=$1 ORDER BY created_at DESC""",
            resource_id,
        )
        return [
            {
                "volid": str(row["volume_id"]),
                "size": int(row["size_bytes"]),
                "ctime": int(row["created_at"].timestamp()),
            }
            for row in rows
        ]

    async def content_copy(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        storage_id = str(payload["storage"])
        volume = str(payload["volume"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        row = await database(request).pool.fetchrow(
            """SELECT volume_id, content_type, size_bytes, metadata
            FROM storage_contents WHERE storage_resource_id=$1 AND volume_id=$2""",
            resource_id,
            volume,
        )
        if row is None:
            raise ApiError(404, "volume does not exist")
        target = str(payload.get("target") or f"{volume}-copy")
        await database(request).pool.execute(
            """INSERT INTO storage_contents(
                id, storage_resource_id, volume_id, content_type, size_bytes, metadata
            ) VALUES(gen_random_uuid(), $1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (storage_resource_id, volume_id) DO UPDATE
            SET size_bytes=EXCLUDED.size_bytes, metadata=EXCLUDED.metadata""",
            resource_id,
            target,
            row["content_type"],
            row["size_bytes"],
            json.dumps({**state(row["metadata"]), "copied_from": volume}, sort_keys=True),
        )
        return f"UPID:{node}:copy:{target}"

    async def content_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        node = str(payload["node"])
        storage_id = str(payload["storage"])
        volume = str(payload["volume"])
        await require_node(request, node)
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        row = await database(request).pool.fetchrow(
            """SELECT metadata FROM storage_contents
            WHERE storage_resource_id=$1 AND volume_id=$2""",
            resource_id,
            volume,
        )
        if row is None:
            raise ApiError(404, "volume does not exist")
        meta = state(row["metadata"])
        if "notes" in payload:
            meta["notes"] = payload["notes"]
        if "protected" in payload:
            meta["protected"] = int(bool(payload["protected"]))
        await database(request).pool.execute(
            """UPDATE storage_contents SET metadata=$3::jsonb
            WHERE storage_resource_id=$1 AND volume_id=$2""",
            resource_id,
            volume,
            json.dumps(meta, sort_keys=True),
        )

    async def download_url(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        storage_id = str(payload["storage"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        filename = str(payload.get("filename") or "download.bin")
        content_type = str(payload.get("content") or "iso")
        volume_id = f"{storage_id}:{content_type}/{filename}"
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        await database(request).pool.execute(
            """INSERT INTO storage_contents(
                id, storage_resource_id, volume_id, content_type, size_bytes, metadata
            ) VALUES(gen_random_uuid(), $1, $2, $3, 0, $4::jsonb)
            ON CONFLICT (storage_resource_id, volume_id) DO UPDATE
            SET metadata=EXCLUDED.metadata""",
            resource_id,
            volume_id,
            content_type,
            json.dumps(
                {
                    "filename": filename,
                    "url": payload.get("url"),
                    "source": "download-url",
                },
                sort_keys=True,
            ),
        )
        return f"UPID:{node}:download:{filename}"

    async def oci_pull(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        node = str(payload["node"])
        storage_id = str(payload["storage"])
        await require_node(request, node)
        await _storage_row(request, None, storage_id)
        reference = str(payload.get("reference") or "image:latest")
        filename = str(payload.get("filename") or reference.replace("/", "_"))
        volume_id = f"{storage_id}:import/{filename}"
        resource_id = await database(request).pool.fetchval(
            "SELECT resource_id FROM storages WHERE storage_id=$1",
            storage_id,
        )
        await database(request).pool.execute(
            """INSERT INTO storage_contents(
                id, storage_resource_id, volume_id, content_type, size_bytes, metadata
            ) VALUES(gen_random_uuid(), $1, $2, 'import', 0, $3::jsonb)
            ON CONFLICT (storage_resource_id, volume_id) DO UPDATE
            SET metadata=EXCLUDED.metadata""",
            resource_id,
            volume_id,
            json.dumps({"reference": reference, "source": "oci"}, sort_keys=True),
        )
        return f"UPID:{node}:oci-pull:{filename}"

    async def file_restore_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        row = await _storage_row(request, None, str(payload["storage"]))
        filepath = str(payload.get("filepath") or "/")
        config = state(row["config"])
        restore = config.get("file_restore")
        if not isinstance(restore, dict):
            return []
        items = restore.get(filepath) or restore.get(filepath.rstrip("/") or "/")
        return [dict(item) for item in items] if isinstance(items, list) else []

    async def file_restore_download(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        row = await _storage_row(request, None, str(payload["storage"]))
        config = state(row["config"])
        downloads = config.get("file_restore_downloads")
        filepath = str(payload.get("filepath") or "/")
        if isinstance(downloads, dict) and filepath in downloads:
            entry = downloads[filepath]
            return dict(entry) if isinstance(entry, dict) else {"filepath": filepath}
        return {
            "download-url": f"/api2/json/nodes/{payload['node']}/storage/"
            f"{payload['storage']}/file-restore/download",
            "filepath": filepath,
            "volume": payload.get("volume"),
        }

    async def storage_identity(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        row = await _storage_row(request, None, str(payload["storage"]))
        config = state(row["config"])
        identity = config.get("identity")
        if isinstance(identity, dict):
            return {
                "storage": str(row["storage_id"]),
                "type": str(identity.get("type") or row["storage_type"]),
                "fingerprint": str(identity.get("fingerprint") or ""),
            }
        return {
            "storage": str(row["storage_id"]),
            "type": str(row["storage_type"]),
            "fingerprint": "",
        }

    async def import_metadata(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        storage_id = str(payload["storage"])
        volume = str(require_value(payload, "volume"))
        row = await _storage_row(request, None, storage_id)
        config = state(row["config"])
        by_volume = config.get("import_metadata_by_volume")
        if isinstance(by_volume, dict) and volume in by_volume:
            meta = by_volume[volume]
            return dict(meta) if isinstance(meta, dict) else {}
        meta = config.get("import_metadata")
        if isinstance(meta, dict):
            return {"source": volume, **meta}
        return {}

    async def storage_rrd(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        row = await _storage_row(request, None, str(payload["storage"]))
        config = state(row["config"])
        rrd_state = config.get("rrd")
        return dict(rrd_state) if isinstance(rrd_state, dict) else {}

    async def storage_rrddata(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        payload = values(inputs)
        await require_node(request, str(payload["node"]))
        row = await _storage_row(request, None, str(payload["storage"]))
        config = state(row["config"])
        series = config.get("rrddata")
        return [dict(item) for item in series] if isinstance(series, list) else []

    registry.register("/storage", "GET", storage_ids)
    registry.register("/storage", "POST", storage_create)
    registry.register("/storage/{storage}", "GET", storage_get)
    registry.register("/storage/{storage}", "PUT", storage_update)
    registry.register("/storage/{storage}", "DELETE", storage_delete)
    registry.register("/nodes/{node}/storage", "GET", node_storage_list)
    registry.register("/nodes/{node}/storage/{storage}", "GET", node_storage_index)
    registry.register("/nodes/{node}/storage/{storage}/status", "GET", node_storage_status)
    registry.register("/nodes/{node}/storage/{storage}/content", "GET", node_storage_content)
    registry.register("/nodes/{node}/storage/{storage}/content", "POST", node_storage_upload)
    registry.register(
        "/nodes/{node}/storage/{storage}/content/{volume}", "GET", node_storage_content_get
    )
    registry.register(
        "/nodes/{node}/storage/{storage}/content/{volume}", "DELETE", node_storage_content_delete
    )
    registry.register("/nodes/{node}/storage/{storage}/upload", "POST", node_storage_upload)
    registry.register(
        "/nodes/{node}/storage/{storage}/prunebackups", "GET", node_storage_prunebackups
    )
    registry.register(
        "/nodes/{node}/storage/{storage}/prunebackups", "DELETE", node_storage_prunebackups
    )
    registry.register("/nodes/{node}/storage/{storage}/content/{volume}", "POST", content_copy)
    registry.register("/nodes/{node}/storage/{storage}/content/{volume}", "PUT", content_update)
    registry.register("/nodes/{node}/storage/{storage}/download-url", "POST", download_url)
    registry.register("/nodes/{node}/storage/{storage}/oci-registry-pull", "POST", oci_pull)
    registry.register("/nodes/{node}/storage/{storage}/file-restore/list", "GET", file_restore_list)
    registry.register(
        "/nodes/{node}/storage/{storage}/file-restore/download", "GET", file_restore_download
    )
    registry.register("/nodes/{node}/storage/{storage}/identity", "GET", storage_identity)
    registry.register("/nodes/{node}/storage/{storage}/import-metadata", "GET", import_metadata)
    registry.register("/nodes/{node}/storage/{storage}/rrd", "GET", storage_rrd)
    registry.register("/nodes/{node}/storage/{storage}/rrddata", "GET", storage_rrddata)
