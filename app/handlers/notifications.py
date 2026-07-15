"""Cluster notifications endpoints and matchers persisted in metadata."""

from __future__ import annotations

import time
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import cluster_metadata, save_cluster_metadata, subdirs, values

_SECRET_KEYS = frozenset({"token", "password", "secret"})

DEFAULT_MATCHER_FIELDS = [
    {"name": "type", "type": "string"},
    {"name": "hostname", "type": "string"},
    {"name": "job-id", "type": "string"},
    {"name": "severity", "type": "string"},
]

DEFAULT_MATCHER_FIELD_VALUES = [
    {"field": "type", "value": "fencing"},
    {"field": "type", "value": "package-updates"},
    {"field": "type", "value": "replication"},
    {"field": "type", "value": "system-mail"},
]


def _public(endpoint: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in endpoint.items() if key not in _SECRET_KEYS}


def _notifications(metadata: dict[str, Any]) -> dict[str, Any]:
    current = metadata.setdefault(
        "notifications",
        {
            "endpoints": {
                "gotify": {},
                "sendmail": {},
                "smtp": {},
                "webhook": {},
            },
            "matchers": {},
            "tests": [],
        },
    )
    if not isinstance(current, dict):
        current = {
            "endpoints": {"gotify": {}, "sendmail": {}, "smtp": {}, "webhook": {}},
            "matchers": {},
            "tests": [],
        }
        metadata["notifications"] = current
    current.setdefault(
        "endpoints",
        {"gotify": {}, "sendmail": {}, "smtp": {}, "webhook": {}},
    )
    current.setdefault("matchers", {})
    current.setdefault("tests", [])
    return current


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
            store = _notifications(metadata)["endpoints"].setdefault(kind, {})
            return [_public({"name": name, **item}) for name, item in sorted(store.items())]

        async def create(request: Request, inputs: dict[str, Any]) -> None:
            payload = values(inputs)
            name = str(payload["name"])
            metadata = await cluster_metadata(request)
            store = _notifications(metadata)["endpoints"].setdefault(kind, {})
            if name in store:
                raise ApiError(400, f"{kind} endpoint '{name}' already exists")
            entry = {key: payload[key] for key in create_keys if key in payload}
            entry["name"] = name
            entry.setdefault("disable", 0)
            store[name] = entry
            await save_cluster_metadata(request, metadata)

        async def get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            name = str(values(inputs)["name"])
            metadata = await cluster_metadata(request)
            store = _notifications(metadata)["endpoints"].setdefault(kind, {})
            if name not in store:
                raise ApiError(404, f"{kind} endpoint does not exist")
            return _public({"name": name, **store[name]})

        async def update(request: Request, inputs: dict[str, Any]) -> None:
            payload = values(inputs)
            name = str(payload["name"])
            metadata = await cluster_metadata(request)
            store = _notifications(metadata)["endpoints"].setdefault(kind, {})
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
            await save_cluster_metadata(request, metadata)

        async def delete(request: Request, inputs: dict[str, Any]) -> None:
            name = str(values(inputs)["name"])
            metadata = await cluster_metadata(request)
            store = _notifications(metadata)["endpoints"].setdefault(kind, {})
            if name not in store:
                raise ApiError(404, f"{kind} endpoint does not exist")
            del store[name]
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
        store = _notifications(metadata)["matchers"]
        if name in store:
            raise ApiError(400, f"matcher '{name}' already exists")
        store[name] = {
            key: value for key, value in payload.items() if key not in {"delete", "digest"}
        }
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
        store = _notifications(metadata)["matchers"]
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
        await save_cluster_metadata(request, metadata)

    async def matchers_delete(request: Request, inputs: dict[str, Any]) -> None:
        name = str(values(inputs)["name"])
        metadata = await cluster_metadata(request)
        store = _notifications(metadata)["matchers"]
        if name not in store:
            raise ApiError(404, "matcher does not exist")
        del store[name]
        await save_cluster_metadata(request, metadata)

    async def matcher_fields(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return list(DEFAULT_MATCHER_FIELDS)

    async def matcher_field_values(
        _request: Request, _inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return list(DEFAULT_MATCHER_FIELD_VALUES)

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
        tests = notifications.setdefault("tests", [])
        if not isinstance(tests, list):
            tests = notifications["tests"] = []
        tests.append({"name": name, "tested_at": int(time.time()), "ok": True})
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
