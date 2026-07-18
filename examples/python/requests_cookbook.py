#!/usr/bin/env python3
"""Raw requests cookbook against HTTP :8006."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import requests

BASE = os.environ.get("PVE_BASE", "https://localhost:8006/api2/json")
NODE = os.environ.get("PVE_NODE", "pve01")
VMID = int(os.environ.get("PVE_VMID", "111"))
TOKEN = os.environ.get(
    "PVE_API_TOKEN",
    "root@pam!automation=automation-secret",
)


def api(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> Any:
    response = requests.request(
        method,
        f"{BASE}{path}",
        headers=headers,
        data=data,
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("data", body)


def wait_task(headers: dict[str, str], upid: str, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = api("GET", f"/nodes/{NODE}/tasks/{upid}/status", headers=headers)
        if status.get("status") == "stopped":
            return
        time.sleep(0.5)
    raise TimeoutError(upid)


def with_token() -> dict[str, str]:
    return {"Authorization": f"PVEAPIToken={TOKEN}"}


def with_ticket() -> dict[str, str]:
    data = api(
        "POST",
        "/access/ticket",
        data={
            "username": os.environ.get("PVE_USER", "root@pam"),
            "password": os.environ.get("PVE_PASSWORD", "secret"),
        },
    )
    return {
        "Cookie": f"PVEAuthCookie={data['ticket']}",
        "CSRFPreventionToken": data["CSRFPreventionToken"],
    }


def cookbook(headers: dict[str, str], label: str) -> None:
    print(label, "version:", api("GET", "/version", headers=headers))
    print(label, "qemu:", api("GET", f"/nodes/{NODE}/qemu", headers=headers))
    upid = api(
        "POST",
        f"/nodes/{NODE}/qemu",
        headers=headers,
        data={"vmid": VMID, "name": f"req-{VMID}", "cores": 1, "memory": 512},
    )
    wait_task(headers, upid)
    upid = api("POST", f"/nodes/{NODE}/qemu/{VMID}/status/start", headers=headers)
    wait_task(headers, upid)
    print(
        label, "status:", api("GET", f"/nodes/{NODE}/qemu/{VMID}/status/current", headers=headers)
    )
    upid = api("POST", f"/nodes/{NODE}/qemu/{VMID}/status/stop", headers=headers)
    wait_task(headers, upid)
    upid = api("DELETE", f"/nodes/{NODE}/qemu/{VMID}", headers=headers)
    wait_task(headers, upid)
    print(label, "ok")


def main() -> int:
    cookbook(with_token(), "token")
    # second VMID for ticket path
    global VMID
    VMID = int(os.environ.get("PVE_VMID_TICKET", "112"))
    cookbook(with_ticket(), "ticket")
    return 0


if __name__ == "__main__":
    sys.exit(main())
