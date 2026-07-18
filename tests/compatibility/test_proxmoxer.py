"""Unmodified proxmoxer HTTPS smoke flow."""

import os
from threading import Event
from typing import Any, cast

import pytest
from proxmoxer import ProxmoxAPI, ResourceException  # type: ignore[import-untyped]

pytestmark = [
    pytest.mark.compatibility,
    pytest.mark.skipif(not os.getenv("PROXMOXER_HOST"), reason="running TLS simulator required"),
]


def wait_task(proxmox: Any, upid: str) -> dict[str, object]:
    for _attempt in range(100):
        task = proxmox.nodes("pve1").tasks(upid).status.get()
        if task["status"] == "stopped":
            return cast(dict[str, object], task)
        Event().wait(0.05)
    raise AssertionError("task did not finish")


def test_proxmoxer_read_and_qemu_task_flow() -> None:
    proxmox = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8006")),
        user="root@pam",
        password=os.getenv("PROXMOXER_PASSWORD", "secret"),
        verify_ssl=False,
    )

    assert proxmox.version.get()["version"] == "9.2.3"
    assert any(node["node"] == "pve1" for node in proxmox.nodes.get())
    assert any(vm["vmid"] == 100 for vm in proxmox.nodes("pve1").qemu.get())

    token_api = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8006")),
        user="root@pam",
        token_name=os.getenv("PROXMOXER_TOKEN_NAME", "automation"),
        token_value=os.getenv("PROXMOXER_TOKEN_SECRET", "automation-secret"),
        verify_ssl=False,
    )
    assert any(node["node"] == "pve1" for node in token_api.nodes.get())

    readonly_api = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8006")),
        user="auditor@pve",
        token_name=os.getenv("PROXMOXER_READONLY_TOKEN_NAME", "readonly"),
        token_value=os.getenv("PROXMOXER_READONLY_TOKEN_SECRET", "readonly-secret"),
        verify_ssl=False,
    )
    assert readonly_api.nodes.get()
    assert readonly_api.nodes("pve1").status.get()["status"] == "online"
    assert readonly_api.nodes("pve1").qemu("100").config.get()["vmid"] == 100
    with pytest.raises(ResourceException) as denied:
        readonly_api.nodes("pve1").qemu("100").status.start.post()
    assert denied.value.status_code == 403

    token_endpoint = proxmox.access.users("root@pam").token("ephemeral")
    created = token_endpoint.post(comment="compatibility lifecycle", privsep=0)
    assert created["full-tokenid"] == "root@pam!ephemeral"
    ephemeral = ProxmoxAPI(
        os.environ["PROXMOXER_HOST"],
        port=int(os.getenv("PROXMOXER_PORT", "8006")),
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
        port=int(os.getenv("PROXMOXER_PORT", "8006")),
        user="storage@pve",
        token_name=os.getenv("PROXMOXER_STORAGE_TOKEN_NAME", "storage"),
        token_value=os.getenv("PROXMOXER_STORAGE_TOKEN_SECRET", "storage-secret"),
        verify_ssl=False,
    )
    for vmid in ("100", "999999"):
        with pytest.raises(ResourceException) as hidden:
            storage_api.nodes("pve1").qemu(vmid).config.get()
        assert hidden.value.status_code == 403

    create_upid = proxmox.nodes("pve1").qemu.post(
        vmid=150,
        name="created-by-proxmoxer",
        cores=2,
        memory=1024,
        agent=1,
        scsi0="local-pve1:vm-150-disk-0,size=8G",
    )
    with pytest.raises(ResourceException) as duplicate_create:
        proxmox.nodes("pve1").qemu.post(vmid=150, name="duplicate")
    assert duplicate_create.value.status_code == 409
    assert wait_task(proxmox, create_upid)["exitstatus"] == "OK"
    created_config = proxmox.nodes("pve1").qemu("150").config.get()
    assert created_config["name"] == "created-by-proxmoxer"
    assert created_config["cores"] == 2

    assert proxmox.nodes("pve1").qemu("150").config.put(name="sync-update", cores=3) is None
    assert proxmox.nodes("pve1").qemu("150").config.get()["name"] == "sync-update"
    update_upid = proxmox.nodes("pve1").qemu("150").config.post(name="async-update", memory=2048)
    assert wait_task(proxmox, update_upid)["exitstatus"] == "OK"
    assert proxmox.nodes("pve1").qemu("150").config.get()["name"] == "async-update"

    disk_api = proxmox.nodes("pve1").qemu("150")
    assert disk_api.resize.put(disk="scsi0", size="+2G") is None
    assert "size=10G" in disk_api.config.get()["scsi0"]
    move_upid = disk_api.move_disk.post(disk="scsi0", storage="shared")
    assert wait_task(proxmox, move_upid)["exitstatus"] == "OK"
    assert disk_api.config.get()["scsi0"].startswith("shared:")
    assert disk_api.pending.get() == []
    assert wait_task(proxmox, disk_api.status.start.post())["exitstatus"] == "OK"
    assert disk_api.agent.ping.post()["result"] == {}
    assert disk_api.agent.info.get()["result"]["version"] == "9.2.0-simulator"
    assert disk_api.agent("get-osinfo").get()["result"]["machine"] == "x86_64"
    assert disk_api.agent("get-host-name").get()["result"]["host-name"] == "async-update"
    assert disk_api.agent("network-get-interfaces").get()["result"][0]["name"] == "eth0"
    assert disk_api.agent("get-time").get()["result"]["seconds"] > 0
    assert wait_task(proxmox, disk_api.status.stop.post())["exitstatus"] == "OK"

    snapshots = proxmox.nodes("pve1").qemu("150").snapshot
    snapshot_upid = snapshots.post(snapname="baseline", description="before change")
    assert wait_task(proxmox, snapshot_upid)["exitstatus"] == "OK"
    assert any(item["name"] == "baseline" for item in snapshots.get())
    baseline = snapshots("baseline")
    assert baseline.get()["description"] == "before change"
    assert baseline.config.put(description="stable baseline") is None
    assert baseline.config.get()["description"] == "stable baseline"
    assert proxmox.nodes("pve1").qemu("150").config.put(name="after-snapshot") is None
    rollback_upid = baseline.rollback.post()
    assert wait_task(proxmox, rollback_upid)["exitstatus"] == "OK"
    assert proxmox.nodes("pve1").qemu("150").config.get()["name"] == "async-update"
    snapshot_delete_upid = baseline.delete()
    assert wait_task(proxmox, snapshot_delete_upid)["exitstatus"] == "OK"
    assert not snapshots.get()

    clone_upid = (
        proxmox.nodes("pve1").qemu("150").clone.post(newid=151, name="clone-by-proxmoxer", full=1)
    )
    assert wait_task(proxmox, clone_upid)["exitstatus"] == "OK"
    assert proxmox.nodes("pve1").qemu("151").config.get()["name"] == "clone-by-proxmoxer"
    migration = proxmox.nodes("pve1").qemu("151").migrate
    assert migration.get(target="pve2")["local_disks"] == []
    migrate_upid = migration.post(target="pve2", online=0)
    assert wait_task(proxmox, migrate_upid)["exitstatus"] == "OK"
    assert proxmox.nodes("pve2").qemu("151").config.get()["name"] == "clone-by-proxmoxer"
    clone_delete_upid = proxmox.nodes("pve2").qemu("151").delete()
    assert wait_task(proxmox, clone_delete_upid)["exitstatus"] == "OK"

    delete_upid = proxmox.nodes("pve1").qemu("150").delete()
    assert wait_task(proxmox, delete_upid)["exitstatus"] == "OK"
    with pytest.raises(ResourceException) as deleted_vm:
        proxmox.nodes("pve1").qemu("150").config.get()
    assert deleted_vm.value.status_code == 404

    if os.getenv("PROXMOXER_MUTATION_TEST") == "1":
        operator_api = ProxmoxAPI(
            os.environ["PROXMOXER_HOST"],
            port=int(os.getenv("PROXMOXER_PORT", "8006")),
            user="operator@pve",
            token_name=os.getenv("PROXMOXER_OPERATOR_TOKEN_NAME", "operator"),
            token_value=os.getenv("PROXMOXER_OPERATOR_TOKEN_SECRET", "operator-secret"),
            verify_ssl=False,
        )
        status_resource = operator_api.nodes("pve1").qemu("100").status

        def run(operation: str, expected: str) -> None:
            upid = status_resource(operation).post()
            assert wait_task(operator_api, upid)["exitstatus"] == "OK"
            assert status_resource.current.get()["status"] == expected

        if status_resource.current.get()["status"] == "stopped":
            run("start", "running")
        run("reboot", "running")
        run("reset", "running")
        run("suspend", "paused")
        run("resume", "running")
        run("shutdown", "stopped")
        run("start", "running")
        run("stop", "stopped")
