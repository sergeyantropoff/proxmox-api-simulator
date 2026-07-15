"""Access TFA, OpenID, permissions, and ticket helpers with durable state."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast
from urllib.parse import urlencode

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.config import Settings
from app.handlers.common import database, values
from app.security.auth import AuthenticationError, csrf_token, issue_ticket, verify_ticket

_TFA_TYPES = frozenset({"totp", "u2f", "webauthn", "recovery", "yubico"})


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _tfa_public(row: Any) -> dict[str, Any]:
    created = row["created_at"]
    created_ts = int(created.timestamp()) if hasattr(created, "timestamp") else int(created or 0)
    return {
        "id": str(row["entry_id"]),
        "type": str(row["tfa_type"]),
        "description": row["description"] or "",
        "enable": int(bool(row["enable"])),
        "created": created_ts,
    }


async def _principal_row(request: Request, userid: str) -> Any:
    row = await database(request).pool.fetchrow(
        """SELECT id, name, tfa_locked_until, totp_locked
        FROM principals WHERE name=$1""",
        userid,
    )
    if row is None:
        raise ApiError(404, "user does not exist")
    return row


def register_access_auth_handlers(registry: HandlerRegistry) -> None:
    async def ticket_get(_request: Request, _inputs: dict[str, Any]) -> None:
        return None

    async def permissions(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        userid = str(payload.get("userid") or request.state.principal)
        path_filter = payload.get("path")
        if userid == "root@pam":
            caps = {
                "/": {
                    "Permissions.Modify": 1,
                    "Sys.Audit": 1,
                    "Sys.Modify": 1,
                    "VM.Allocate": 1,
                    "VM.Audit": 1,
                    "VM.PowerMgmt": 1,
                    "Datastore.Allocate": 1,
                    "Datastore.Audit": 1,
                }
            }
            if path_filter:
                return {str(path_filter): caps["/"]}
            return caps

        rows = await database(request).pool.fetch(
            """SELECT a.path, r.privileges
            FROM acl_entries a
            JOIN principals p ON p.id=a.principal_id
            JOIN roles r ON r.name=a.role_name
            WHERE p.name=$1
            UNION ALL
            SELECT a.path, r.privileges
            FROM group_acl_entries a
            JOIN identity_groups g ON g.id=a.group_id
            JOIN identity_group_members m ON m.group_id=g.id
            JOIN principals p ON p.id=m.principal_id
            JOIN roles r ON r.name=a.role_name
            WHERE p.name=$1""",
            userid,
        )
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            path = str(row["path"])
            bucket = result.setdefault(path, {})
            for privilege in row["privileges"] or []:
                bucket[str(privilege)] = 1
        if path_filter:
            target = str(path_filter)
            merged: dict[str, int] = {}
            for path, privs in result.items():
                if target == path or target.startswith(path.rstrip("/") + "/") or path == "/":
                    merged.update(privs)
            return {target: merged} if merged else {}
        return result

    async def vncticket(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        ticket = str(payload["vncticket"])
        key = _settings(request).ticket_signing_key.get_secret_value().encode()
        try:
            claims = verify_ticket(ticket, key)
        except AuthenticationError as error:
            raise ApiError(401, "authentication failure") from error
        authid = str(payload["authid"])
        if claims.principal != authid:
            raise ApiError(401, "authentication failure")
        return None

    async def openid_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return [{"subdir": "auth-url"}, {"subdir": "login"}]

    async def openid_auth_url(request: Request, inputs: dict[str, Any]) -> str:
        payload = values(inputs)
        realm = str(payload["realm"])
        redirect_url = str(payload["redirect-url"])
        row = await database(request).pool.fetchrow(
            "SELECT name, kind, config FROM realms WHERE name=$1",
            realm,
        )
        if row is None:
            raise ApiError(404, "realm does not exist")
        if str(row["kind"]) != "openid":
            raise ApiError(400, "realm is not an OpenID realm")
        state = secrets.token_urlsafe(16)
        await database(request).pool.execute(
            """INSERT INTO openid_pending(state, realm, redirect_url)
            VALUES($1, $2, $3)
            ON CONFLICT (state) DO UPDATE
            SET realm=EXCLUDED.realm, redirect_url=EXCLUDED.redirect_url,
                created_at=now()""",
            state,
            realm,
            redirect_url,
        )
        config = row["config"]
        if isinstance(config, str):
            config = json.loads(config)
        config = config or {}
        issuer = str(config.get("issuer-url") or "https://openid.example.local")
        client_id = str(config.get("client-id") or "pve-simulator")
        query = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_url,
                "response_type": "code",
                "scope": str(config.get("scopes") or "openid email profile"),
                "state": state,
            }
        )
        return f"{issuer.rstrip('/')}/authorize?{query}"

    async def openid_login(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        state = str(payload["state"])
        pending = await database(request).pool.fetchrow(
            "SELECT realm, redirect_url FROM openid_pending WHERE state=$1",
            state,
        )
        if pending is None:
            raise ApiError(400, "invalid OpenID state")
        redirect = payload.get("redirect-url")
        if redirect is not None and str(redirect) != str(pending["redirect_url"]):
            raise ApiError(400, "redirect-url mismatch")
        realm = str(pending["realm"])
        code = str(payload["code"])
        username = f"openid-{code[:12]}@{realm}"
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM principals WHERE name=$1)",
            username,
        )
        if not exists:
            await database(request).pool.execute(
                """INSERT INTO principals(id, name, password_hash, realm_name)
                VALUES(gen_random_uuid(), $1, NULL, $2)""",
                username,
                realm,
            )
        await database(request).pool.execute(
            "DELETE FROM openid_pending WHERE state=$1",
            state,
        )
        key = _settings(request).ticket_signing_key.get_secret_value().encode()
        ticket = issue_ticket(username, key)
        return {
            "username": username,
            "ticket": ticket,
            "CSRFPreventionToken": csrf_token(ticket, key),
            "clustername": "pve-simulator",
            "cap": {},
        }

    async def tfa_list_all(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(request).pool.fetch(
            """SELECT p.name AS userid, p.tfa_locked_until, p.totp_locked,
                t.entry_id, t.tfa_type, t.description, t.enable, t.created_at
            FROM principals p
            LEFT JOIN tfa_entries t ON t.principal_id=p.id
            ORDER BY p.name, t.entry_id"""
        )
        by_user: dict[str, dict[str, Any]] = {}
        for row in rows:
            userid = str(row["userid"])
            item = by_user.setdefault(
                userid,
                {
                    "userid": userid,
                    "entries": [],
                    "totp-locked": int(bool(row["totp_locked"])),
                },
            )
            if row["tfa_locked_until"] is not None:
                locked = row["tfa_locked_until"]
                item["tfa-locked-until"] = (
                    int(locked.timestamp()) if hasattr(locked, "timestamp") else int(locked)
                )
            if row["entry_id"] is not None:
                item["entries"].append(_tfa_public(row))
        return list(by_user.values())

    async def tfa_list_user(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        userid = str(values(inputs)["userid"])
        principal = await _principal_row(request, userid)
        rows = await database(request).pool.fetch(
            """SELECT entry_id, tfa_type, description, enable, created_at
            FROM tfa_entries WHERE principal_id=$1 ORDER BY entry_id""",
            principal["id"],
        )
        return [_tfa_public(row) for row in rows]

    async def tfa_add(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        userid = payload.get("userid")
        if userid in {None, ""}:
            raise ApiError(400, "parameter 'userid' is required")
        userid = str(userid)
        tfa_type = payload.get("type")
        if tfa_type in {None, ""}:
            raise ApiError(400, "parameter 'type' is required")
        tfa_type = str(tfa_type)
        if tfa_type not in _TFA_TYPES:
            raise ApiError(400, f"invalid TFA type: {tfa_type}")
        principal = await _principal_row(request, userid)
        entry_id = secrets.token_hex(8)
        secret = str(payload.get("value") or payload.get("totp") or secrets.token_hex(20))
        description = str(payload.get("description") or tfa_type)
        recovery: list[str] = []
        metadata: dict[str, Any] = {}
        if tfa_type == "recovery":
            recovery = [secrets.token_hex(5) for _ in range(8)]
            metadata["recovery"] = recovery
        await database(request).pool.execute(
            """INSERT INTO tfa_entries(
                principal_id, entry_id, tfa_type, description, enable, secret, metadata
            ) VALUES($1, $2, $3, $4, true, $5, $6::jsonb)""",
            principal["id"],
            entry_id,
            tfa_type,
            description,
            secret,
            json.dumps(metadata, sort_keys=True),
        )
        result: dict[str, Any] = {"id": entry_id}
        if recovery:
            result["recovery"] = recovery
        if payload.get("challenge") is not None:
            result["challenge"] = payload.get("challenge")
        return result

    async def tfa_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        userid = str(values(inputs)["userid"])
        entry_id = str(values(inputs)["id"])
        principal = await _principal_row(request, userid)
        row = await database(request).pool.fetchrow(
            """SELECT entry_id, tfa_type, description, enable, created_at
            FROM tfa_entries WHERE principal_id=$1 AND entry_id=$2""",
            principal["id"],
            entry_id,
        )
        if row is None:
            raise ApiError(404, "TFA entry does not exist")
        return _tfa_public(row)

    async def tfa_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        userid = payload.get("userid")
        if userid in {None, ""}:
            raise ApiError(400, "parameter 'userid' is required")
        userid = str(userid)
        entry_id = payload.get("id")
        if entry_id in {None, ""}:
            raise ApiError(400, "parameter 'id' is required")
        entry_id = str(entry_id)
        provided = frozenset(str(item) for item in inputs.get("provided", payload))
        principal = await _principal_row(request, userid)
        row = await database(request).pool.fetchrow(
            "SELECT entry_id FROM tfa_entries WHERE principal_id=$1 AND entry_id=$2",
            principal["id"],
            entry_id,
        )
        if row is None:
            raise ApiError(404, "TFA entry does not exist")
        if "description" in provided:
            await database(request).pool.execute(
                """UPDATE tfa_entries SET description=$3
                WHERE principal_id=$1 AND entry_id=$2""",
                principal["id"],
                entry_id,
                payload.get("description"),
            )
        if "enable" in provided:
            enabled = payload.get("enable")
            if isinstance(enabled, bool):
                value = enabled
            else:
                value = str(enabled).lower() in {"1", "true", "yes", "on"}
            await database(request).pool.execute(
                """UPDATE tfa_entries SET enable=$3
                WHERE principal_id=$1 AND entry_id=$2""",
                principal["id"],
                entry_id,
                value,
            )

    async def tfa_delete(request: Request, inputs: dict[str, Any]) -> None:
        userid = str(values(inputs)["userid"])
        entry_id = str(values(inputs)["id"])
        principal = await _principal_row(request, userid)
        status = await database(request).pool.execute(
            "DELETE FROM tfa_entries WHERE principal_id=$1 AND entry_id=$2",
            principal["id"],
            entry_id,
        )
        if status != "DELETE 1":
            raise ApiError(404, "TFA entry does not exist")

    async def user_tfa_types(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        userid = str(values(inputs)["userid"])
        principal = await _principal_row(request, userid)
        rows = await database(request).pool.fetch(
            """SELECT DISTINCT tfa_type FROM tfa_entries
            WHERE principal_id=$1 AND enable=true ORDER BY tfa_type""",
            principal["id"],
        )
        types = [str(row["tfa_type"]) for row in rows]
        realm = userid.split("@", 1)[1] if "@" in userid else "pam"
        return {"user": types, "types": types, "realm": realm}

    async def unlock_tfa(request: Request, inputs: dict[str, Any]) -> bool:
        userid = str(values(inputs)["userid"])
        status = await database(request).pool.execute(
            """UPDATE principals
            SET tfa_locked_until=NULL, totp_locked=false
            WHERE name=$1""",
            userid,
        )
        if status != "UPDATE 1":
            raise ApiError(404, "user does not exist")
        return True

    registry.register("/access/ticket", "GET", ticket_get)
    registry.register("/access/permissions", "GET", permissions)
    registry.register("/access/vncticket", "POST", vncticket)
    registry.register("/access/openid", "GET", openid_index)
    registry.register("/access/openid/auth-url", "POST", openid_auth_url)
    registry.register("/access/openid/login", "POST", openid_login)
    registry.register("/access/tfa", "GET", tfa_list_all)
    registry.register("/access/tfa/{userid}", "GET", tfa_list_user)
    registry.register("/access/tfa/{userid}", "POST", tfa_add)
    registry.register("/access/tfa/{userid}/{id}", "GET", tfa_get)
    registry.register("/access/tfa/{userid}/{id}", "PUT", tfa_update)
    registry.register("/access/tfa/{userid}/{id}", "DELETE", tfa_delete)
    registry.register("/access/users/{userid}/tfa", "GET", user_tfa_types)
    registry.register("/access/users/{userid}/unlock-tfa", "PUT", unlock_tfa)
