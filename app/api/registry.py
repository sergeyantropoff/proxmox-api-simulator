"""Contract-driven dynamic route and semantic handler registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors import ContractValidationError
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
        inputs = await _parse_inputs(request, method)
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


async def _parse_inputs(request: Request, method: Method) -> dict[str, Any]:
    supplied: dict[str, Any] = dict(request.query_params)
    supplied.update(request.path_params)
    if request.method not in {"GET", "DELETE"}:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type == "application/json":
            try:
                body = await request.json()
            except ValueError as exc:
                raise ContractValidationError({"body": "invalid JSON"}) from exc
            if not isinstance(body, dict):
                raise ContractValidationError({"body": "expected an object"})
            supplied.update(body)
        elif content_type == "application/x-www-form-urlencoded":
            supplied.update(dict(parse_qsl((await request.body()).decode())))

    definitions = {parameter.name: parameter.definition for parameter in method.parameters}
    errors: dict[str, str] = {}
    parsed: dict[str, Any] = {}
    for name, definition in definitions.items():
        if name not in supplied:
            if definition.optional:
                if definition.default is not None:
                    parsed[name] = definition.default
                continue
            errors[name] = "property is missing and it is not optional"
            continue
        try:
            parsed[name] = _coerce(supplied[name], definition)
        except (TypeError, ValueError) as exc:
            errors[name] = str(exc)
    for name in supplied.keys() - definitions.keys():
        if name not in request.path_params:
            errors[name] = "property is not defined in schema"
    if errors:
        raise ContractValidationError(dict(sorted(errors.items())))
    return {"values": parsed, "path": dict(request.path_params)}


def _coerce(value: Any, schema: Schema) -> Any:
    if schema.type == "integer":
        parsed: Any = int(value)
    elif schema.type == "number":
        parsed = float(value)
    elif schema.type == "boolean":
        if isinstance(value, bool):
            parsed = value
        elif str(value).lower() in {"1", "true", "yes", "on"}:
            parsed = True
        elif str(value).lower() in {"0", "false", "no", "off"}:
            parsed = False
        else:
            raise ValueError("expected a boolean")
    elif schema.type == "string" or schema.type is None:
        parsed = str(value)
    else:
        parsed = value
    if schema.enum and parsed not in schema.enum:
        raise ValueError("value is not in the allowed enumeration")
    if isinstance(parsed, int | float):
        if schema.minimum is not None and parsed < schema.minimum:
            raise ValueError(f"value must be at least {schema.minimum}")
        if schema.maximum is not None and parsed > schema.maximum:
            raise ValueError(f"value must be at most {schema.maximum}")
    if isinstance(parsed, str):
        if schema.min_length is not None and len(parsed) < schema.min_length:
            raise ValueError(f"value is shorter than {schema.min_length}")
        if schema.max_length is not None and len(parsed) > schema.max_length:
            raise ValueError(f"value is longer than {schema.max_length}")
    return parsed


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
