"""Group-level API smoke with real PostgreSQL persistence.

Exercises representative create/update/read paths per major API group so the
surface verified ledger is backed by working handlers, not only route presence.
Requires ``TEST_DATABASE_URL`` (same as other integration tests).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import asyncpg  # type: ignore[import-untyped]
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.db.migrations import migrate
from app.db.pool import AsyncpgDatabase
from app.main import create_app
from app.simulation.seed import apply_seed, lab_profile

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is required"),
]

_BUNDLED_9 = Path(
    "contracts/e61a893e996d05d376579226e7dfbedbcfce8b71787adacffbc557e6e35901c1/snapshot.json"
)
_EVIDENCE_9 = Path("evidence/pve-9.2.3.json")
_NODE = "pve01"


async def _prepare_database(url: str) -> None:
    connection = await asyncpg.connect(url)
    try:
        await migrate(connection)
        await apply_seed(connection, lab_profile())
    finally:
        await connection.close()


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/api2/json/access/ticket",
        content="username=root%40pam&password=secret",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["username"] == "root@pam"
    ticket = data["ticket"]
    client.cookies.set("PVEAuthCookie", ticket)
    return str(data["CSRFPreventionToken"])


async def _wait_task(client: AsyncClient, upid: str, *, node: str = _NODE) -> dict[str, Any]:
    for _ in range(100):
        response = await client.get(f"/api2/json/nodes/{node}/tasks/{upid}/status")
        assert response.status_code == 200, response.text
        task = cast(dict[str, Any], response.json()["data"])
        if task.get("status") == "stopped":
            return task
        await asyncio.sleep(0.05)
    raise AssertionError(f"task did not finish: {upid}")


@pytest.fixture
async def api_client() -> AsyncIterator[tuple[AsyncClient, str]]:
    url = os.environ["TEST_DATABASE_URL"]
    await _prepare_database(url)
    settings = Settings(
        database_url=SecretStr(url),
        contract_snapshot=_BUNDLED_9,
        compatibility_evidence=_EVIDENCE_9,
        ticket_signing_key=SecretStr("development-only-signing-key-change-me"),
    )

    def database_factory(resolved: Settings) -> AsyncpgDatabase:
        return AsyncpgDatabase(resolved)

    app = create_app(settings=settings, database_factory=database_factory)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            csrf = await _login(client)
            yield client, csrf


async def test_access_group_realm_and_user_persist(api_client: tuple[AsyncClient, str]) -> None:
    client, csrf = api_client
    realm = "smoke-ldap"
    create_realm = await client.post(
        "/api2/json/access/domains",
        data={
            "realm": realm,
            "type": "ldap",
            "server1": "ldap.smoke.local",
            "base_dn": "dc=smoke,dc=local",
            "comment": "group smoke realm",
        },
        headers={"CSRFPreventionToken": csrf},
    )
    assert create_realm.status_code == 200, create_realm.text

    listed = await client.get("/api2/json/access/domains")
    assert listed.status_code == 200
    names = {item["realm"] for item in listed.json()["data"]}
    assert realm in names

    detail = await client.get(f"/api2/json/access/domains/{realm}")
    assert detail.status_code == 200
    assert detail.json()["data"]["type"] == "ldap"

    user = "smoke-user@pam"
    create_user = await client.post(
        "/api2/json/access/users",
        data={"userid": user, "comment": "group smoke user", "enable": 1},
        headers={"CSRFPreventionToken": csrf},
    )
    assert create_user.status_code == 200, create_user.text
    got_user = await client.get(f"/api2/json/access/users/{user}")
    assert got_user.status_code == 200
    assert got_user.json()["data"]["userid"] == user

    delete_realm = await client.delete(
        f"/api2/json/access/domains/{realm}",
        headers={"CSRFPreventionToken": csrf},
    )
    assert delete_realm.status_code == 200, delete_realm.text


async def test_qemu_group_create_config_and_power(api_client: tuple[AsyncClient, str]) -> None:
    client, csrf = api_client
    vmid = 9101
    create = await client.post(
        f"/api2/json/nodes/{_NODE}/qemu",
        data={
            "vmid": str(vmid),
            "name": "smoke-qemu",
            "cores": "1",
            "memory": "512",
        },
        headers={"CSRFPreventionToken": csrf},
    )
    assert create.status_code == 200, create.text
    upid = create.json()["data"]
    assert isinstance(upid, str) and upid.startswith("UPID:")
    task = await _wait_task(client, upid)
    assert task.get("exitstatus") == "OK"

    config = await client.get(f"/api2/json/nodes/{_NODE}/qemu/{vmid}/config")
    assert config.status_code == 200
    assert config.json()["data"]["name"] == "smoke-qemu"

    update = await client.put(
        f"/api2/json/nodes/{_NODE}/qemu/{vmid}/config",
        data={"name": "smoke-qemu-renamed", "cores": "2"},
        headers={"CSRFPreventionToken": csrf},
    )
    assert update.status_code == 200, update.text
    config2 = await client.get(f"/api2/json/nodes/{_NODE}/qemu/{vmid}/config")
    assert config2.json()["data"]["name"] == "smoke-qemu-renamed"
    assert int(config2.json()["data"]["cores"]) == 2

    start = await client.post(
        f"/api2/json/nodes/{_NODE}/qemu/{vmid}/status/start",
        headers={"CSRFPreventionToken": csrf},
    )
    assert start.status_code == 200, start.text
    start_task = await _wait_task(client, start.json()["data"])
    assert start_task.get("exitstatus") == "OK"
    status = await client.get(f"/api2/json/nodes/{_NODE}/qemu/{vmid}/status/current")
    assert status.status_code == 200
    assert status.json()["data"]["status"] in {"running", "started"}


async def test_lxc_group_create_and_status(api_client: tuple[AsyncClient, str]) -> None:
    client, csrf = api_client
    vmid = 9201
    create = await client.post(
        f"/api2/json/nodes/{_NODE}/lxc",
        data={
            "vmid": str(vmid),
            "hostname": "smoke-lxc",
            "ostemplate": "local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst",
            "memory": "256",
            "rootfs": "local-lvm:4",
        },
        headers={"CSRFPreventionToken": csrf},
    )
    assert create.status_code == 200, create.text
    upid = create.json()["data"]
    task = await _wait_task(client, upid)
    assert task.get("exitstatus") == "OK"

    config = await client.get(f"/api2/json/nodes/{_NODE}/lxc/{vmid}/config")
    assert config.status_code == 200
    cfg = config.json()["data"]
    assert "hostname" in cfg or cfg.get("hostname") == "smoke-lxc"

    status = await client.get(f"/api2/json/nodes/{_NODE}/lxc/{vmid}/status/current")
    assert status.status_code == 200
    assert "status" in status.json()["data"]


async def test_storage_and_cluster_groups_mutate(api_client: tuple[AsyncClient, str]) -> None:
    client, csrf = api_client

    storages = await client.get("/api2/json/storage")
    if storages.status_code == 404:
        storages = await client.get(f"/api2/json/nodes/{_NODE}/storage")
    assert storages.status_code == 200, storages.text
    assert storages.json()["data"]

    content = await client.get(f"/api2/json/nodes/{_NODE}/storage/local/content")
    assert content.status_code == 200, content.text
    assert isinstance(content.json()["data"], list)

    resources = await client.get("/api2/json/cluster/resources")
    assert resources.status_code == 200
    assert resources.json()["data"]

    notify = await client.post(
        "/api2/json/cluster/notifications/endpoints/gotify",
        data={
            "name": "smoke-gotify",
            "server": "https://gotify.smoke.local",
            "token": "smoke-token",
        },
        headers={"CSRFPreventionToken": csrf},
    )
    assert notify.status_code == 200, notify.text
    got = await client.get("/api2/json/cluster/notifications/endpoints/gotify/smoke-gotify")
    assert got.status_code == 200
    assert got.json()["data"]["name"] == "smoke-gotify"
    # secret must not be echoed
    assert "token" not in got.json()["data"] or got.json()["data"].get("token") in {None, ""}


async def test_sdn_and_node_ops_groups_persist(api_client: tuple[AsyncClient, str]) -> None:
    client, csrf = api_client

    zone = await client.post(
        "/api2/json/cluster/sdn/zones",
        data={"zone": "smokecn", "type": "simple", "mtu": "1500"},
        headers={"CSRFPreventionToken": csrf},
    )
    assert zone.status_code == 200, zone.text
    zones = await client.get("/api2/json/cluster/sdn/zones")
    assert zones.status_code == 200
    names = {item.get("zone") or item.get("id") for item in zones.json()["data"]}
    assert "smokecn" in names

    network_put = await client.put(
        f"/api2/json/nodes/{_NODE}/network",
        data={},
        headers={"CSRFPreventionToken": csrf},
    )
    # Apply/reload may return null/UPID; must not be 501.
    assert network_put.status_code == 200, network_put.text

    dns = await client.get(f"/api2/json/nodes/{_NODE}/dns")
    assert dns.status_code == 200
    assert isinstance(dns.json()["data"], dict)

    dns_put = await client.put(
        f"/api2/json/nodes/{_NODE}/dns",
        data={"search": "smoke.local", "dns1": "1.1.1.1"},
        headers={"CSRFPreventionToken": csrf},
    )
    assert dns_put.status_code == 200, dns_put.text
    dns2 = await client.get(f"/api2/json/nodes/{_NODE}/dns")
    assert dns2.json()["data"].get("search") == "smoke.local" or "dns1" in dns2.json()["data"]
