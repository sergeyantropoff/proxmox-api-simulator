#!/usr/bin/env python3
"""proxmoxer cookbook against the local HTTPS gateway."""

from __future__ import annotations

import os
import sys
import time

from proxmoxer import ProxmoxAPI


def wait_task(proxmox: ProxmoxAPI, node: str, upid: str, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = proxmox.nodes(node).tasks(upid).status.get()
        if status.get("status") == "stopped":
            exitstatus = status.get("exitstatus", "")
            if exitstatus not in ("OK", "ok", None, ""):
                # Proxmox uses exitstatus "OK" on success; accept empty for lab.
                if str(exitstatus).upper() != "OK":
                    raise RuntimeError(f"task failed: {status}")
            return
        time.sleep(0.5)
    raise TimeoutError(upid)


def main() -> int:
    host = os.environ.get("PVE_HOST", "localhost")
    port = int(os.environ.get("PVE_PORT", "8007"))
    user = os.environ.get("PVE_USER", "root@pam")
    node = os.environ.get("PVE_NODE", "pve01")
    vmid = int(os.environ.get("PVE_VMID", "110"))

    token_name = os.environ.get("PVE_TOKEN_NAME")
    token_value = os.environ.get("PVE_TOKEN_VALUE")
    if token_name and token_value:
        proxmox = ProxmoxAPI(
            host,
            user=user,
            token_name=token_name,
            token_value=token_value,
            port=port,
            verify_ssl=False,
        )
    else:
        proxmox = ProxmoxAPI(
            host,
            user=user,
            password=os.environ.get("PVE_PASSWORD", "secret"),
            port=port,
            verify_ssl=False,
        )

    print("version:", proxmox.version.get())
    print("nodes:", proxmox.nodes.get())
    print("qemu:", proxmox.nodes(node).qemu.get())

    upid = proxmox.nodes(node).qemu.post(
        vmid=vmid,
        name=f"cookbook-{vmid}",
        cores=1,
        memory=512,
    )
    print("create:", upid)
    wait_task(proxmox, node, upid)

    upid = proxmox.nodes(node).qemu(vmid).status.start.post()
    print("start:", upid)
    wait_task(proxmox, node, upid)
    print("status:", proxmox.nodes(node).qemu(vmid).status.current.get())

    upid = proxmox.nodes(node).qemu(vmid).status.stop.post()
    print("stop:", upid)
    wait_task(proxmox, node, upid)

    upid = proxmox.nodes(node).qemu(vmid).delete()
    print("delete:", upid)
    wait_task(proxmox, node, upid)
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
