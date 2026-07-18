"""Cluster ACME accounts and DNS plugins."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import cluster_metadata, save_cluster_metadata, subdirs, values


def _acme(metadata: dict[str, Any]) -> dict[str, Any]:
    current = metadata.get("acme")
    if not isinstance(current, dict):
        current = {}
        metadata["acme"] = current
    if not isinstance(current.get("accounts"), dict):
        current["accounts"] = {}
    if not isinstance(current.get("plugins"), dict):
        current["plugins"] = {}
    if not isinstance(current.get("meta"), dict):
        current["meta"] = {}
    if not isinstance(current.get("directories"), list):
        current["directories"] = []
    if not isinstance(current.get("challenge_schema"), list):
        current["challenge_schema"] = []
    return current


def _default_directory(acme: dict[str, Any]) -> str:
    directories = acme.get("directories")
    if isinstance(directories, list):
        for item in directories:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    return "https://acme-v02.api.letsencrypt.org/directory"


def register_acme_handlers(registry: HandlerRegistry) -> None:
    async def index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs(
            "account",
            "challenge-schema",
            "directories",
            "meta",
            "plugins",
            "tos",
        )

    async def account_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        accounts = _acme(metadata)["accounts"]
        return [
            {
                "name": name,
                "contact": item.get("contact", []),
                "directory": item.get("directory"),
            }
            for name, item in sorted(accounts.items())
        ]

    async def account_create(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        name = str(payload.get("name") or "default")
        metadata = await cluster_metadata(request)
        acme = _acme(metadata)
        accounts = acme["accounts"]
        if name in accounts:
            raise ApiError(400, f"ACME account '{name}' already exists")
        directory = str(payload.get("directory") or _default_directory(acme))
        accounts[name] = {
            "name": name,
            "contact": payload.get("contact"),
            "directory": directory,
            "tos_url": payload.get("tos_url"),
            "eab-kid": payload.get("eab-kid"),
            "eab-hmac-key": payload.get("eab-hmac-key"),
            "location": f"https://acme.example.local/acct/{name}",
        }
        await save_cluster_metadata(request, metadata)
        return name

    async def account_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        name = str(values(inputs)["name"])
        metadata = await cluster_metadata(request)
        account = _acme(metadata)["accounts"].get(name)
        if not isinstance(account, dict):
            raise ApiError(404, "ACME account does not exist")
        return {
            "account": {
                "name": name,
                "contact": account.get("contact"),
            },
            "directory": account.get("directory"),
            "tos": account.get("tos_url"),
            "location": account.get("location"),
        }

    async def account_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        name = str(payload["name"])
        metadata = await cluster_metadata(request)
        accounts = _acme(metadata)["accounts"]
        if name not in accounts:
            raise ApiError(404, "ACME account does not exist")
        if "contact" in payload:
            accounts[name]["contact"] = payload["contact"]
        await save_cluster_metadata(request, metadata)

    async def account_delete(request: Request, inputs: dict[str, Any]) -> None:
        name = str(values(inputs)["name"])
        metadata = await cluster_metadata(request)
        accounts = _acme(metadata)["accounts"]
        if name not in accounts:
            raise ApiError(404, "ACME account does not exist")
        del accounts[name]
        await save_cluster_metadata(request, metadata)

    async def plugins_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        plugins = _acme(metadata)["plugins"]
        plugin_type = values(inputs).get("type")
        result = []
        for plugin_id, item in sorted(plugins.items()):
            if plugin_type and item.get("type") != plugin_type:
                continue
            entry = {"plugin": plugin_id, **{k: v for k, v in item.items() if k != "data"}}
            if "digest" not in entry:
                material = {k: v for k, v in entry.items() if k != "digest"}
                entry["digest"] = hashlib.sha1(  # noqa: S324 - Proxmox config digests use SHA-1
                    json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
            result.append(entry)
        return result

    async def plugins_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        plugin_id = str(payload["id"])
        metadata = await cluster_metadata(request)
        plugins = _acme(metadata)["plugins"]
        if plugin_id in plugins:
            raise ApiError(400, f"ACME plugin '{plugin_id}' already exists")
        plugins[plugin_id] = {
            key: value for key, value in payload.items() if key not in {"delete", "digest"}
        }
        await save_cluster_metadata(request, metadata)

    async def plugins_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        plugin_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        plugin = _acme(metadata)["plugins"].get(plugin_id)
        if not isinstance(plugin, dict):
            raise ApiError(404, "ACME plugin does not exist")
        return {"id": plugin_id, **plugin}

    async def plugins_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        plugin_id = str(payload["id"])
        metadata = await cluster_metadata(request)
        plugins = _acme(metadata)["plugins"]
        if plugin_id not in plugins:
            raise ApiError(404, "ACME plugin does not exist")
        current = dict(plugins[plugin_id])
        for key in [
            item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
        ]:
            current.pop(key, None)
        for key, value in payload.items():
            if key in {"id", "delete", "digest"}:
                continue
            current[key] = value
        current["id"] = plugin_id
        plugins[plugin_id] = current
        await save_cluster_metadata(request, metadata)

    async def plugins_delete(request: Request, inputs: dict[str, Any]) -> None:
        plugin_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        plugins = _acme(metadata)["plugins"]
        if plugin_id not in plugins:
            raise ApiError(404, "ACME plugin does not exist")
        del plugins[plugin_id]
        await save_cluster_metadata(request, metadata)

    async def directories(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        directories = _acme(metadata).get("directories")
        if isinstance(directories, list):
            return [dict(item) for item in directories if isinstance(item, dict)]
        return []

    async def challenge_schema(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        schema = _acme(metadata).get("challenge_schema")
        if isinstance(schema, list):
            return [dict(item) for item in schema if isinstance(item, dict)]
        return []

    async def meta(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        acme = _acme(metadata)
        directory = str(values(inputs).get("directory") or _default_directory(acme))
        meta_raw = acme.get("meta")
        meta_store: dict[str, Any] = dict(meta_raw) if isinstance(meta_raw, dict) else {}
        payload = meta_store.get(directory)
        if not isinstance(payload, dict):
            return {}
        return dict(payload)

    async def tos(request: Request, inputs: dict[str, Any]) -> str:
        result = await meta(request, inputs)
        return str(result.get("termsOfService") or "")

    registry.register("/cluster/acme", "GET", index)
    registry.register("/cluster/acme/account", "GET", account_list)
    registry.register("/cluster/acme/account", "POST", account_create)
    registry.register("/cluster/acme/account/{name}", "GET", account_get)
    registry.register("/cluster/acme/account/{name}", "PUT", account_update)
    registry.register("/cluster/acme/account/{name}", "DELETE", account_delete)
    registry.register("/cluster/acme/plugins", "GET", plugins_list)
    registry.register("/cluster/acme/plugins", "POST", plugins_create)
    registry.register("/cluster/acme/plugins/{id}", "GET", plugins_get)
    registry.register("/cluster/acme/plugins/{id}", "PUT", plugins_update)
    registry.register("/cluster/acme/plugins/{id}", "DELETE", plugins_delete)
    registry.register("/cluster/acme/directories", "GET", directories)
    registry.register("/cluster/acme/challenge-schema", "GET", challenge_schema)
    registry.register("/cluster/acme/meta", "GET", meta)
    registry.register("/cluster/acme/tos", "GET", tos)
