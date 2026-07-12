"""Contract-driven dynamic route and semantic handler registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.contracts.model import Method, Schema, Snapshot

Handler = Callable[[Request, dict[str, Any]], Awaitable[Any]]
FallbackMode = Literal["error", "schema-default", "fixture"]


class RouteCollisionError(ValueError):
    pass


@dataclass(slots=True)
class HandlerRegistry:
    _handlers: dict[tuple[str, str], Handler] = field(default_factory=dict)

    def register(self, path: str, verb: str, handler: Handler) -> None:
        key = (path, verb.upper())
        if key in self._handlers:
            raise RouteCollisionError(f"duplicate semantic handler: {verb} {path}")
        self._handlers[key] = handler

    def get(self, path: str, verb: str) -> Handler | None:
        return self._handlers.get((path, verb.upper()))


def register_contract_routes(
    app: FastAPI,
    snapshot: Snapshot,
    handlers: HandlerRegistry,
    fallback: FallbackMode = "error",
) -> None:
    seen: set[tuple[str, str, str]] = set()
    for contract_path in snapshot.paths:
        for contract_method in contract_path.methods:
            for renderer in ("json", "extjs"):
                route = f"/api2/{renderer}{contract_path.path}"
                key = (route, contract_method.verb, renderer)
                if key in seen:
                    raise RouteCollisionError(
                        f"duplicate contract route: {contract_method.verb} {route}"
                    )
                seen.add(key)
                endpoint = _endpoint(
                    contract_path.path,
                    contract_method,
                    renderer,
                    handlers,
                    fallback,
                )
                app.add_api_route(
                    route,
                    endpoint,
                    methods=[contract_method.verb],
                    name=f"contract:{renderer}:{contract_method.verb}:{contract_path.path}",
                    openapi_extra={"x-proxmox-method-checksum": contract_method.checksum},
                )


def _endpoint(
    semantic_path: str,
    method: Method,
    renderer: str,
    handlers: HandlerRegistry,
    fallback: FallbackMode,
) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def dispatch(request: Request) -> JSONResponse:
        handler = handlers.get(semantic_path, method.verb)
        inputs = {
            "path": dict(request.path_params),
            "query": dict(request.query_params),
        }
        if handler is not None:
            data = await handler(request, inputs)
        elif fallback == "schema-default":
            data = _schema_default(method.returns)
        elif fallback == "fixture" and "fixture" in method.extra:
            data = method.extra["fixture"]
        else:
            return JSONResponse(
                status_code=501,
                content={"data": None, "errors": "method semantics are not implemented"},
            )
        if renderer == "extjs":
            return JSONResponse({"data": data, "success": True})
        return JSONResponse({"data": data})

    return dispatch


def _schema_default(schema: Schema) -> Any:
    if schema.default is not None:
        return schema.default
    if schema.type == "array":
        return []
    if schema.type == "object":
        return {
            name: _schema_default(definition)
            for name, definition in schema.properties.items()
            if not definition.optional
        }
    if schema.type == "boolean":
        return False
    if schema.type in {"integer", "number"}:
        return 0
    return None
