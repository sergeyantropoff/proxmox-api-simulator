"""Unmodified proxmoxer HTTPS smoke flow."""

import os
from threading import Event

import pytest
from proxmoxer import ProxmoxAPI, ResourceException  # type: ignore[import-untyped]

pytestmark = [
    pytest.mark.compatibility,
    pytest.mark.skipif(not os.getenv("PROXMOXER_HOST"), reason="running TLS simulator required"),
]


def test_proxmoxer_read_and_qemu_task_flow() -> None:
    proxmox = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8007")),
        user="root@pam",
        password=os.getenv("PROXMOXER_PASSWORD", "secret"),
        verify_ssl=False,
    )

    assert proxmox.version.get()["version"] == "9.2.3"
    assert any(node["node"] == "pve1" for node in proxmox.nodes.get())
    assert any(vm["vmid"] == 101 for vm in proxmox.nodes("pve1").qemu.get())

    token_api = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8007")),
        user="root@pam",
        token_name=os.getenv("PROXMOXER_TOKEN_NAME", "automation"),
        token_value=os.getenv("PROXMOXER_TOKEN_SECRET", "automation-secret"),
        verify_ssl=False,
    )
    assert any(node["node"] == "pve1" for node in token_api.nodes.get())

    readonly_api = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8007")),
        user="auditor@pve",
        token_name=os.getenv("PROXMOXER_READONLY_TOKEN_NAME", "readonly"),
        token_value=os.getenv("PROXMOXER_READONLY_TOKEN_SECRET", "readonly-secret"),
        verify_ssl=False,
    )
    assert readonly_api.nodes.get()
    assert readonly_api.nodes("pve1").status.get()["status"] == "online"
    assert readonly_api.nodes("pve1").qemu("101").config.get()["vmid"] == 101
    with pytest.raises(ResourceException) as denied:
        readonly_api.nodes("pve1").qemu("101").status.start.post()
    assert denied.value.status_code == 403

    token_endpoint = proxmox.access.users("root@pam").token("ephemeral")
    created = token_endpoint.post(comment="compatibility lifecycle", privsep=0)
    assert created["full-tokenid"] == "root@pam!ephemeral"
    ephemeral = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8007")),
        user="root@pam",
        token_name=os.getenv("PROXMOXER_EPHEMERAL_TOKEN_NAME", "ephemeral"),
        token_value=created["value"],
        verify_ssl=False,
    )
    assert ephemeral.nodes.get()
    updated = token_endpoint.put(comment="updated", privsep=0)
    assert updated["comment"] == "updated"
    assert token_endpoint.get()["comment"] == "updated"
    token_endpoint.delete()
    with pytest.raises(ResourceException) as removed:
        ephemeral.nodes.get()
    assert removed.value.status_code == 401

    storage_api = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8007")),
        user="storage@pve",
        token_name=os.getenv("PROXMOXER_STORAGE_TOKEN_NAME", "storage"),
        token_value=os.getenv("PROXMOXER_STORAGE_TOKEN_SECRET", "storage-secret"),
        verify_ssl=False,
    )
    for vmid in ("101", "999999"):
        with pytest.raises(ResourceException) as hidden:
            storage_api.nodes("pve1").qemu(vmid).config.get()
        assert hidden.value.status_code == 403

    if os.getenv("PROXMOXER_MUTATION_TEST") == "1":
        operator_api = ProxmoxAPI(
            os.environ["PROXMOXER_HOST"],
            port=int(os.getenv("PROXMOXER_PORT", "8007")),
            user="operator@pve",
            token_name=os.getenv("PROXMOXER_OPERATOR_TOKEN_NAME", "operator"),
            token_value=os.getenv("PROXMOXER_OPERATOR_TOKEN_SECRET", "operator-secret"),
            verify_ssl=False,
        )
        status = operator_api.nodes("pve1").qemu("101").status.current.get()
        operation = "start" if status["status"] == "stopped" else "stop"
        endpoint = operator_api.nodes("pve1").qemu("101").status(operation)
        upid = endpoint.post()
        for _attempt in range(100):
            task = operator_api.nodes("pve1").tasks(upid).status.get()
            if task["status"] == "stopped":
                break
            Event().wait(0.05)
        assert task["status"] == "stopped"
        assert task["exitstatus"] == "OK"
