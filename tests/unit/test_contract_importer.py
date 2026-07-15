"""Security and idempotency tests for contract imports."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.contracts.importer import (
    RemoteSourceImporter,
    validate_public_addresses,
    validate_remote_url,
)
from app.contracts.normalize import normalize_snapshot
from app.contracts.source import ApiViewerParser, SourceError
from app.contracts.store import RevisionStore


async def public_resolver(_host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


@pytest.mark.parametrize(
    "url",
    [
        "http://pve.proxmox.com/apidoc.js",
        "https://evil.example/apidoc.js",
        "https://pve.proxmox.com.evil.example/apidoc.js",
        "https://user@pve.proxmox.com/apidoc.js",
        "https://pve.proxmox.com:444/apidoc.js",
    ],
)
def test_remote_url_policy_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(SourceError):
        validate_remote_url(url, frozenset({"pve.proxmox.com"}))


@pytest.mark.parametrize(
    "address",
    [
        "198.18.0.42",
        "::ffff:198.18.0.42",
    ],
)
def test_validate_public_addresses_allows_proxy_fake_ip(address: str) -> None:
    validate_public_addresses((address,))


async def test_remote_import_rejects_private_resolution() -> None:
    async def private_resolver(_host: str) -> tuple[str, ...]:
        return ("127.0.0.1",)

    importer = RemoteSourceImporter(
        "https://pve.proxmox.com/apidoc.js",
        resolver=private_resolver,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"[]")),
    )

    with pytest.raises(SourceError, match="non-public"):
        await importer.load()


async def test_redirect_is_revalidated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/private"})

    importer = RemoteSourceImporter(
        "https://pve.proxmox.com/apidoc.js",
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SourceError, match="allowlist"):
        await importer.load()


async def test_remote_import_enforces_size_limit() -> None:
    importer = RemoteSourceImporter(
        "https://pve.proxmox.com/apidoc.js",
        max_bytes=2,
        resolver=public_resolver,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"[]\n")),
    )

    with pytest.raises(SourceError, match="size"):
        await importer.load()


def test_revision_store_is_idempotent(tmp_path: Path) -> None:
    raw = b'[{"path":"/version","info":{}}]'
    parsed = ApiViewerParser().parse(raw)
    snapshot, manifest = normalize_snapshot(
        parsed,
        raw=raw,
        source_version="test",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store = RevisionStore(tmp_path)

    first = store.save(raw, snapshot, manifest)
    second = store.save(raw, snapshot, manifest)

    assert first == second
    assert store.list() == (manifest.snapshot_sha256,)
    assert store.manifest(manifest.snapshot_sha256) == manifest
