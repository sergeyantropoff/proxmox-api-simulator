"""Cluster notifications endpoints and matchers persisted in metadata."""

from __future__ import annotations

import time
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import cluster_metadata, save_cluster_metadata, subdirs, values

_SECRET_KEYS = frozenset({"token", "password", "secret"})


def _public(endpoint: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in endpoint.items() if key not in _SECRET_KEYS}


def _notifications(metadata: dict[str, Any]) -> dict[str, Any]:
    current = metadata.get("notifications")
    if not isinstance(current, dict):
        return {
            "endpoints": {"gotify": {}, "sendmail": {}, "smtp": {}, "webhook": {}},
            "matchers": {},
            "tests": [],
        }
    endpoints = current.get("endpoints")
    if not isinstance(endpoints, dict):
        endpoints = {}
    result = {
        key: value
        for key, value in current.items()
        if key not in {"endpoints", "matchers", "tests"}
    }
    result["endpoints"] = {
        "gotify": dict(endpoints["gotify"]) if isinstance(endpoints.get("gotify"), dict) else {},
        "sendmail": (
            dict(endpoints["sendmail"]) if isinstance(endpoints.get("sendmail"), dict) else {}
        ),
        "smtp": dict(endpoints["smtp"]) if isinstance(endpoints.get("smtp"), dict) else {},
        "webhook": dict(endpoints["webhook"]) if isinstance(endpoints.get("webhook"), dict) else {},
    }
    result["matchers"] = (
        dict(current["matchers"]) if isinstance(current.get("matchers"), dict) else {}
    )
    result["tests"] = list(current["tests"]) if isinstance(current.get("tests"), list) else []
    return result


def register_notifications_handlers(registry: HandlerRegistry) -> None:
    async def index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs(
            "endpoints",
            "matcher-field-values",
            "matcher-fields",
            "matchers",
            "targets",
        )

    async def endpoints_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("gotify", "sendmail", "smtp", "webhook")

    def register_kind(kind: str, create_keys: tuple[str, ...]) -> None:
        base = f"/cluster/notifications/endpoints/{kind}"

        async def list_endpoints(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
            metadata = await cluster_metadata(request)
            store = _notifications(metadata)["endpoints"].get(kind) or {}
            return [_public({"name": name, **item}) for name, item in sorted(store.items())]

        async def create(request: Request, inputs: dict[str, Any]) -> None:
            payload = values(inputs)
            name = str(payload["name"])
            metadata = await cluster_metadata(request)
            notifications = _notifications(metadata)
            store = notifications["endpoints"].setdefault(kind, {})
            if name in store:
                raise ApiError(400, f"{kind} endpoint '{name}' already exists")
            entry = {key: payload[key] for key in create_keys if key in payload}
            entry["name"] = name
            entry.setdefault("disable", 0)
            store[name] = entry
            metadata["notifications"] = notifications
            await save_cluster_metadata(request, metadata)

        async def get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            name = str(values(inputs)["name"])
            metadata = await cluster_metadata(request)
            store = _notifications(metadata)["endpoints"].get(kind) or {}
            if name not in store:
                raise ApiError(404, f"{kind} endpoint does not exist")
            return _public({"name": name, **store[name]})

        async def update(request: Request, inputs: dict[str, Any]) -> None:
            payload = values(inputs)
            name = str(payload["name"])
            metadata = await cluster_metadata(request)
            notifications = _notifications(metadata)
            store = notifications["endpoints"].setdefault(kind, {})
            if name not in store:
                raise ApiError(404, f"{kind} endpoint does not exist")
            current = dict(store[name])
            delete_keys = [
                item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
            ]
            for key in delete_keys:
                current.pop(key, None)
            for key, value in payload.items():
                if key in {"name", "delete", "digest"}:
                    continue
                current[key] = value
            current["name"] = name
            store[name] = current
            metadata["notifications"] = notifications
            await save_cluster_metadata(request, metadata)

        async def delete(request: Request, inputs: dict[str, Any]) -> None:
            name = str(values(inputs)["name"])
            metadata = await cluster_metadata(request)
            notifications = _notifications(metadata)
            store = notifications["endpoints"].setdefault(kind, {})
            if name not in store:
                raise ApiError(404, f"{kind} endpoint does not exist")
            del store[name]
            metadata["notifications"] = notifications
            await save_cluster_metadata(request, metadata)

        registry.register(base, "GET", list_endpoints)
        registry.register(base, "POST", create)
        registry.register(f"{base}/{{name}}", "GET", get)
        registry.register(f"{base}/{{name}}", "PUT", update)
        registry.register(f"{base}/{{name}}", "DELETE", delete)

    async def matchers_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        store = _notifications(metadata)["matchers"]
        return [{"name": name, **item} for name, item in sorted(store.items())]

    async def matchers_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        name = str(payload["name"])
        metadata = await cluster_metadata(request)
        notifications = _notifications(metadata)
        store = notifications["matchers"]
        if name in store:
            raise ApiError(400, f"matcher '{name}' already exists")
        store[name] = {
            key: value for key, value in payload.items() if key not in {"delete", "digest"}
        }
        metadata["notifications"] = notifications
        await save_cluster_metadata(request, metadata)

    async def matchers_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        name = str(values(inputs)["name"])
        metadata = await cluster_metadata(request)
        store = _notifications(metadata)["matchers"]
        if name not in store:
            raise ApiError(404, "matcher does not exist")
        return {"name": name, **store[name]}

    async def matchers_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        name = str(payload["name"])
        metadata = await cluster_metadata(request)
        notifications = _notifications(metadata)
        store = notifications["matchers"]
        if name not in store:
            raise ApiError(404, "matcher does not exist")
        current = dict(store[name])
        for key in [
            item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
        ]:
            current.pop(key, None)
        for key, value in payload.items():
            if key in {"name", "delete", "digest"}:
                continue
            current[key] = value
        current["name"] = name
        store[name] = current
        metadata["notifications"] = notifications
        await save_cluster_metadata(request, metadata)

    async def matchers_delete(request: Request, inputs: dict[str, Any]) -> None:
        name = str(values(inputs)["name"])
        metadata = await cluster_metadata(request)
        notifications = _notifications(metadata)
        store = notifications["matchers"]
        if name not in store:
            raise ApiError(404, "matcher does not exist")
        del store[name]
        metadata["notifications"] = notifications
        await save_cluster_metadata(request, metadata)

    async def matcher_fields(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        fields = _notifications(metadata).get("matcher_fields")
        if isinstance(fields, list):
            return [dict(item) for item in fields if isinstance(item, dict)]
        return []

    async def matcher_field_values(
        request: Request, _inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        values_list = _notifications(metadata).get("matcher_field_values")
        if isinstance(values_list, list):
            return [dict(item) for item in values_list if isinstance(item, dict)]
        return []

    async def targets(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        notifications = _notifications(metadata)
        result: list[dict[str, Any]] = []
        for kind, store in (notifications.get("endpoints") or {}).items():
            if not isinstance(store, dict):
                continue
            for name, item in store.items():
                result.append(
                    {
                        "name": name,
                        "type": kind,
                        "comment": item.get("comment", ""),
                        "disable": int(bool(item.get("disable"))),
                    }
                )
        return result

    async def target_test(request: Request, inputs: dict[str, Any]) -> None:
        name = str(values(inputs)["name"])
        metadata = await cluster_metadata(request)
        notifications = _notifications(metadata)
        found = False
        for store in (notifications.get("endpoints") or {}).values():
            if isinstance(store, dict) and name in store:
                found = True
                break
        if not found:
            raise ApiError(404, "notification target does not exist")
        tests = list(notifications.get("tests") or [])
        tests.append({"name": name, "tested_at": int(time.time()), "ok": True})
        notifications["tests"] = tests
        metadata["notifications"] = notifications
        await save_cluster_metadata(request, metadata)

    registry.register("/cluster/notifications", "GET", index)
    registry.register("/cluster/notifications/endpoints", "GET", endpoints_index)
    register_kind("gotify", ("comment", "disable", "name", "server", "token"))
    register_kind(
        "sendmail",
        ("author", "comment", "disable", "from-address", "mailto", "mailto-user", "name"),
    )
    register_kind(
        "smtp",
        (
            "author",
            "comment",
            "disable",
            "from-address",
            "mailto",
            "mailto-user",
            "mode",
            "name",
            "password",
            "port",
            "server",
            "username",
        ),
    )
    register_kind(
        "webhook",
        ("body", "comment", "disable", "header", "method", "name", "secret", "url"),
    )
    registry.register("/cluster/notifications/matchers", "GET", matchers_list)
    registry.register("/cluster/notifications/matchers", "POST", matchers_create)
    registry.register("/cluster/notifications/matchers/{name}", "GET", matchers_get)
    registry.register("/cluster/notifications/matchers/{name}", "PUT", matchers_update)
    registry.register("/cluster/notifications/matchers/{name}", "DELETE", matchers_delete)
    registry.register("/cluster/notifications/matcher-fields", "GET", matcher_fields)
    registry.register("/cluster/notifications/matcher-field-values", "GET", matcher_field_values)
    registry.register("/cluster/notifications/targets", "GET", targets)
    registry.register("/cluster/notifications/targets/{name}/test", "POST", target_test)
