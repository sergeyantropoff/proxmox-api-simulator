"""Minimal Proxmox API client for Pulumi programs and surface probes."""

from __future__ import annotations

import os
import time
import urllib.parse
from typing import Any

import httpx


class Pve:
    def __init__(self, *, authenticate: bool = True) -> None:
        root = os.environ.get("API_URL", "http://simulator:8006").rstrip("/")
        self.root = root
        self.base = root + "/api2/json"
        self.node = os.environ.get("PVE_NODE", "pve1")
        self.storage = os.environ.get("PVE_STORAGE", "local-lvm")
        self.bridge = os.environ.get("PVE_BRIDGE", "vmbr0")
        self._c = httpx.Client(base_url=self.base, timeout=120.0)
        self._h: dict[str, str] = {}
        if authenticate:
            self.login()

    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> Pve:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def login(
        self,
        username: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        r = self._c.post(
            "/access/ticket",
            data={
                "username": username or os.environ.get("API_USER", "root@pam"),
                "password": password or os.environ.get("API_PASSWORD", "secret"),
            },
        )
        r.raise_for_status()
        data = r.json()["data"]
        self._h = {
            "Cookie": f"PVEAuthCookie={data['ticket']}",
            "CSRFPreventionToken": data["CSRFPreventionToken"],
        }
        return data

    def clear_auth(self) -> None:
        self._h = {}

    def req(self, method: str, path: str, **kw: Any) -> Any:
        r = self._c.request(method, path, headers=self._h, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text}")
        return r.json().get("data")

    def wait(self, upid: str) -> None:
        enc = urllib.parse.quote(upid, safe="")
        for _ in range(600):
            st = self.req("GET", f"/nodes/{self.node}/tasks/{enc}/status")
            if st.get("status") == "stopped":
                if st.get("exitstatus") != "OK":
                    raise RuntimeError(st)
                return
            time.sleep(0.2)
        raise TimeoutError(upid)

    def create_vm(self, vmid: int, name: str) -> None:
        upid = self.req(
            "POST",
            f"/nodes/{self.node}/qemu",
            data={
                "vmid": vmid,
                "name": name,
                "cores": 1,
                "memory": 512,
                "scsi0": f"{self.storage}:vm-{vmid}-disk-0,size=8G",
                "net0": f"virtio,bridge={self.bridge}",
            },
        )
        self.wait(upid)

    def delete_vm(self, vmid: int) -> None:
        try:
            upid = self.req("POST", f"/nodes/{self.node}/qemu/{vmid}/status/stop")
            if isinstance(upid, str):
                self.wait(upid)
        except Exception:
            pass
        try:
            upid = self.req("DELETE", f"/nodes/{self.node}/qemu/{vmid}")
            if isinstance(upid, str):
                self.wait(upid)
        except Exception:
            pass

    def create_lxc(self, vmid: int, name: str) -> None:
        upid = self.req(
            "POST",
            f"/nodes/{self.node}/lxc",
            data={
                "vmid": vmid,
                "hostname": name,
                "ostemplate": "local:vztmpl/example.tar.zst",
                "rootfs": f"{self.storage}:8",
                "memory": 512,
                "cores": 1,
                "net0": f"name=eth0,bridge={self.bridge},ip=dhcp",
            },
        )
        self.wait(upid)

    def delete_lxc(self, vmid: int) -> None:
        try:
            upid = self.req("POST", f"/nodes/{self.node}/lxc/{vmid}/status/stop")
            if isinstance(upid, str):
                self.wait(upid)
        except Exception:
            pass
        try:
            upid = self.req("DELETE", f"/nodes/{self.node}/lxc/{vmid}")
            if isinstance(upid, str):
                self.wait(upid)
        except Exception:
            pass
