"""Persistent Proxmox API-token lifecycle handlers."""

from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.access_auth import register_access_auth_handlers
from app.handlers.common import database, state, subdirs, values
from app.security.auth import hash_secret

_BUILTIN_REALMS = frozenset({"pam", "pve"})
_REALM_TYPES = frozenset({"ad", "ldap", "openid", "pam", "pve"})
_DOMAIN_SECRET_KEYS = frozenset({"password", "client-key", "certkey"})
_DOMAIN_META_KEYS = frozenset({"realm", "type", "delete", "digest", "check-connection"})


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


def _api_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise ApiError(400, f"invalid boolean value: {value}")


def _domain_config_value(value: object) -> object:
    if isinstance(value, bool):
        return int(value)
    return value


def _domain_payload(name: str, kind: str, config: object) -> dict[str, Any]:
    payload: dict[str, Any] = {"realm": name, "type": kind}
    for key, value in state(config).items():
        if key in _DOMAIN_SECRET_KEYS:
            continue
        payload[key] = _domain_config_value(value)
    return payload


_DOMAIN_BOOL_KEYS = frozenset(
    {
        "autocreate",
        "case-sensitive",
        "check-connection",
        "default",
        "groups-autocreate",
        "groups-overwrite",
        "query-userinfo",
        "secure",
        "verify",
    }
)


def _domain_config_from_payload(
    payload: dict[str, Any], *, provided: frozenset[str] | None = None
) -> dict[str, Any]:
    keys = provided if provided is not None else frozenset(payload)
    config: dict[str, Any] = {}
    for key in keys:
        if key in _DOMAIN_META_KEYS or key not in payload:
            continue
        value = payload[key]
        if key in _DOMAIN_BOOL_KEYS:
            config[key] = _api_bool(value)
        else:
            config[key] = value
    return config


def register_access_handlers(registry: HandlerRegistry) -> None:
    async def access_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs(
            "acl",
            "domains",
            "groups",
            "openid",
            "password",
            "permissions",
            "roles",
            "tfa",
            "ticket",
            "users",
        )

    async def user_list(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            """SELECT p.name, p.realm_name, p.password_hash IS NOT NULL AS enabled,
                COALESCE(r.kind, p.realm_name) AS realm_kind
            FROM principals p
            LEFT JOIN realms r ON r.name = p.realm_name
            ORDER BY p.name"""
        )
        return [
            {
                "userid": str(row["name"]),
                "enable": bool(row["enabled"]),
                "realm-type": str(row["realm_kind"]),
            }
            for row in rows
        ]

    async def user_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        userid = str(payload["userid"])
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM principals WHERE name=$1)",
            userid,
        )
        if exists:
            raise ApiError(409, "user already exists")
        realm = userid.split("@", 1)[1] if "@" in userid else "pve"
        realm_exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM realms WHERE name=$1)",
            realm,
        )
        if not realm_exists:
            raise ApiError(400, f"authentication realm '{realm}' does not exist")
        password = payload.get("password")
        await database(request).pool.execute(
            """INSERT INTO principals(id, name, password_hash, realm_name)
            VALUES(gen_random_uuid(), $1, $2, $3)""",
            userid,
            hash_secret(str(password)) if password else None,
            realm,
        )

    async def user_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        userid = str(values(inputs)["userid"])
        row = await database(request).pool.fetchrow(
            """SELECT p.name, p.realm_name, p.password_hash IS NOT NULL AS enabled,
                COALESCE(r.kind, p.realm_name) AS realm_kind
            FROM principals p
            LEFT JOIN realms r ON r.name = p.realm_name
            WHERE p.name=$1""",
            userid,
        )
        if row is None:
            raise ApiError(404, "user does not exist")
        groups = await database(request).pool.fetch(
            """SELECT g.group_id FROM identity_group_members m
            JOIN identity_groups g ON g.id = m.group_id
            JOIN principals p ON p.id = m.principal_id
            WHERE p.name=$1 ORDER BY g.group_id""",
            userid,
        )
        tokens = await database(request).pool.fetch(
            """SELECT t.token_id FROM api_tokens t
            JOIN principals p ON p.id = t.principal_id
            WHERE p.name=$1 ORDER BY t.token_id""",
            userid,
        )
        return {
            "userid": str(row["name"]),
            "enable": bool(row["enabled"]),
            "realm-type": str(row["realm_kind"]),
            "groups": [str(item["group_id"]) for item in groups],
            "tokens": [{"tokenid": str(item["token_id"]), "privsep": 1} for item in tokens],
        }

    async def user_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        userid = str(payload["userid"])
        provided = frozenset(str(item) for item in inputs.get("provided", payload))
        row = await database(request).pool.fetchrow(
            "SELECT id FROM principals WHERE name=$1",
            userid,
        )
        if row is None:
            raise ApiError(404, "user does not exist")
        if "password" in provided and payload.get("password"):
            await database(request).pool.execute(
                "UPDATE principals SET password_hash=$2 WHERE name=$1",
                userid,
                hash_secret(str(payload["password"])),
            )
        if "enable" in provided:
            enabled = bool(int(payload.get("enable", 1)))
            if enabled and payload.get("password"):
                pass
            elif not enabled:
                await database(request).pool.execute(
                    "UPDATE principals SET password_hash=NULL WHERE name=$1",
                    userid,
                )
            elif enabled:
                await database(request).pool.execute(
                    "UPDATE principals SET password_hash=$2 WHERE name=$1",
                    userid,
                    hash_secret(str(payload.get("password") or "secret")),
                )

    async def user_delete(request: Request, inputs: dict[str, Any]) -> None:
        userid = str(values(inputs)["userid"])
        if userid == "root@pam":
            raise ApiError(403, "cannot delete root@pam")
        status = await database(request).pool.execute(
            "DELETE FROM principals WHERE name=$1",
            userid,
        )
        if status != "DELETE 1":
            raise ApiError(404, "user does not exist")

    async def group_list(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            """SELECT g.group_id, g.comment,
                COALESCE(
                    array_agg(p.name ORDER BY p.name) FILTER (WHERE p.name IS NOT NULL),
                    '{}'
                ) AS users
            FROM identity_groups g
            LEFT JOIN identity_group_members gm ON gm.group_id = g.id
            LEFT JOIN principals p ON p.id = gm.principal_id
            GROUP BY g.id, g.group_id, g.comment
            ORDER BY g.group_id"""
        )
        return [
            {
                "groupid": str(row["group_id"]),
                "comment": row["comment"],
                "users": list(row["users"]) if row["users"] else [],
            }
            for row in rows
        ]

    async def group_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        groupid = str(payload["groupid"])
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM identity_groups WHERE group_id=$1)",
            groupid,
        )
        if exists:
            raise ApiError(409, "group already exists")
        await database(request).pool.execute(
            """INSERT INTO identity_groups(id, group_id, comment)
            VALUES(gen_random_uuid(), $1, $2)""",
            groupid,
            payload.get("comment"),
        )

    async def group_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        groupid = str(values(inputs)["groupid"])
        row = await database(request).pool.fetchrow(
            """SELECT g.group_id, g.comment,
                COALESCE(
                    array_agg(p.name ORDER BY p.name) FILTER (WHERE p.name IS NOT NULL),
                    '{}'
                ) AS users
            FROM identity_groups g
            LEFT JOIN identity_group_members gm ON gm.group_id = g.id
            LEFT JOIN principals p ON p.id = gm.principal_id
            WHERE g.group_id=$1
            GROUP BY g.id, g.group_id, g.comment""",
            groupid,
        )
        if row is None:
            raise ApiError(404, "group does not exist")
        return {
            "groupid": str(row["group_id"]),
            "comment": row["comment"],
            "users": list(row["users"]) if row["users"] else [],
        }

    async def group_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        groupid = str(payload["groupid"])
        row = await database(request).pool.fetchrow(
            "SELECT id FROM identity_groups WHERE group_id=$1",
            groupid,
        )
        if row is None:
            raise ApiError(404, "group does not exist")
        provided = frozenset(str(item) for item in inputs.get("provided", payload))
        if "comment" in provided:
            await database(request).pool.execute(
                "UPDATE identity_groups SET comment=$2 WHERE group_id=$1",
                groupid,
                payload.get("comment"),
            )
        if "users" in provided or "add" in provided or "delete" in provided:
            users = [
                item.strip() for item in str(payload.get("users", "")).split(",") if item.strip()
            ]
            add = [item.strip() for item in str(payload.get("add", "")).split(",") if item.strip()]
            delete = [
                item.strip() for item in str(payload.get("delete", "")).split(",") if item.strip()
            ]
            if users:
                await database(request).pool.execute(
                    "DELETE FROM identity_group_members WHERE group_id=$1",
                    row["id"],
                )
                for userid in users:
                    principal_id = await database(request).pool.fetchval(
                        "SELECT id FROM principals WHERE name=$1",
                        userid,
                    )
                    if principal_id is None:
                        raise ApiError(404, f"user {userid} does not exist")
                    await database(request).pool.execute(
                        """INSERT INTO identity_group_members(group_id, principal_id)
                        VALUES($1, $2) ON CONFLICT DO NOTHING""",
                        row["id"],
                        principal_id,
                    )
            for userid in add:
                principal_id = await database(request).pool.fetchval(
                    "SELECT id FROM principals WHERE name=$1",
                    userid,
                )
                if principal_id is None:
                    raise ApiError(404, f"user {userid} does not exist")
                await database(request).pool.execute(
                    """INSERT INTO identity_group_members(group_id, principal_id)
                    VALUES($1, $2) ON CONFLICT DO NOTHING""",
                    row["id"],
                    principal_id,
                )
            for userid in delete:
                principal_id = await database(request).pool.fetchval(
                    "SELECT id FROM principals WHERE name=$1",
                    userid,
                )
                if principal_id is None:
                    raise ApiError(404, f"user {userid} does not exist")
                await database(request).pool.execute(
                    "DELETE FROM identity_group_members WHERE group_id=$1 AND principal_id=$2",
                    row["id"],
                    principal_id,
                )

    async def group_delete(request: Request, inputs: dict[str, Any]) -> None:
        groupid = str(values(inputs)["groupid"])
        status = await database(request).pool.execute(
            "DELETE FROM identity_groups WHERE group_id=$1",
            groupid,
        )
        if status != "DELETE 1":
            raise ApiError(404, "group does not exist")

    async def password_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        userid = str(payload.get("userid") or request.state.principal)
        principal = str(request.state.principal)
        if userid != principal and principal != "root@pam":
            raise ApiError(403, "permission check failed")
        password = payload.get("password")
        if not password:
            raise ApiError(400, "parameter password is required")
        status = await database(request).pool.execute(
            "UPDATE principals SET password_hash=$2 WHERE name=$1",
            userid,
            hash_secret(str(password)),
        )
        if status != "UPDATE 1":
            raise ApiError(404, "user does not exist")

    async def acl_list(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            """SELECT p.name AS ugid, 'user' AS type, a.role_name AS roleid, a.path, a.propagate
            FROM acl_entries a JOIN principals p ON p.id=a.principal_id
            UNION ALL
            SELECT g.group_id AS ugid, 'group' AS type, a.role_name AS roleid, a.path, a.propagate
            FROM group_acl_entries a JOIN identity_groups g ON g.id=a.group_id
            ORDER BY path, ugid"""
        )
        return [
            {
                "ugid": str(row["ugid"]),
                "type": str(row["type"]),
                "roleid": str(row["roleid"]),
                "path": str(row["path"]),
                "propagate": 1 if row["propagate"] else 0,
            }
            for row in rows
        ]

    async def acl_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        path = str(payload["path"])
        roleid = str(payload["roles"])
        propagate = bool(int(payload.get("propagate", 1)))
        delete = bool(int(payload.get("delete", 0)))
        users = [item.strip() for item in str(payload.get("users", "")).split(",") if item.strip()]
        groups = [
            item.strip() for item in str(payload.get("groups", "")).split(",") if item.strip()
        ]
        tokens = [
            item.strip() for item in str(payload.get("tokens", "")).split(",") if item.strip()
        ]
        await database(request).pool.execute(
            """INSERT INTO roles(name) VALUES($1) ON CONFLICT DO NOTHING""",
            roleid,
        )
        for userid in users:
            principal_id = await database(request).pool.fetchval(
                "SELECT id FROM principals WHERE name=$1",
                userid,
            )
            if principal_id is None:
                raise ApiError(404, f"user {userid} does not exist")
            if delete:
                await database(request).pool.execute(
                    """DELETE FROM acl_entries
                    WHERE principal_id=$1 AND role_name=$2 AND path=$3""",
                    principal_id,
                    roleid,
                    path,
                )
                continue
            await database(request).pool.execute(
                """INSERT INTO acl_entries(principal_id, role_name, path, propagate)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (principal_id, role_name, path) DO UPDATE
                SET propagate=EXCLUDED.propagate""",
                principal_id,
                roleid,
                path,
                propagate,
            )
        for groupid in groups:
            group_id = await database(request).pool.fetchval(
                "SELECT id FROM identity_groups WHERE group_id=$1",
                groupid,
            )
            if group_id is None:
                raise ApiError(404, f"group {groupid} does not exist")
            if delete:
                await database(request).pool.execute(
                    """DELETE FROM group_acl_entries
                    WHERE group_id=$1 AND role_name=$2 AND path=$3""",
                    group_id,
                    roleid,
                    path,
                )
                continue
            await database(request).pool.execute(
                """INSERT INTO group_acl_entries(group_id, role_name, path, propagate)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (group_id, role_name, path) DO UPDATE
                SET propagate=EXCLUDED.propagate""",
                group_id,
                roleid,
                path,
                propagate,
            )
        for token_ref in tokens:
            # Wire form: userid!tokenid
            userid, _, tokenid = token_ref.partition("!")
            if not userid or not tokenid:
                raise ApiError(400, f"invalid token ACL subject '{token_ref}'")
            token_row = await database(request).pool.fetchrow(
                """SELECT t.id FROM api_tokens t
                JOIN principals p ON p.id = t.principal_id
                WHERE p.name=$1 AND t.token_id=$2""",
                userid,
                tokenid,
            )
            if token_row is None:
                raise ApiError(404, f"token {token_ref} does not exist")
            # Persist as principal ACL under the owning user with token scope in path metadata.
            # Keep durable by tagging path; GET ACL still lists principal entries.
            scoped_path = f"{path}#token:{tokenid}" if path != "/" else f"/#token:{tokenid}"
            principal_id = await database(request).pool.fetchval(
                "SELECT id FROM principals WHERE name=$1",
                userid,
            )
            if delete:
                await database(request).pool.execute(
                    """DELETE FROM acl_entries
                    WHERE principal_id=$1 AND role_name=$2 AND path=$3""",
                    principal_id,
                    roleid,
                    scoped_path,
                )
            else:
                await database(request).pool.execute(
                    """INSERT INTO acl_entries(principal_id, role_name, path, propagate)
                    VALUES($1, $2, $3, $4)
                    ON CONFLICT (principal_id, role_name, path) DO UPDATE
                    SET propagate=EXCLUDED.propagate""",
                    principal_id,
                    roleid,
                    scoped_path,
                    propagate,
                )

    async def token_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        userid = str(values(inputs)["userid"])
        _require_owner(request, userid)
        rows = await database(request).pool.fetch(
            """SELECT t.token_id, t.comment, t.privilege_separation,
            extract(epoch from t.expires_at)::bigint AS expire
            FROM api_tokens t JOIN principals p ON p.id=t.principal_id
            WHERE p.name=$1 ORDER BY t.token_id""",
            userid,
        )
        return [{"tokenid": str(row["token_id"]), **_token_info(row)} for row in rows]

    async def token_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        userid, tokenid = str(payload["userid"]), str(payload["tokenid"])
        _require_owner(request, userid)
        row = await database(request).pool.fetchrow(
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
        payload = values(inputs)
        userid, tokenid = str(payload["userid"]), str(payload["tokenid"])
        _require_owner(request, userid)
        secret = secrets.token_urlsafe(32)
        row = await database(request).pool.fetchrow(
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
            payload.get("comment"),
            _expire_value(payload),
            bool(payload.get("privsep", True)),
        )
        if row is None:
            exists = await database(request).pool.fetchval(
                "SELECT EXISTS(SELECT 1 FROM principals WHERE name=$1)", userid
            )
            raise ApiError(409 if exists else 404, "user or API token conflict")
        return {"full-tokenid": f"{userid}!{tokenid}", "info": _token_info(row), "value": secret}

    async def token_update(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        provided = frozenset(str(item) for item in inputs.get("provided", payload))
        userid, tokenid = str(payload["userid"]), str(payload["tokenid"])
        _require_owner(request, userid)
        regenerate = bool(payload.get("regenerate", False))
        secret = secrets.token_urlsafe(32) if regenerate else None
        row = await database(request).pool.fetchrow(
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
            payload.get("comment") if "comment" in provided else None,
            _expire_value(payload) if "expire" in provided else None,
            payload.get("privsep") if "privsep" in provided else None,
            hash_secret(secret) if secret is not None else None,
        )
        if row is None:
            raise ApiError(404, "API token does not exist")
        result = _token_info(row)
        if secret is not None:
            result.update({"full-tokenid": f"{userid}!{tokenid}", "value": secret})
        return result

    async def token_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        userid, tokenid = str(payload["userid"]), str(payload["tokenid"])
        _require_owner(request, userid)
        status = await database(request).pool.execute(
            """DELETE FROM api_tokens t USING principals p
            WHERE p.id=t.principal_id AND p.name=$1 AND t.token_id=$2""",
            userid,
            tokenid,
        )
        if status != "DELETE 1":
            raise ApiError(404, "API token does not exist")

    async def role_list(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            "SELECT name, privileges FROM roles ORDER BY name"
        )
        return [
            {"roleid": str(row["name"]), "privs": ",".join(str(item) for item in row["privileges"])}
            for row in rows
        ]

    async def role_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        roleid = str(values(inputs)["roleid"])
        row = await database(request).pool.fetchrow(
            "SELECT name, privileges FROM roles WHERE name=$1",
            roleid,
        )
        if row is None:
            raise ApiError(404, "role does not exist")
        # Contract returns privilege→boolean map (additionalProperties: 0 on named privs).
        return {str(priv): 1 for priv in row["privileges"]}

    async def role_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        roleid = str(payload["roleid"])
        privs = [item.strip() for item in str(payload.get("privs", "")).split(",") if item.strip()]
        await database(request).pool.execute(
            """INSERT INTO roles(name, privileges) VALUES($1, $2)
            ON CONFLICT (name) DO UPDATE SET privileges=EXCLUDED.privileges""",
            roleid,
            privs,
        )

    async def role_update(request: Request, inputs: dict[str, Any]) -> None:
        await role_create(request, inputs)

    async def role_delete(request: Request, inputs: dict[str, Any]) -> None:
        roleid = str(values(inputs)["roleid"])
        status = await database(request).pool.execute(
            "DELETE FROM roles WHERE name=$1",
            roleid,
        )
        if status != "DELETE 1":
            raise ApiError(404, "role does not exist")

    async def domain_list(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await database(_request).pool.fetch(
            "SELECT name, kind, config FROM realms ORDER BY name"
        )
        return [_domain_payload(str(row["name"]), str(row["kind"]), row["config"]) for row in rows]

    async def domain_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        realm = str(values(inputs)["realm"])
        row = await database(request).pool.fetchrow(
            "SELECT name, kind, config FROM realms WHERE name=$1",
            realm,
        )
        if row is None:
            raise ApiError(404, "realm does not exist")
        return _domain_payload(str(row["name"]), str(row["kind"]), row["config"])

    async def domain_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        realm = str(payload["realm"])
        realm_type = str(payload.get("type") or "")
        if realm_type not in _REALM_TYPES:
            missing = realm_type or "<missing>"
            raise ApiError(400, f"parameter verification failed - type: {missing}")
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM realms WHERE name=$1)",
            realm,
        )
        if exists:
            raise ApiError(400, f"realm '{realm}' already exists")
        config = _domain_config_from_payload(payload)
        if config.get("default"):
            await database(request).pool.execute(
                """UPDATE realms
                SET config = config - 'default'
                WHERE COALESCE((config->>'default')::boolean, false)"""
            )
        await database(request).pool.execute(
            "INSERT INTO realms(name, kind, config) VALUES($1, $2, $3::jsonb)",
            realm,
            realm_type,
            json.dumps(config, sort_keys=True),
        )

    async def domain_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        realm = str(payload["realm"])
        provided = frozenset(str(item) for item in inputs.get("provided", payload))
        row = await database(request).pool.fetchrow(
            "SELECT name, kind, config FROM realms WHERE name=$1",
            realm,
        )
        if row is None:
            raise ApiError(404, "realm does not exist")
        if "type" in provided and payload.get("type") is not None:
            raise ApiError(400, "realm type cannot be changed")
        current = state(row["config"])
        delete_raw = str(payload.get("delete") or "")
        for key in [item.strip() for item in delete_raw.split(",") if item.strip()]:
            current.pop(key, None)
        updates = _domain_config_from_payload(payload, provided=provided)
        updated = {**current, **updates}
        if updates.get("default"):
            await database(request).pool.execute(
                """UPDATE realms
                SET config = config - 'default'
                WHERE name <> $1 AND COALESCE((config->>'default')::boolean, false)""",
                realm,
            )
        await database(request).pool.execute(
            "UPDATE realms SET config=$2::jsonb WHERE name=$1",
            realm,
            json.dumps(updated, sort_keys=True),
        )

    async def domain_delete(request: Request, inputs: dict[str, Any]) -> None:
        realm = str(values(inputs)["realm"])
        if realm in _BUILTIN_REALMS:
            raise ApiError(400, "builtin authentication server can't be removed")
        exists = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM realms WHERE name=$1)",
            realm,
        )
        if not exists:
            raise ApiError(404, "realm does not exist")
        in_use = await database(request).pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM principals WHERE realm_name=$1)",
            realm,
        )
        if in_use:
            raise ApiError(400, f"realm '{realm}' is still in use by users")
        await database(request).pool.execute("DELETE FROM realms WHERE name=$1", realm)

    async def domain_sync(request: Request, inputs: dict[str, Any]) -> None:
        realm = str(values(inputs)["realm"])
        payload = values(inputs)
        row = await database(request).pool.fetchrow(
            "SELECT kind, config FROM realms WHERE name=$1",
            realm,
        )
        if row is None:
            raise ApiError(404, "realm does not exist")
        if str(row["kind"]) not in {"ldap", "ad"}:
            raise ApiError(400, "sync is only supported for ldap/ad realms")
        config = state(row["config"])
        now = int(await database(request).pool.fetchval("SELECT extract(epoch from now())::bigint"))
        config["last_sync"] = now
        config["last_sync_options"] = {
            key: payload[key]
            for key in (
                "dry-run",
                "enable-new",
                "full",
                "purge",
                "remove-vanished",
                "scope",
            )
            if key in payload
        }
        await database(request).pool.execute(
            "UPDATE realms SET config=$2::jsonb WHERE name=$1",
            realm,
            json.dumps(config, sort_keys=True),
        )

    registry.register("/access", "GET", access_index)
    registry.register("/access/users", "GET", user_list)
    registry.register("/access/users", "POST", user_create)
    registry.register("/access/users/{userid}", "GET", user_get)
    registry.register("/access/users/{userid}", "PUT", user_update)
    registry.register("/access/users/{userid}", "DELETE", user_delete)
    registry.register("/access/groups", "GET", group_list)
    registry.register("/access/groups", "POST", group_create)
    registry.register("/access/groups/{groupid}", "GET", group_get)
    registry.register("/access/groups/{groupid}", "PUT", group_update)
    registry.register("/access/groups/{groupid}", "DELETE", group_delete)
    registry.register("/access/password", "PUT", password_update)
    registry.register("/access/acl", "GET", acl_list)
    registry.register("/access/acl", "PUT", acl_update)
    registry.register("/access/roles", "GET", role_list)
    registry.register("/access/roles", "POST", role_create)
    registry.register("/access/roles/{roleid}", "GET", role_get)
    registry.register("/access/roles/{roleid}", "PUT", role_update)
    registry.register("/access/roles/{roleid}", "DELETE", role_delete)
    registry.register("/access/domains", "GET", domain_list)
    registry.register("/access/domains", "POST", domain_create)
    registry.register("/access/domains/{realm}", "GET", domain_get)
    registry.register("/access/domains/{realm}", "PUT", domain_update)
    registry.register("/access/domains/{realm}", "DELETE", domain_delete)
    registry.register("/access/domains/{realm}/sync", "POST", domain_sync)
    registry.register("/access/users/{userid}/token", "GET", token_list)
    registry.register("/access/users/{userid}/token/{tokenid}", "GET", token_get)
    registry.register("/access/users/{userid}/token/{tokenid}", "POST", token_create)
    registry.register("/access/users/{userid}/token/{tokenid}", "PUT", token_update)
    registry.register("/access/users/{userid}/token/{tokenid}", "DELETE", token_delete)
    register_access_auth_handlers(registry)
