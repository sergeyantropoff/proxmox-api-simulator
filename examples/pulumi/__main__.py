"""Pulumi lab program: create/start/stop/delete a VM on the simulator via HTTP API.

This uses a dynamic Pulumi Resource that wraps REST calls so the cookbook works
even when a Proxmox native provider is unavailable. Prefer HTTPS gateway +
token; default here is HTTP :8006 for simpler local TLS handling.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pulumi
import requests

config = pulumi.Config()
base = config.get("base") or "http://localhost:8006/api2/json"
node = config.get("node") or "pve01"
vmid = int(config.get("vmid") or "118")
token = config.get_secret("token") or "root@pam!automation=automation-secret"
headers = {"Authorization": f"PVEAPIToken={token}"}


def api(method: str, path: str, data: dict[str, Any] | None = None) -> Any:
    response = requests.request(
        method,
        f"{base}{path}",
        headers=headers,
        data=data,
        timeout=60,
    )
    response.raise_for_status()
    return response.json().get("data")


def wait_task(upid: str) -> None:
    deadline = time.time() + 120
    while time.time() < deadline:
        status = api("GET", f"/nodes/{node}/tasks/{upid}/status")
        if status and status.get("status") == "stopped":
            return
        time.sleep(0.5)
    raise TimeoutError(upid)


class SimulatorVm(pulumi.ComponentResource):
    def __init__(self, name: str, opts: pulumi.ResourceOptions | None = None) -> None:
        super().__init__("simulator:index:Vm", name, None, opts)

        def create(_):
            version = api("GET", "/version")
            upid = api(
                "POST",
                f"/nodes/{node}/qemu",
                {
                    "vmid": vmid,
                    "name": f"pulumi-{vmid}",
                    "cores": 1,
                    "memory": 512,
                },
            )
            wait_task(upid)
            upid = api("POST", f"/nodes/{node}/qemu/{vmid}/status/start")
            wait_task(upid)
            return {
                "version": json.dumps(version),
                "vmid": str(vmid),
                "status": json.dumps(api("GET", f"/nodes/{node}/qemu/{vmid}/status/current")),
            }

        result = pulumi.Output.from_input(None).apply(create)
        self.version = result.apply(lambda d: d["version"])
        self.vmid = result.apply(lambda d: d["vmid"])
        self.status = result.apply(lambda d: d["status"])
        self.register_outputs(
            {
                "version": self.version,
                "vmid": self.vmid,
                "status": self.status,
            }
        )


vm = SimulatorVm("cookbook-vm")
pulumi.export("version", vm.version)
pulumi.export("vmid", vm.vmid)
pulumi.export("status", vm.status)
