"""Authentication, CSRF, token, and redaction matrices."""

import pytest
from starlette.responses import Response

from app.security.auth import (
    AuthenticationError,
    csrf_token,
    hash_secret,
    issue_ticket,
    parse_api_token,
    redact_secrets,
    set_ticket_cookie,
    verify_csrf,
    verify_secret,
    verify_ticket,
)

KEY = b"test-signing-key-with-at-least-32-bytes"


def test_password_and_token_hashes_do_not_store_plaintext() -> None:
    encoded = hash_secret("correct horse", salt=b"0123456789abcdef")

    assert "correct horse" not in encoded
    assert verify_secret("correct horse", encoded)
    assert not verify_secret("wrong", encoded)
    assert not verify_secret("correct horse", "unknown$format")


def test_signed_ticket_expiry_and_csrf() -> None:
    ticket = issue_ticket("root@pam", KEY, now=100, ttl=60)

    assert verify_ticket(ticket, KEY, now=120).principal == "root@pam"
    token = csrf_token(ticket, KEY)
    assert verify_csrf(ticket, token, KEY)
    assert not verify_csrf(ticket, token + "x", KEY)
    with pytest.raises(AuthenticationError, match="expired"):
        verify_ticket(ticket, KEY, now=161)
    with pytest.raises(AuthenticationError, match="invalid"):
        verify_ticket(ticket + "x", KEY, now=120)


def test_ticket_cookie_is_http_only_and_secure() -> None:
    response = Response()
    set_ticket_cookie(response, "ticket")

    header = response.headers["set-cookie"]
    assert "PVEAuthCookie=ticket" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=strict" in header


def test_api_token_parsing_and_log_redaction() -> None:
    token = parse_api_token("PVEAPIToken=user@pve!automation=supersecret")

    assert token.principal == "user@pve"
    assert token.token_id == "automation"
    assert token.secret == "supersecret"
    redacted = redact_secrets(
        "PVEAPIToken=user@pve!automation=supersecret password=hunter2 token=abc"
    )
    assert "supersecret" not in redacted
    assert "hunter2" not in redacted
    assert "token=abc" not in redacted
    with pytest.raises(AuthenticationError):
        parse_api_token("Bearer secret")
