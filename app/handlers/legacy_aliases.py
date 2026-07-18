"""Legacy Proxmox path aliases for older contract snapshots."""

from __future__ import annotations

from app.api.registry import HandlerRegistry


def register_legacy_aliases(registry: HandlerRegistry) -> None:
    """Register older-path synonyms onto already-registered handlers when present."""

    def alias(old_path: str, old_verb: str, new_path: str, new_verb: str | None = None) -> None:
        verb = (new_verb or old_verb).upper()
        handler = registry.get(new_path, verb)
        if handler is None:
            return
        if registry.get(old_path, old_verb) is not None:
            return
        registry.register(old_path, old_verb.upper(), handler)

    alias("/access/tfa", "POST", "/access/tfa/{userid}", "POST")
    alias("/access/tfa", "PUT", "/access/tfa/{userid}/{id}", "PUT")
    # /cluster/backupinfo is registered as a PVE 6 stub string in backup.py
    alias(
        "/cluster/backupinfo/not_backed_up",
        "GET",
        "/cluster/backup-info/not-backed-up",
        "GET",
    )
    alias("/nodes/{node}/ceph/config", "GET", "/nodes/{node}/ceph/cfg/raw", "GET")
    alias("/nodes/{node}/ceph/configdb", "GET", "/nodes/{node}/ceph/cfg/db", "GET")
    alias("/nodes/{node}/ceph/disks", "GET", "/nodes/{node}/ceph/osd", "GET")
    alias("/nodes/{node}/ceph/flags", "GET", "/cluster/ceph/flags", "GET")
    alias("/nodes/{node}/ceph/flags/{flag}", "POST", "/cluster/ceph/flags/{flag}", "PUT")
    alias("/nodes/{node}/ceph/flags/{flag}", "DELETE", "/cluster/ceph/flags/{flag}", "PUT")
    alias("/nodes/{node}/ceph/pools", "GET", "/nodes/{node}/ceph/pool", "GET")
    alias("/nodes/{node}/ceph/pools", "POST", "/nodes/{node}/ceph/pool", "POST")
    alias("/nodes/{node}/ceph/pools/{name}", "GET", "/nodes/{node}/ceph/pool/{name}", "GET")
    alias("/nodes/{node}/ceph/pools/{name}", "PUT", "/nodes/{node}/ceph/pool/{name}", "PUT")
    alias(
        "/nodes/{node}/ceph/pools/{name}",
        "DELETE",
        "/nodes/{node}/ceph/pool/{name}",
        "DELETE",
    )
    alias("/nodes/{node}/cpu", "GET", "/nodes/{node}/capabilities/qemu/cpu", "GET")
    alias(
        "/nodes/{node}/hardware/pci/{pciid}",
        "GET",
        "/nodes/{node}/hardware/pci/{pci-id-or-mapping}",
        "GET",
    )
    alias(
        "/nodes/{node}/hardware/pci/{pciid}/mdev",
        "GET",
        "/nodes/{node}/hardware/pci/{pci-id-or-mapping}/mdev",
        "GET",
    )
    alias("/nodes/{node}/scan/glusterfs", "GET", "/nodes/{node}/scan/nfs", "GET")
    alias("/nodes/{node}/scan/usb", "GET", "/nodes/{node}/hardware/usb", "GET")
