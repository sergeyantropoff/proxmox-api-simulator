"""Lifecycle suite driven primarily by pulumi-proxmoxve (BPG bridge).

Surface probing of every contract method stays in ``run_suite.py`` (HTTP).
This program covers provider-backed inventory + VM lifecycle with non-empty
output checks. Negative auth still uses httpx against the plain HTTP API.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import pulumi
import pulumi_proxmoxve as proxmox
from pvelib.api import Pve

cfg = pulumi.Config()
smoke = (cfg.get("smoke") or os.environ.get("SMOKE_ONLY") or "0") == "1"

node = os.environ.get("PVE_NODE", "pve1")
endpoint = (
    os.environ.get("PROXMOX_VE_ENDPOINT") or "https://tls-gateway:8443/"
).rstrip("/") + "/"
username = os.environ.get("PROXMOX_VE_USERNAME") or os.environ.get("API_USER", "root@pam")
password = os.environ.get("PROXMOX_VE_PASSWORD") or os.environ.get("API_PASSWORD", "secret")
insecure = (os.environ.get("PROXMOX_VE_INSECURE") or "true").lower() in {
    "1",
    "true",
    "yes",
}


def _vmid(tag: str) -> int:
    digest = hashlib.sha1(f"hx-pve-{tag}-{os.getpid()}".encode()).hexdigest()
    return 710000 + (int(digest[:6], 16) % 90000)


def _require(value: Any, label: str) -> Any:
    if value is None:
        raise AssertionError(f"{label}: value is None")
    if isinstance(value, (str, bytes)) and not str(value).strip():
        raise AssertionError(f"{label}: empty string")
    if isinstance(value, (list, tuple, set, dict)) and len(value) == 0:
        raise AssertionError(f"{label}: empty {type(value).__name__}")
    return value


def _datastore_ids(datastores: Any) -> list[str]:
    items = getattr(datastores, "datastores", None) or datastores or []
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict):
            value = item.get("id") or item.get("datastore_id") or item.get("storage")
        else:
            value = (
                getattr(item, "id", None)
                or getattr(item, "datastore_id", None)
                or getattr(item, "storage", None)
            )
        if value not in (None, ""):
            ids.append(str(value))
    return ids


provider = proxmox.Provider(
    "proxmoxve",
    endpoint=endpoint,
    username=username,
    password=password,
    insecure=insecure,
)
prov_opts = pulumi.ResourceOptions(provider=provider)
invoke_opts = pulumi.InvokeOptions(provider=provider)

# --- Provider data sources (inventory) ---
version = proxmox.get_version_legacy(opts=invoke_opts)
identity = version.version or version.release or version.repository_id
_require(identity, "get_version_legacy identity")

nodes = proxmox.get_nodes_legacy(opts=invoke_opts)
node_names = list(_require(nodes.names, "get_nodes_legacy.names"))
if node not in node_names:
    raise AssertionError(f"expected node {node!r} in {node_names!r}")

stores = proxmox.get_datastores_legacy(node_name=node, opts=invoke_opts)
store_ids = _require(_datastore_ids(stores), "get_datastores_legacy ids")

# --- Negative auth via HTTP ---
_bad = Pve(authenticate=False)
try:
    try:
        _bad.login(password="definitely-wrong")
        raise AssertionError("expected login failure for bad password")
    except AssertionError:
        raise
    except Exception:
        pass
finally:
    _bad.close()

# --- VM via pulumi-proxmoxve (mirrors examples/terraform cookbook shape) ---
vm_id = _vmid("qemu")
vm_name = f"hxpu{vm_id}"

vm = proxmox.VmLegacy(
    "hx-vm",
    name=vm_name,
    node_name=node,
    vm_id=vm_id,
    started=False,
    on_boot=False,
    agent={"enabled": False},
    cpu={"cores": 1 if smoke else 2},
    memory={"dedicated": 512 if smoke else 1024},
    opts=prov_opts,
)


def _check_vm(args: list[Any]) -> dict[str, Any]:
    name, vmid, node_name = args
    _require(name, "VmLegacy.name")
    _require(vmid, "VmLegacy.vm_id")
    _require(node_name, "VmLegacy.node_name")
    if str(name) != vm_name:
        raise AssertionError(f"name mismatch {name!r} != {vm_name!r}")
    if int(vmid) != vm_id:
        raise AssertionError(f"vmid mismatch {vmid!r} != {vm_id!r}")
    if str(node_name) != node:
        raise AssertionError(f"node mismatch {node_name!r} != {node!r}")
    return {"name": str(name), "vm_id": int(vmid), "node": str(node_name)}


vm_checked = pulumi.Output.all(vm.name, vm.vm_id, vm.node_name).apply(_check_vm)

scenario_ids = [
    "provider_version",
    "provider_nodes",
    "provider_datastores",
    "auth_bad_password",
    "vm_lifecycle_provider",
]

pulumi.export(
    "inventory",
    {
        "version": str(identity),
        "nodes": node_names,
        "datastores": store_ids,
    },
)
pulumi.export("vm", vm_checked)
pulumi.export("scenario_ids", scenario_ids)
