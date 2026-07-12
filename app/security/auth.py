"""Password, ticket, CSRF, and API-token primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass

from starlette.responses import Response


class AuthenticationError(ValueError):
    pass


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_secret(secret: str, *, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(secret.encode(), salt=actual_salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64(actual_salt)}${_b64(digest)}"


def verify_secret(secret: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            secret.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True, slots=True)
class TicketClaims:
    principal: str
    issued_at: int
    expires_at: int
    nonce: str


def issue_ticket(principal: str, key: bytes, *, now: int | None = None, ttl: int = 7200) -> str:
    issued = int(time.time() if now is None else now)
    claims = {
        "exp": issued + ttl,
        "iat": issued,
        "nonce": _b64(secrets.token_bytes(12)),
        "principal": principal,
    }
    payload = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    signature = _b64(hmac.digest(key, payload.encode(), "sha256"))
    return f"PVE:{payload}.{signature}"


def verify_ticket(ticket: str, key: bytes, *, now: int | None = None) -> TicketClaims:
    try:
        prefix, signed = ticket.split(":", 1)
        payload, signature = signed.split(".", 1)
        if prefix != "PVE" or not hmac.compare_digest(
            _unb64(signature), hmac.digest(key, payload.encode(), "sha256")
        ):
            raise AuthenticationError("invalid ticket")
        data = json.loads(_unb64(payload))
        claims = TicketClaims(
            principal=str(data["principal"]),
            issued_at=int(data["iat"]),
            expires_at=int(data["exp"]),
            nonce=str(data["nonce"]),
        )
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        raise AuthenticationError("invalid ticket") from error
    current = int(time.time() if now is None else now)
    if claims.expires_at < current or claims.issued_at > current + 60:
        raise AuthenticationError("ticket expired or not yet valid")
    return claims


def csrf_token(ticket: str, key: bytes) -> str:
    return _b64(hmac.digest(key, b"csrf:" + ticket.encode(), "sha256"))


def verify_csrf(ticket: str, token: str, key: bytes) -> bool:
    return hmac.compare_digest(csrf_token(ticket, key), token)


def set_ticket_cookie(response: Response, ticket: str, *, secure: bool = True) -> None:
    response.set_cookie(
        "PVEAuthCookie",
        ticket,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


@dataclass(frozen=True, slots=True)
class ApiToken:
    principal: str
    token_id: str
    secret: str


TOKEN_PATTERN = re.compile(r"^PVEAPIToken=([^!=\s]+![^=\s]+)=([^\s]+)$")


def parse_api_token(header: str) -> ApiToken:
    match = TOKEN_PATTERN.fullmatch(header)
    if match is None:
        raise AuthenticationError("invalid API token")
    identity, secret = match.groups()
    principal, token_id = identity.rsplit("!", 1)
    return ApiToken(principal, token_id, secret)


SECRET_RE = re.compile(r"(PVEAPIToken=[^=\s]+=)[^\s]+|(password|secret|token)=([^&\s]+)", re.I)


def redact_secrets(value: str) -> str:
    return SECRET_RE.sub(
        lambda match: (match.group(1) or f"{match.group(2)}=") + "[REDACTED]", value
    )
