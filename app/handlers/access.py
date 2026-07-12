"""Persistent Proxmox API-token lifecycle handlers."""

from __future__ import annotations

import secrets
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.security.auth import hash_secret


def _database(request: Request) -> AsyncpgDatabase:
    return cast(AsyncpgDatabase, request.app.state.database)


def _values(inputs: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], inputs["values"])


def _require_owner(request: Request, userid: str) -> None:
    principal = str(request.state.principal)
    if principal != "root@pam" and principal != userid:
        raise ApiError(403, "permission check failed")


def _token_info(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"privsep": bool(row["privilege_separation"])}
    if row["comment"] is not None:
        result["comment"] = str(row["comment"])
    if row["expire"] is not None:
        result["expire"] = int(row["expire"])
    return result


def _expire_value(values: dict[str, Any]) -> int | None:
    value = values.get("expire")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def register_access_handlers(registry: HandlerRegistry) -> None:
    async def token_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        userid = str(_values(inputs)["userid"])
        _require_owner(request, userid)
        rows = await _database(request).pool.fetch(
            """SELECT t.token_id, t.comment, t.privilege_separation,
            extract(epoch from t.expires_at)::bigint AS expire
            FROM api_tokens t JOIN principals p ON p.id=t.principal_id
            WHERE p.name=$1 ORDER BY t.token_id""",
            userid,
        )
        return [{"tokenid": str(row["token_id"]), **_token_info(row)} for row in rows]

    async def token_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        userid, tokenid = str(values["userid"]), str(values["tokenid"])
        _require_owner(request, userid)
        row = await _database(request).pool.fetchrow(
            """SELECT t.comment, t.privilege_separation,
            extract(epoch from t.expires_at)::bigint AS expire
            FROM api_tokens t JOIN principals p ON p.id=t.principal_id
            WHERE p.name=$1 AND t.token_id=$2""",
            userid,
            tokenid,
        )
        if row is None:
            raise ApiError(404, "API token does not exist")
        return _token_info(row)

    async def token_create(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        userid, tokenid = str(values["userid"]), str(values["tokenid"])
        _require_owner(request, userid)
        secret = secrets.token_urlsafe(32)
        row = await _database(request).pool.fetchrow(
            """INSERT INTO api_tokens(
                principal_id, token_id, secret_hash, comment, expires_at,
                privilege_separation
            ) SELECT id, $2, $3, $4,
                CASE WHEN $5::bigint IS NULL OR $5=0 THEN NULL ELSE to_timestamp($5) END,
                $6 FROM principals WHERE name=$1
            ON CONFLICT (principal_id, token_id) DO NOTHING
            RETURNING comment, privilege_separation,
                extract(epoch from expires_at)::bigint AS expire""",
            userid,
            tokenid,
            hash_secret(secret),
            values.get("comment"),
            _expire_value(values),
            bool(values.get("privsep", True)),
        )
        if row is None:
            exists = await _database(request).pool.fetchval(
                "SELECT EXISTS(SELECT 1 FROM principals WHERE name=$1)", userid
            )
            raise ApiError(409 if exists else 404, "user or API token conflict")
        return {"full-tokenid": f"{userid}!{tokenid}", "info": _token_info(row), "value": secret}

    async def token_update(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        provided = frozenset(str(item) for item in inputs.get("provided", values))
        userid, tokenid = str(values["userid"]), str(values["tokenid"])
        _require_owner(request, userid)
        regenerate = bool(values.get("regenerate", False))
        secret = secrets.token_urlsafe(32) if regenerate else None
        row = await _database(request).pool.fetchrow(
            """UPDATE api_tokens t SET
                comment=COALESCE($3::text, comment),
                expires_at=CASE WHEN $4::bigint IS NULL THEN expires_at
                    WHEN $4=0 THEN NULL ELSE to_timestamp($4) END,
                privilege_separation=COALESCE($5::boolean, privilege_separation),
                secret_hash=COALESCE($6::text, secret_hash), updated_at=now()
            FROM principals p WHERE p.id=t.principal_id AND p.name=$1 AND t.token_id=$2
            RETURNING t.comment, t.privilege_separation,
                extract(epoch from t.expires_at)::bigint AS expire""",
            userid,
            tokenid,
            values.get("comment") if "comment" in provided else None,
            _expire_value(values) if "expire" in provided else None,
            values.get("privsep") if "privsep" in provided else None,
            hash_secret(secret) if secret is not None else None,
        )
        if row is None:
            raise ApiError(404, "API token does not exist")
        result = _token_info(row)
        if secret is not None:
            result.update({"full-tokenid": f"{userid}!{tokenid}", "value": secret})
        return result

    async def token_delete(request: Request, inputs: dict[str, Any]) -> None:
        values = _values(inputs)
        userid, tokenid = str(values["userid"]), str(values["tokenid"])
        _require_owner(request, userid)
        status = await _database(request).pool.execute(
            """DELETE FROM api_tokens t USING principals p
            WHERE p.id=t.principal_id AND p.name=$1 AND t.token_id=$2""",
            userid,
            tokenid,
        )
        if status != "DELETE 1":
            raise ApiError(404, "API token does not exist")

    registry.register("/access/users/{userid}/token", "GET", token_list)
    registry.register("/access/users/{userid}/token/{tokenid}", "GET", token_get)
    registry.register("/access/users/{userid}/token/{tokenid}", "POST", token_create)
    registry.register("/access/users/{userid}/token/{tokenid}", "PUT", token_update)
    registry.register("/access/users/{userid}/token/{tokenid}", "DELETE", token_delete)
