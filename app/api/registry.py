"""Contract-driven dynamic route and semantic handler registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors import ApiError, ContractValidationError
from app.config import Settings
from app.contracts.model import Method, Schema, Snapshot
from app.db.pool import AsyncpgDatabase
from app.security.acl import AclEntry, CapabilityRequirement, authorize, requirement_from_contract
from app.security.auth import parse_api_token, verify_csrf, verify_secret, verify_ticket

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

    def keys(self) -> frozenset[tuple[str, str]]:
        return frozenset(self._handlers)


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
        inputs = await _parse_inputs(request, method)
        await _authenticate(request, semantic_path, method, inputs)
        handler = handlers.get(semantic_path, method.verb)
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
        content = {"data": data, "success": True} if renderer == "extjs" else {"data": data}
        response = JSONResponse(content)
        if semantic_path == "/access/ticket" and isinstance(data, dict):
            ticket = data.get("ticket")
            if isinstance(ticket, str):
                response.set_cookie(
                    "PVEAuthCookie", ticket, httponly=True, samesite="strict", path="/"
                )
        return response

    return dispatch


async def _authenticate(
    request: Request, semantic_path: str, method: Method, inputs: dict[str, Any]
) -> None:
    if semantic_path in {"/version", "/access/ticket"}:
        return
    authorization = request.headers.get("Authorization", "")
    token_privileges: frozenset[str] | None = None
    principal: str
    if authorization.startswith("PVEAPIToken="):
        database = cast(AsyncpgDatabase, request.app.state.database)
        try:
            parsed_token = parse_api_token(authorization)
        except ValueError as error:
            raise ApiError(401, "authentication failure") from error
        row = await database.pool.fetchrow(
            """SELECT p.name, t.secret_hash, t.privileges, t.privilege_separation
            FROM api_tokens t JOIN principals p ON p.id=t.principal_id
            WHERE p.name=$1 AND t.token_id=$2
              AND (t.expires_at IS NULL OR t.expires_at > now())""",
            parsed_token.principal,
            parsed_token.token_id,
        )
        if row is None or not verify_secret(parsed_token.secret, str(row["secret_hash"])):
            raise ApiError(401, "authentication failure")
        principal = str(row["name"])
        token_privileges = (
            frozenset(str(item) for item in row["privileges"])
            if bool(row["privilege_separation"])
            else None
        )
    else:
        ticket = request.cookies.get("PVEAuthCookie")
        if ticket is None:
            raise ApiError(401, "authentication required")
        settings = cast(Settings, request.app.state.settings)
        key = settings.ticket_signing_key.get_secret_value().encode()
        try:
            claims = verify_ticket(ticket, key)
        except ValueError as error:
            raise ApiError(401, "authentication failure") from error
        principal = claims.principal
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf_value = request.headers.get("CSRFPreventionToken", "")
            if not verify_csrf(ticket, csrf_value, key):
                raise ApiError(403, "invalid CSRF prevention token")
    request.state.principal = principal
    if principal == "root@pam" and token_privileges is None:
        return
    database = cast(AsyncpgDatabase, request.app.state.database)
    await _authorize(database, principal, token_privileges, semantic_path, method, inputs)


async def _authorize(
    database: AsyncpgDatabase,
    principal: str,
    token_privileges: frozenset[str] | None,
    semantic_path: str,
    method: Method,
    inputs: dict[str, Any],
) -> None:
    values = cast(dict[str, Any], inputs["values"])
    requirement = requirement_from_contract(
        method.permissions, {name: str(value) for name, value in values.items()}
    )
    if requirement is None and semantic_path == "/nodes/{node}/qemu" and method.verb == "POST":
        requirement = CapabilityRequirement(f"/vms/{values['vmid']}", frozenset({"VM.Allocate"}))
    if requirement is None:
        return
    rows = await database.pool.fetch(
        """SELECT a.path, a.propagate, r.privileges
        FROM acl_entries a JOIN roles r ON r.name=a.role_name
        JOIN principals p ON p.id=a.principal_id WHERE p.name=$1
        UNION ALL
        SELECT a.path, a.propagate, r.privileges
        FROM group_acl_entries a JOIN roles r ON r.name=a.role_name
        JOIN identity_group_members m ON m.group_id=a.group_id
        JOIN principals p ON p.id=m.principal_id WHERE p.name=$1""",
        principal,
    )
    entries = tuple(
        AclEntry(
            principal,
            str(row["path"]),
            frozenset(str(item) for item in row["privileges"]),
            bool(row["propagate"]),
        )
        for row in rows
    )
    if not authorize(
        principal,
        requirement.path,
        requirement.privileges,
        entries,
        token_privileges=token_privileges,
        require_all=requirement.require_all,
    ):
        raise ApiError(403, "permission check failed")


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
    return {
        "values": parsed,
        "path": dict(request.path_params),
        "provided": tuple(sorted(supplied)),
    }


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
