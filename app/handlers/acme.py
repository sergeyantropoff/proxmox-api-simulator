"""Cluster ACME accounts and DNS plugins."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import cluster_metadata, save_cluster_metadata, subdirs, values

_DEFAULT_DIRECTORIES = [
    {
        "name": "Let's Encrypt V2",
        "url": "https://acme-v02.api.letsencrypt.org/directory",
    },
    {
        "name": "Let's Encrypt V2 Staging",
        "url": "https://acme-staging-v02.api.letsencrypt.org/directory",
    },
]

_CHALLENGE_SCHEMA = [
    {
        "id": "dns",
        "name": "DNS plugin",
        "type": "dns",
        "fields": [{"name": "api", "type": "string"}],
    }
]


def _acme(metadata: dict[str, Any]) -> dict[str, Any]:
    current = metadata.setdefault(
        "acme",
        {"accounts": {}, "plugins": {}, "meta": {}},
    )
    if not isinstance(current, dict):
        current = {"accounts": {}, "plugins": {}, "meta": {}}
        metadata["acme"] = current
    current.setdefault("accounts", {})
    current.setdefault("plugins", {})
    current.setdefault("meta", {})
    return current


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

    async def account_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        name = str(payload.get("name") or "default")
        metadata = await cluster_metadata(request)
        accounts = _acme(metadata)["accounts"]
        if name in accounts:
            raise ApiError(400, f"ACME account '{name}' already exists")
        accounts[name] = {
            "name": name,
            "contact": payload.get("contact"),
            "directory": payload.get("directory") or _DEFAULT_DIRECTORIES[0]["url"],
            "tos_url": payload.get("tos_url"),
            "eab-kid": payload.get("eab-kid"),
            # eab-hmac-key stored but never returned
            "eab-hmac-key": payload.get("eab-hmac-key"),
            "location": f"https://acme.example.local/acct/{name}",
        }
        await save_cluster_metadata(request, metadata)

    async def account_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        name = str(values(inputs)["name"])
        metadata = await cluster_metadata(request)
        account = _acme(metadata)["accounts"].get(name)
        if not isinstance(account, dict):
            raise ApiError(404, "ACME account does not exist")
        return {
            "name": name,
            "contact": account.get("contact"),
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
            result.append({"plugin": plugin_id, **{k: v for k, v in item.items() if k != "data"}})
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

    async def directories(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return list(_DEFAULT_DIRECTORIES)

    async def challenge_schema(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return list(_CHALLENGE_SCHEMA)

    async def meta(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        directory = str(values(inputs).get("directory") or _DEFAULT_DIRECTORIES[0]["url"])
        metadata = await cluster_metadata(request)
        meta_store = _acme(metadata).setdefault("meta", {})
        payload = meta_store.setdefault(
            directory,
            {
                "termsOfService": f"{directory.rstrip('/')}/tos",
                "caaIdentities": ["letsencrypt.org"],
            },
        )
        await save_cluster_metadata(request, metadata)
        return dict(payload)

    async def tos(request: Request, inputs: dict[str, Any]) -> str:
        directory = str(values(inputs).get("directory") or _DEFAULT_DIRECTORIES[0]["url"])
        result = await meta(request, {"values": {"directory": directory}, "provided": frozenset()})
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
