"""Network-constrained remote contract retrieval."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.contracts.source import SourceError

Resolver = Callable[[str], Awaitable[tuple[str, ...]]]


async def resolve_host(host: str) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    results = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return tuple(sorted({str(result[4][0]) for result in results}))


def validate_remote_url(url: str, allowed_hosts: frozenset[str]) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise SourceError("remote imports require HTTPS")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise SourceError("remote URL contains forbidden authority components")
    host = (parsed.hostname or "").rstrip(".").lower()
    if host not in allowed_hosts:
        raise SourceError("remote host is not in the official-domain allowlist")
    if parsed.fragment:
        raise SourceError("remote URL fragments are not allowed")
    return host


# Fake-IP pools used by local proxies (Clash, Surge, etc.) still route to public hosts.
_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _is_allowed_resolved_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.is_global:
        return True
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    if mapped is not None and mapped in _FAKE_IP_NETWORK:
        return True
    if isinstance(address, ipaddress.IPv4Address) and address in _FAKE_IP_NETWORK:
        return True
    return False


def validate_public_addresses(addresses: tuple[str, ...]) -> None:
    if not addresses:
        raise SourceError("remote host did not resolve")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not _is_allowed_resolved_address(address):
            raise SourceError(f"remote host resolved to a non-public address: {value}")


@dataclass(frozen=True, slots=True)
class RemoteSourceImporter:
    url: str
    allowed_hosts: frozenset[str] = frozenset({"pve.proxmox.com"})
    max_bytes: int = 16 * 1024 * 1024
    max_redirects: int = 3
    retries: int = 2
    timeout_seconds: float = 20.0
    resolver: Resolver = resolve_host
    transport: httpx.AsyncBaseTransport | None = None

    async def load(self) -> bytes:
        current = self.url
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=timeout, transport=self.transport
        ) as client:
            for redirect_count in range(self.max_redirects + 1):
                host = validate_remote_url(current, self.allowed_hosts)
                validate_public_addresses(await self.resolver(host))
                response = await self._request(client, current)
                if response.is_redirect:
                    if redirect_count == self.max_redirects:
                        raise SourceError("remote import exceeded redirect limit")
                    location = response.headers.get("location")
                    if not location:
                        raise SourceError("remote redirect has no location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_bytes:
                    raise SourceError("remote artifact exceeds size limit")
                content = response.content
                if len(content) > self.max_bytes:
                    raise SourceError("remote artifact exceeds size limit")
                return content
        raise SourceError("remote import failed")

    async def _request(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        for attempt in range(self.retries + 1):
            try:
                return await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self.retries:
                    raise
                await asyncio.sleep(0.1 * (2**attempt))
        raise SourceError("remote import retry loop exhausted")
