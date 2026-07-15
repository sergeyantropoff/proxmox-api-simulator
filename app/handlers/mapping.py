"""Cluster resource mapping handlers (dir/pci/usb)."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import cluster_metadata, save_cluster_metadata, subdirs, values


def _mappings(metadata: dict[str, Any]) -> dict[str, Any]:
    current = metadata.setdefault("mapping", {"dir": {}, "pci": {}, "usb": {}})
    if not isinstance(current, dict):
        current = {"dir": {}, "pci": {}, "usb": {}}
        metadata["mapping"] = current
    for kind in ("dir", "pci", "usb"):
        current.setdefault(kind, {})
    return current


def register_mapping_handlers(registry: HandlerRegistry) -> None:
    async def index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("dir", "pci", "usb")

    def register_kind(kind: str) -> None:
        base = f"/cluster/mapping/{kind}"

        async def list_items(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            metadata = await cluster_metadata(request)
            store = _mappings(metadata)[kind]
            check_node = values(inputs).get("check-node")
            result = [{"id": key, **item} for key, item in sorted(store.items())]
            if check_node:
                for item in result:
                    item["checks"] = {str(check_node): "OK"}
            return result

        async def create(request: Request, inputs: dict[str, Any]) -> None:
            payload = values(inputs)
            item_id = str(payload["id"])
            metadata = await cluster_metadata(request)
            store = _mappings(metadata)[kind]
            if item_id in store:
                raise ApiError(400, f"{kind} mapping '{item_id}' already exists")
            store[item_id] = {
                key: value for key, value in payload.items() if key not in {"delete", "digest"}
            }
            await save_cluster_metadata(request, metadata)

        async def get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            item_id = str(values(inputs)["id"])
            metadata = await cluster_metadata(request)
            store = _mappings(metadata)[kind]
            if item_id not in store:
                raise ApiError(404, f"{kind} mapping does not exist")
            return {"id": item_id, **store[item_id]}

        async def update(request: Request, inputs: dict[str, Any]) -> None:
            payload = values(inputs)
            item_id = str(payload["id"])
            metadata = await cluster_metadata(request)
            store = _mappings(metadata)[kind]
            if item_id not in store:
                raise ApiError(404, f"{kind} mapping does not exist")
            current = dict(store[item_id])
            for key in [
                item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
            ]:
                current.pop(key, None)
            for key, value in payload.items():
                if key in {"id", "delete", "digest"}:
                    continue
                current[key] = value
            current["id"] = item_id
            store[item_id] = current
            await save_cluster_metadata(request, metadata)

        async def delete(request: Request, inputs: dict[str, Any]) -> None:
            item_id = str(values(inputs)["id"])
            metadata = await cluster_metadata(request)
            store = _mappings(metadata)[kind]
            if item_id not in store:
                raise ApiError(404, f"{kind} mapping does not exist")
            del store[item_id]
            await save_cluster_metadata(request, metadata)

        registry.register(base, "GET", list_items)
        registry.register(base, "POST", create)
        registry.register(f"{base}/{{id}}", "GET", get)
        registry.register(f"{base}/{{id}}", "PUT", update)
        registry.register(f"{base}/{{id}}", "DELETE", delete)

    registry.register("/cluster/mapping", "GET", index)
    register_kind("dir")
    register_kind("pci")
    register_kind("usb")
