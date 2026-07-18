"""Deterministic idempotent simulation seed profiles."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import asyncpg  # type: ignore[import-untyped]
from asyncpg import Connection

from app.security.auth import hash_secret

NAMESPACE = uuid.UUID("c9040a72-b391-4a7e-9864-3ae46291a531")
CLUSTER_ID = uuid.UUID("dc760c47-d8d7-57e6-9404-f0c6f2395d8f")


def default_node_ops_for_seed(node_name: str) -> dict[str, object]:
    """Full durable node ops written to nodes.metadata at seed time."""

    suffix = (stable_id(f"node-ip:{node_name}").int % 200) + 10
    return {
        "network": [
            {
                "iface": "vmbr0",
                "type": "bridge",
                "active": 1,
                "method": "static",
                "address": f"10.0.0.{suffix}/24",
            },
            {
                "iface": "vmbr1",
                "type": "bridge",
                "active": 1,
                "method": "static",
                "address": f"10.10.0.{suffix}/24",
            },
            {"iface": "eno1", "type": "eth", "active": 1, "method": "manual"},
        ],
        "disks": {
            "list": [
                {
                    "devpath": "/dev/sda",
                    "size": 1_000_000_000_000,
                    "model": "SIM-DISK-01",
                    "serial": "SIM0001",
                    "gpt": 1,
                },
                {
                    "devpath": "/dev/sdb",
                    "size": 2_000_000_000_000,
                    "model": "SIM-SSD-01",
                    "serial": "SIM0002",
                    "gpt": 0,
                },
            ],
            "directory": [],
            "lvm": [],
            "lvmthin": [],
            "zfs": [],
            "smart": {
                "/dev/sda": {
                    "health": "PASSED",
                    "type": "scsi",
                    "model": "SIM-DISK-01",
                    "serial": "SIM0001",
                },
                "/dev/sdb": {
                    "health": "PASSED",
                    "type": "scsi",
                    "model": "SIM-SSD-01",
                    "serial": "SIM0002",
                },
            },
        },
        "services": {
            "pveproxy": {"state": "running", "enabled": 1},
            "pvedaemon": {"state": "running", "enabled": 1},
            "pvestatd": {"state": "running", "enabled": 1},
            "corosync": {"state": "running", "enabled": 1},
        },
        "apt": {
            "packages": [
                {
                    "Package": "pve-manager",
                    "Version": "9.2.3",
                    "OldVersion": "9.2.2",
                    "Status": "upgradable",
                },
                {"Package": "libpve-common-perl", "Version": "9.0.3", "Status": "installed"},
            ],
            "repositories": [
                {
                    "path": "/etc/apt/sources.list.d/pve-enterprise.list",
                    "enabled": 1,
                    "types": "deb",
                    "uri": "http://download.proxmox.com/debian/pve",
                    "suites": "bookworm",
                    "components": "pve-no-subscription",
                }
            ],
            "update": {"status": "stopped", "exitstatus": "OK"},
            "changelogs": {
                "pve-manager": "pve-manager (9.2.3) bookworm\n\n  * simulator seed\n",
            },
        },
        "hardware": {
            "pci": [
                {
                    "id": "0000:00:1f.2",
                    "vendor_name": "Intel Corporation",
                    "device_name": "SATA Controller",
                    "iommugroup": 0,
                },
                {
                    "id": "0000:01:00.0",
                    "vendor_name": "NVIDIA Corporation",
                    "device_name": "GP102 [GeForce GTX 1080 Ti]",
                    "iommugroup": 1,
                    "mdev": 1,
                },
            ],
            "usb": [
                {
                    "busnum": 1,
                    "devnum": 1,
                    "level": 0,
                    "port": "1",
                    "prodid": "0002",
                    "vendid": "1d6b",
                },
                {
                    "busnum": 2,
                    "devnum": 2,
                    "level": 1,
                    "port": "2",
                    "prodid": "5591",
                    "vendid": "0781",
                },
            ],
            "mdev": {
                "0000:01:00.0": [
                    {"type": "nvidia-11", "available": 4, "description": "GRID profile"},
                ]
            },
        },
        "scan": {
            "cifs": [{"server": "files.local", "share": "backups"}],
            "iscsi": [{"portal": "10.0.0.50:3260", "target": "iqn.2024-01.local:storage"}],
            "lvm": [{"vg": "pve", "size": 500_000_000_000, "free": 100_000_000_000}],
            "lvmthin": [{"lv": "data", "vg": "pve", "lv_size": 400_000_000_000}],
            "nfs": [{"server": "nfs.local", "path": "/export/pve", "options": "vers=4"}],
            "pbs": [{"server": "pbs.local", "datastore": "store1"}],
            "zfs": [{"pool": "rpool", "name": "rpool/data", "size": 800_000_000_000}],
        },
        "subscription": {
            "status": "notfound",
            "message": "There is no subscription key",
            "serverid": "SIMULATOR",
            "sockets": 1,
            "productname": "Proxmox VE",
            "url": "https://www.proxmox.com/en/proxmox-virtual-environment/pricing",
        },
        "dns": {"search": "local", "dns1": "1.1.1.1", "dns2": "8.8.8.8", "dns3": ""},
        "time": {"timezone": "UTC", "time": 1_720_000_000, "localtime": 1_720_000_000},
        "config": {
            "description": "Simulator node",
            "startall-onboot-delay": 0,
            "wakeonlan": "",
        },
        "certificates": {
            "custom": None,
            "acme": {"account": "letsencrypt", "domains": [], "certificate": None},
            "info": [],
        },
        "ceph": {
            "mds": {},
            "mgr": {
                node_name: {
                    "name": node_name,
                    "state": "active",
                    "addr": f"{node_name}.local:6800",
                }
            },
            "mon": {
                node_name: {
                    "name": node_name,
                    "addr": f"{node_name}.local:6789",
                    "rank": 0,
                }
            },
            "log": [{"t": 1_700_000_000, "n": 0, "line": "ceph simulator ready"}],
        },
        "aplinfo": [
            {
                "package": "alpine-3-standard",
                "section": "system",
                "type": "lxc",
                "version": "3.20",
            }
        ],
        "oci_tags": {"library/alpine": [{"tag": "latest"}, {"tag": "3.20"}]},
        "capabilities": {
            "cpu": [
                {"name": "host", "vendor": "QEMU", "custom": 0},
                {"name": "x86-64-v2-AES", "vendor": "QEMU", "custom": 0},
                {"name": "kvm64", "vendor": "QEMU", "custom": 0},
            ],
            "cpu_flags": [
                {"name": "aes", "introduces": "Westmere"},
                {"name": "avx", "introduces": "SandyBridge"},
                {"name": "avx2", "introduces": "Haswell"},
            ],
            "machines": [
                {"id": "pc-i440fx-9.0", "type": "i440fx", "version": "9.0"},
                {"id": "pc-q35-9.0", "type": "q35", "version": "9.0"},
            ],
            "migration": {"network": "", "type": "secure", "enabled": 1},
        },
        "hosts": {
            "data": f"127.0.0.1 localhost\n10.0.0.{suffix} {node_name}\n",
            "digest": "seedhosts",
        },
        "journal": [
            f"0: {node_name} systemd[1]: Started pveproxy.service.",
            f"1: {node_name} systemd[1]: Started pvedaemon.service.",
            f"2: {node_name} kernel: Booting simulator node {node_name}.",
        ],
        "syslog": [
            {"n": 0, "t": f"{node_name} kernel: simulator syslog ready"},
            {"n": 1, "t": f"{node_name} pvestatd[1]: status update ok"},
        ],
        "netstat": [
            {
                "in": 1_000_000,
                "out": 900_000,
                "vnet": "vmbr0",
                "hwaddr": "bc:24:11:00:00:01",
            },
            {
                "in": 500_000,
                "out": 450_000,
                "vnet": "vmbr1",
                "hwaddr": "bc:24:11:00:00:02",
            },
        ],
        "report": f"==== Proxmox node report for {node_name} ====\nuptime: seeded\n",
        "rrd": {"filename": f"/var/lib/rrdcached/db/pve-node-{node_name}.rrd"},
        "rrddata": [
            {"time": 1_720_000_000 - 120, "cpu": 0.05, "memused": 1_000_000_000},
            {"time": 1_720_000_000 - 60, "cpu": 0.07, "memused": 1_100_000_000},
            {"time": 1_720_000_000, "cpu": 0.04, "memused": 1_050_000_000},
        ],
        "vzdump": {
            "defaults": {
                "all": 0,
                "bwlimit": 0,
                "compress": "zstd",
                "dumpdir": "backup",
                "mode": "snapshot",
                "remove": 0,
                "storage": "nfs-backup",
                "mailto": "",
                "notes-template": "{{guestname}}",
            },
            "extractconfig": {
                "local:backup/vzdump-qemu-100.vma.zst": (
                    "# vzdump config for local:backup/vzdump-qemu-100.vma.zst\n"
                    "name: demo\nmemory: 2048\n"
                ),
            },
        },
        "status": {
            "uptime": 86_400 + suffix,
            "cpu": 0.05 + (suffix % 10) * 0.01,
            "memory": {
                "used": 4_000_000_000 + suffix * 10_000_000,
                "total": 32_000_000_000,
            },
            "loadavg": ["0.10", "0.20", "0.30"],
            "kversion": "6.8.12-1-pve",
            "pveversion": "pve-manager/9.2.3",
        },
        "ip": f"10.32.1.{suffix}",
        "cluster_status": {
            "ip": f"10.32.1.{suffix}",
            "level": "c",
            "type": "node",
            "quorate": 1,
        },
    }


def enrich_guest_state(state: dict[str, object], *, kind: str, vmid: str) -> dict[str, object]:
    """Ensure qemu/lxc resources carry durable agent/rrd/migrate catalogs."""

    enriched = dict(state)
    name = str(enriched.get("name") or f"{kind}-{vmid}")
    suffix = stable_id(f"guest-runtime:{kind}:{vmid}").int % 200
    agent_enabled = enriched.get("agent")
    if isinstance(agent_enabled, bool) and not agent_enabled:
        agent: dict[str, object] = {"enabled": False, "files": {}, "results": {}}
    else:
        existing_agent = enriched.get("agent")
        agent = dict(existing_agent) if isinstance(existing_agent, dict) else {}
        files = agent.get("files")
        if not isinstance(files, dict):
            files = {}
        files.setdefault("/etc/hostname", f"{name}\n")
        agent["files"] = files
        results = agent.get("results")
        if not isinstance(results, dict):
            results = {}
        results.setdefault(
            "info",
            {
                "version": "9.2.0-simulator",
                "supported_commands": [
                    {"name": "guest-ping", "enabled": True, "success-response": True},
                    {"name": "guest-info", "enabled": True, "success-response": True},
                    {"name": "guest-get-osinfo", "enabled": True, "success-response": True},
                ],
            },
        )
        results.setdefault(
            "get-osinfo",
            {
                "name": str(enriched.get("ostype") or "l26"),
                "pretty-name": f"Simulator guest {name}",
                "version": "1.0",
                "machine": "x86_64",
            },
        )
        results.setdefault("get-host-name", {"host-name": name})
        results.setdefault(
            "network-get-interfaces",
            [
                {
                    "name": "eth0",
                    "hardware-address": f"02:00:00:00:{suffix:02x}:01",
                    "ip-addresses": [
                        {
                            "ip-address": f"192.0.2.{(suffix % 200) + 10}",
                            "ip-address-type": "ipv4",
                            "prefix": 24,
                        }
                    ],
                }
            ],
        )
        results.setdefault("ping", {})
        results.setdefault("get-users", [{"user": "root", "login-time": 0}])
        results.setdefault(
            "get-fsinfo",
            [{"name": "/", "type": "ext4", "total-bytes": 32 * 1024**3}],
        )
        results.setdefault("get-memory-block-info", {"size": 1024**3})
        results.setdefault("get-memory-blocks", [{"start": 0, "size": 1024**3}])
        results.setdefault("get-timezone", {"zone": "UTC", "offset": 0})
        results.setdefault("get-vcpus", [{"online": True, "can-offline": False}])
        results.setdefault("fsfreeze-status", "thawed")
        results.setdefault("fstrim", {"paths": [{"path": "/", "trimmed": 0}]})
        agent["results"] = results
        agent["enabled"] = True
    enriched["agent"] = agent
    if "rrd" not in enriched or not isinstance(enriched.get("rrd"), dict):
        prefix = "pve-vm" if kind == "qemu" else "pve-ct"
        enriched["rrd"] = {"filename": f"{prefix}-{vmid}.rrd"}
    if "rrddata" not in enriched or not isinstance(enriched.get("rrddata"), list):
        memory = enriched.get("memory", 256)
        mem_mb = int(memory) if isinstance(memory, int | float | str) else 256
        mem = mem_mb * 1024 * 1024
        enriched["rrddata"] = [
            {"time": 1_720_000_000, "cpu": 0.05, "mem": mem, "netin": 0, "netout": 0},
            {
                "time": 1_720_000_060,
                "cpu": 0.08,
                "mem": mem + 4_000_000,
                "netin": 100,
                "netout": 80,
            },
        ]
    if "migrate_preconditions" not in enriched or not isinstance(
        enriched.get("migrate_preconditions"), dict
    ):
        enriched["migrate_preconditions"] = {"local_disks": [], "local_resources": []}
    if kind == "lxc" and (
        "interfaces" not in enriched or not isinstance(enriched.get("interfaces"), list)
    ):
        enriched["interfaces"] = [
            {
                "name": "eth0",
                "hwaddr": f"02:00:00:00:{suffix:02x}:11",
                "inet": f"192.0.2.{(suffix % 200) + 20}/24",
            }
        ]
    if "cloudinit_dump" not in enriched:
        enriched["cloudinit_dump"] = f"#cloud-config\nhostname: {name}\nmanage_etc_hosts: true\n"
    return enriched


def enrich_storage_state(state: dict[str, object], *, storage_id: str) -> dict[str, object]:
    enriched = dict(state)
    total_raw = enriched.get("total_bytes", 100)
    total = int(total_raw) if isinstance(total_raw, int | float | str) else 100
    used_raw = enriched.get("used_bytes", max(total // 10, 1))
    used = int(used_raw) if isinstance(used_raw, int | float | str) else max(total // 10, 1)
    if "rrd" not in enriched or not isinstance(enriched.get("rrd"), dict):
        enriched["rrd"] = {"filename": f"pve-storage-{storage_id}.rrd"}
    if "rrddata" not in enriched or not isinstance(enriched.get("rrddata"), list):
        enriched["rrddata"] = [
            {"time": 1_720_000_000, "used": used, "total": total},
            {"time": 1_720_000_060, "used": min(used + total // 50, total), "total": total},
        ]
    if "file_restore" not in enriched or not isinstance(enriched.get("file_restore"), dict):
        enriched["file_restore"] = {
            "/": [{"filepath": "/etc", "type": "d", "text": "etc"}],
            "/etc": [
                {"filepath": "/etc/hostname", "type": "f", "text": "hostname"},
                {"filepath": "/etc/hosts", "type": "f", "text": "hosts"},
            ],
        }
    if "import_metadata" not in enriched or not isinstance(enriched.get("import_metadata"), dict):
        enriched["import_metadata"] = {
            "type": "qemu",
            "disks": {"scsi0": f"{storage_id}:0/vm-import.raw"},
            "net0": "virtio,bridge=vmbr0",
        }
    if "identity" not in enriched or not isinstance(enriched.get("identity"), dict):
        enriched["identity"] = {
            "fingerprint": f"fp-{storage_id}",
            "type": str(enriched.get("storage_type") or "dir"),
        }
    return enriched


@dataclass(frozen=True, slots=True)
class SeedNode:
    id: uuid.UUID
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class SeedResource:
    id: uuid.UUID
    node_id: uuid.UUID
    kind: str
    external_id: str
    state: dict[str, object]


@dataclass(frozen=True, slots=True)
class SeedTask:
    id: uuid.UUID
    upid: str
    task_type: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class SeedProfile:
    name: str
    nodes: tuple[SeedNode, ...]
    resources: tuple[SeedResource, ...]
    tasks: tuple[SeedTask, ...] = ()

    def logical_state(self) -> dict[str, object]:
        nodes = [{"name": node.name, "status": node.status} for node in self.nodes]
        names = {node.id: node.name for node in self.nodes}
        resources = [
            {
                "kind": resource.kind,
                "external_id": resource.external_id,
                "node": names[resource.node_id],
                "state": resource.state,
            }
            for resource in self.resources
        ]
        tasks = [
            {"upid": task.upid, "task_type": task.task_type, "status": "success"}
            for task in self.tasks
        ]
        return {"profile": self.name, "nodes": nodes, "resources": resources, "tasks": tasks}


def stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


def _empty_firewall_scope(*, options: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "options": dict(
            options
            or {
                "enable": 1,
                "policy_in": "DROP",
                "policy_out": "ACCEPT",
                "log_level_in": "nolog",
                "log_level_out": "nolog",
            }
        ),
        "rules": [],
        "aliases": {},
        "ipset": {},
        "groups": {},
        "log": [],
    }


def cluster_domain_metadata(profile: SeedProfile) -> dict[str, object]:
    """Durable cluster metadata domains so list endpoints are non-empty after seed."""

    node_names = [node.name for node in profile.nodes]
    primary = node_names[0] if node_names else "pve01"
    secondary = node_names[1] if len(node_names) > 1 else "pve02"
    node_by_id = {node.id: node.name for node in profile.nodes}

    qemu_guests: list[tuple[str, str]] = []
    lxc_guests: list[tuple[str, str]] = []
    for resource in profile.resources:
        node_name = node_by_id.get(resource.node_id)
        if node_name is None:
            continue
        if resource.kind == "qemu":
            qemu_guests.append((node_name, resource.external_id))
        elif resource.kind == "lxc":
            lxc_guests.append((node_name, resource.external_id))

    # Keep large profiles bounded; small/demo stay fully covered within the cap.
    guest_cap = 128 if profile.name == "large" else 10_000
    qemu_guests = qemu_guests[:guest_cap]
    lxc_guests = lxc_guests[:guest_cap]
    replication_guest = qemu_guests[0][1] if qemu_guests else "100"

    cluster_fw = _empty_firewall_scope(
        options={
            "enable": 1,
            "policy_in": "DROP",
            "policy_out": "ACCEPT",
            "log_level_in": "info",
            "log_level_out": "nolog",
        }
    )
    cluster_fw["aliases"] = {
        "mgmt-net": {
            "name": "mgmt-net",
            "cidr": "10.0.0.0/24",
            "comment": "Management network",
        },
        "monitoring": {
            "name": "monitoring",
            "cidr": "10.20.0.0/24",
            "comment": "Prometheus / Grafana",
        },
    }
    cluster_fw["ipset"] = {
        "blocked-scanners": {
            "name": "blocked-scanners",
            "comment": "Known scanners",
            "entries": {
                "203.0.113.0/24": {
                    "cidr": "203.0.113.0/24",
                    "comment": "RFC5737 TEST-NET-3",
                    "nomatch": 0,
                }
            },
        }
    }
    cluster_fw["groups"] = {
        "web-tier": {
            "comment": "HTTP/HTTPS services",
            "rules": [
                {
                    "type": "in",
                    "action": "ACCEPT",
                    "proto": "tcp",
                    "dport": "443",
                    "comment": "HTTPS",
                    "enable": 1,
                    "pos": 0,
                }
            ],
        }
    }
    cluster_fw["rules"] = [
        {
            "type": "in",
            "action": "ACCEPT",
            "source": "+mgmt-net",
            "macro": "SSH",
            "comment": "SSH from mgmt",
            "enable": 1,
            "pos": 0,
        },
        {
            "type": "in",
            "action": "ACCEPT",
            "source": "+monitoring",
            "dport": "9100",
            "proto": "tcp",
            "comment": "Node exporter",
            "enable": 1,
            "pos": 1,
        },
        {
            "type": "in",
            "action": "DROP",
            "source": "+blocked-scanners",
            "comment": "Drop scanners",
            "enable": 1,
            "pos": 2,
        },
    ]
    cluster_fw["log"] = [
        {
            "n": 0,
            "t": 1720000000,
            "msg": "DROP IN 198.51.100.10 → 10.0.0.10:22 proto=tcp",
        }
    ]

    scopes: dict[str, object] = {"cluster": cluster_fw}
    for node_name in node_names:
        scope = _empty_firewall_scope()
        scope["rules"] = [
            {
                "type": "in",
                "action": "ACCEPT",
                "iface": "vmbr0",
                "comment": f"Allow bridge traffic on {node_name}",
                "enable": 1,
                "pos": 0,
            }
        ]
        scope["aliases"] = {
            f"{node_name}-mgmt": {
                "name": f"{node_name}-mgmt",
                "cidr": "10.0.0.0/24",
                "comment": f"{node_name} management",
            }
        }
        scope["ipset"] = {
            f"{node_name}-trusted": {
                "name": f"{node_name}-trusted",
                "comment": "Trusted clients",
                "entries": {
                    "10.0.0.0/8": {
                        "cidr": "10.0.0.0/8",
                        "comment": "RFC1918",
                        "nomatch": 0,
                    }
                },
            }
        }
        scope["log"] = [
            {
                "n": 0,
                "t": 1720000100,
                "msg": f"ACCEPT IN vmbr0 on {node_name}",
            }
        ]
        scopes[f"node:{node_name}"] = scope

    for node_name, vmid in qemu_guests:
        scope = _empty_firewall_scope()
        scope["rules"] = [
            {
                "type": "in",
                "action": "ACCEPT",
                "proto": "tcp",
                "dport": "443",
                "comment": f"HTTPS on VM {vmid}",
                "enable": 1,
                "pos": 0,
            }
        ]
        host = (stable_id(f"fw-vip:{vmid}").int % 250) + 1
        scope["aliases"] = {
            f"vm{vmid}-vip": {
                "name": f"vm{vmid}-vip",
                "cidr": f"10.10.{host}.10/32",
                "comment": f"VIP for VM {vmid}",
            }
        }
        scopes[f"qemu:{node_name}:{vmid}"] = scope

    for node_name, vmid in lxc_guests:
        scope = _empty_firewall_scope()
        scope["rules"] = [
            {
                "type": "in",
                "action": "ACCEPT",
                "proto": "tcp",
                "dport": "22",
                "comment": f"SSH on CT {vmid}",
                "enable": 1,
                "pos": 0,
            }
        ]
        scopes[f"lxc:{node_name}:{vmid}"] = scope

    ha_nodes = ",".join(node_names) if node_names else primary
    return {
        "firewall": {"scopes": scopes},
        "options": {
            "keyboard": "en-us",
            "email_from": "pve@example.local",
            "http_proxy": "",
            "description": f"Proxmox API simulator ({profile.name})",
            "mac_prefix": "BC:24:11",
        },
        "quorate": 1,
        "ha": {
            "armed": True,
            "status_current": {"quorate": 1, "mode": "active"},
            "manager_status": {"manager_status": "active", "quorum": "OK"},
        },
        "ha_groups": {
            "primary": {
                "nodes": ha_nodes,
                "nofailback": 0,
                "restricted": 0,
                "comment": "Default HA group",
            },
            "critical-services": {
                "nodes": ha_nodes,
                "nofailback": 1,
                "restricted": 0,
                "comment": "Critical services",
            },
        },
        "ha_rules": [
            {"rule": "node-fencing", "type": "node", "action": "restart"},
            {"rule": "service-ha", "type": "resource", "action": "failover"},
        ],
        "sdn": {
            "zones": {
                "public": {
                    "zone": "public",
                    "type": "simple",
                    "bridge": "vmbr0",
                    "bridges": [{"iface": "vmbr0", "active": 1}],
                    "vrf": "vrf-public",
                    "table": 100,
                    "mtu": 1500,
                    "comment": "Public zone",
                },
                "internal": {
                    "zone": "internal",
                    "type": "vlan",
                    "bridge": "vmbr1",
                    "bridges": [{"iface": "vmbr1", "active": 1}],
                    "vrf": "vrf-internal",
                    "table": 101,
                    "vlan-protocol": "802.1q",
                    "comment": "Internal VLAN zone",
                },
            },
            "vnets": {
                "vnet0": {
                    "vnet": "vnet0",
                    "zone": "public",
                    "alias": "Public VNet",
                    "mac-vrf": "macvrf-vnet0",
                    "tag": 0,
                    "subnets": {
                        "10.0.0.0/24": {
                            "subnet": "10.0.0.0/24",
                            "gateway": "10.0.0.1",
                            "snat": 0,
                        }
                    },
                    "ips": [],
                    "firewall": {
                        "options": {"enable": 1},
                        "rules": [
                            {
                                "type": "in",
                                "action": "ACCEPT",
                                "proto": "tcp",
                                "dport": "443",
                                "enable": 1,
                                "pos": 0,
                            }
                        ],
                    },
                },
                "vnet1": {
                    "vnet": "vnet1",
                    "zone": "internal",
                    "alias": "Internal VNet",
                    "mac-vrf": "macvrf-vnet1",
                    "tag": 100,
                    "subnets": {
                        "10.10.0.0/24": {
                            "subnet": "10.10.0.0/24",
                            "gateway": "10.10.0.1",
                            "snat": 1,
                        }
                    },
                    "ips": [],
                    "firewall": {"options": {"enable": 0}, "rules": []},
                },
            },
            "controllers": {
                "evpn1": {
                    "controller": "evpn1",
                    "type": "evpn",
                    "asn": 65000,
                    "peers": secondary,
                    "comment": "EVPN controller",
                }
            },
            "dns": {
                "powerdns": {
                    "dns": "powerdns",
                    "type": "powerdns",
                    "url": "http://dns.example.local:8081",
                    "key": "seed-dns-key",
                    "ttl": 300,
                }
            },
            "ipams": {
                "pve": {"ipam": "pve", "type": "pve", "comment": "Built-in IPAM"},
                "netbox": {
                    "ipam": "netbox",
                    "type": "netbox",
                    "url": "https://netbox.example.local",
                    "token": "seed-netbox-token",
                },
            },
            "fabrics": {
                "fabric0": {
                    "id": "fabric0",
                    "protocol": "ospf",
                    "ip-prefix": "10.99.0.0/24",
                    "comment": "Underlay fabric",
                    "routes": [{"dst": "10.99.0.0/24", "protocol": "ospf"}],
                }
            },
            "fabric_nodes": {
                "fabric0": {
                    node_name: {
                        "node": node_name,
                        "interfaces": ["eno1"],
                        "state": "up",
                    }
                    for node_name in node_names[:3] or [primary]
                }
            },
            "prefix_lists": {
                "pl-default": {
                    "name": "pl-default",
                    "entries": {"10": {"seq": "10", "action": "permit", "prefix": "10.0.0.0/8"}},
                }
            },
            "route_maps": {
                "rm-default": {
                    "name": "rm-default",
                    "entries": {"10": {"seq": "10", "action": "permit", "match": "pl-default"}},
                }
            },
            "lock": None,
            "pending": False,
            "running_version": 1,
        },
        "firewall_macros": [
            {"macro": "SSH", "descr": "Secure Shell"},
            {"macro": "HTTPS", "descr": "Secure web server"},
            {"macro": "HTTP", "descr": "Web server"},
        ],
        "notifications": {
            "matcher_fields": [
                {"name": "type", "type": "string"},
                {"name": "hostname", "type": "string"},
                {"name": "job-id", "type": "string"},
                {"name": "severity", "type": "string"},
            ],
            "matcher_field_values": [
                {"field": "type", "value": "fencing"},
                {"field": "type", "value": "package-updates"},
                {"field": "type", "value": "replication"},
                {"field": "type", "value": "system-mail"},
            ],
            "endpoints": {
                "gotify": {
                    "ops-gotify": {
                        "name": "ops-gotify",
                        "server": "https://gotify.example.local",
                        "token": "seed-gotify-token",
                        "comment": "Ops Gotify",
                        "disable": 0,
                    }
                },
                "sendmail": {
                    "local-mail": {
                        "name": "local-mail",
                        "mailto": "ops@example.local",
                        "from-address": "pve@example.local",
                        "comment": "Local sendmail",
                        "disable": 0,
                    }
                },
                "smtp": {
                    "alerts": {
                        "name": "alerts",
                        "server": "smtp.example.local",
                        "port": 587,
                        "mode": "starttls",
                        "from-address": "pve@example.local",
                        "mailto": "ops@example.local",
                        "comment": "Ops SMTP",
                        "disable": 0,
                    }
                },
                "webhook": {
                    "pager": {
                        "name": "pager",
                        "url": "https://hooks.example.local/pve",
                        "method": "post",
                        "comment": "Webhook pager",
                        "disable": 0,
                    }
                },
            },
            "matchers": {
                "backup-failures": {
                    "name": "backup-failures",
                    "match-field": ["type=package-updates"],
                    "target": ["alerts", "ops-gotify"],
                    "mode": "always",
                    "comment": "Route package/update noise",
                    "disable": 0,
                }
            },
            "tests": [],
        },
        "acme": {
            "accounts": {
                "letsencrypt": {
                    "name": "letsencrypt",
                    "contact": ["mailto:admin@example.local"],
                    "directory": "https://acme-v02.api.letsencrypt.org/directory",
                    "location": "https://acme.example.local/acct/letsencrypt",
                }
            },
            "plugins": {
                "cf-dns": {
                    "id": "cf-dns",
                    "type": "dns",
                    "api": "CF",
                    "data": {"CF_Token": "seed-cf-token"},
                    "validation-delay": 30,
                }
            },
            "directories": [
                {
                    "name": "Let's Encrypt V2",
                    "url": "https://acme-v02.api.letsencrypt.org/directory",
                },
                {
                    "name": "Let's Encrypt V2 Staging",
                    "url": "https://acme-staging-v02.api.letsencrypt.org/directory",
                },
            ],
            "challenge_schema": [
                {
                    "id": "dns",
                    "name": "DNS plugin",
                    "type": "dns",
                    "fields": [{"name": "api", "type": "string"}],
                }
            ],
            "meta": {
                "https://acme-v02.api.letsencrypt.org/directory": {
                    "termsOfService": "https://acme-v02.api.letsencrypt.org/directory/tos",
                    "caaIdentities": ["letsencrypt.org"],
                },
                "https://acme-staging-v02.api.letsencrypt.org/directory": {
                    "termsOfService": (
                        "https://acme-staging-v02.api.letsencrypt.org/directory/tos"
                    ),
                    "caaIdentities": ["letsencrypt.org"],
                },
            },
        },
        "mapping": {
            "pci": {
                "gpu0": {
                    "id": "gpu0",
                    "map": [f"{primary};0000:01:00.0;"],
                    "description": "Passthrough GPU",
                }
            },
            "usb": {
                "backup-key": {
                    "id": "backup-key",
                    "map": [f"{primary};2-2;"],
                    "description": "USB backup key",
                }
            },
            "dir": {
                "shared-data": {
                    "id": "shared-data",
                    "map": [f"{primary};/mnt/shared;"],
                    "description": "Shared directory mapping",
                }
            },
        },
        "replication": [
            {
                "id": f"{replication_guest}-0",
                "guest": replication_guest,
                "target": secondary,
                "type": "local",
                "schedule": "*/15",
                "rate": 100,
                "comment": f"Replicate VM/CT {replication_guest} to {secondary}",
                "enabled": 1,
                "source": primary,
                "state": "OK",
                "last_sync": 1720000200,
                "duration": 12,
                "fail_count": 0,
                "error": "",
                "log": [
                    {
                        "t": 1720000200,
                        "n": 0,
                        "msg": f"replication ok for {replication_guest}-0",
                    }
                ],
            }
        ],
        "metrics": {
            "export_data": '# HELP pve_up Node is up\npve_up{node="pve01"} 1\n',
            "servers": {
                "influx": {
                    "id": "influx",
                    "type": "influxdb",
                    "server": "influx.example.local",
                    "port": 8086,
                    "organization": "lab",
                    "bucket": "pve",
                    "enable": 1,
                    "comment": "InfluxDB metrics sink",
                }
            },
        },
        "jobs": {
            "realm_sync": {
                "ldap-sync": {
                    "id": "ldap-sync",
                    "realm": "pam",
                    "schedule": "0 3 * * *",
                    "enable": 1,
                    "comment": "Nightly realm sync",
                }
            },
            "schedule_analyze_results": [
                {"timestamp": 1_720_000_900, "utc": True},
                {"timestamp": 1_720_001_800, "utc": True},
                {"timestamp": 1_720_002_700, "utc": True},
                {"timestamp": 1_720_003_600, "utc": True},
            ],
        },
        "qemu_cpu_models": {
            "lab-cpu": {
                "name": "lab-cpu",
                "vendor": "GenuineIntel",
                "flags": "+aes",
                "comment": "Custom lab CPU model",
            }
        },
        "qemu_cpu_flags": [
            {"name": "aes", "introduces": "Westmere"},
            {"name": "avx", "introduces": "SandyBridge"},
            {"name": "avx2", "introduces": "Haswell"},
        ],
        "ceph": {
            "initialized": True,
            "running": True,
            "version": {"str": "18.2.2", "parts": [18, 2, 2]},
            "config": {
                "network": "10.10.10.0/24",
                "cluster-network": "10.10.10.0/24",
                "size": 3,
                "min_size": 2,
                "pg_bits": 7,
                "fsid": "pve-simulator-fsid",
            },
            "cfg_db": [
                {"section": "global", "name": "auth_client_required", "value": "cephx"},
                {"section": "global", "name": "fsid", "value": "pve-simulator-fsid"},
            ],
            "cfg_raw": "[global]\nfsid = pve-simulator-fsid\nauth_client_required = cephx\n",
            "cfg_values": {},
            "pools": {
                "rbd": {
                    "pool": "rbd",
                    "size": 3,
                    "min_size": 2,
                    "pg_num": 128,
                    "application": "rbd",
                    "crush_rule": "replicated_rule",
                    "bytes_used": 12_000_000_000,
                    "percent_used": 12.0,
                    "healthy": True,
                }
            },
            "fs": {},
            "rules": [{"name": "replicated_rule", "id": 0}],
            "crush": "device 0 osd.0 class hdd\n",
            "cmd_safety": {"safe": 1},
            "flags": {
                "nobackfill": 0,
                "nodeep-scrub": 0,
                "nodown": 0,
                "noin": 0,
                "noout": 0,
                "norebalance": 0,
                "norecover": 0,
                "noscrub": 0,
                "notieragent": 0,
                "pause": 0,
            },
        },
        "cluster_config": {
            "clustername": f"pve-{profile.name}",
            "votes": 1,
            "links": {},
            "join_info": {},
            "totem": {
                "version": 2,
                "secauth": "on",
                "cluster_name": f"pve-{profile.name}",
            },
            "qdevice": {"status": "disabled"},
            "apiversion": 1,
            "added_nodes": {
                node_name: {
                    "node": node_name,
                    "ring0_addr": f"{node_name}.local",
                    "quorum_votes": 1,
                }
                for node_name in node_names
            },
        },
    }


def _seed_resource_state(resource: SeedResource) -> dict[str, object]:
    if resource.kind in {"qemu", "lxc"}:
        return enrich_guest_state(
            dict(resource.state), kind=resource.kind, vmid=resource.external_id
        )
    if resource.kind == "storage":
        return enrich_storage_state(dict(resource.state), storage_id=resource.external_id)
    if resource.kind == "ceph-osd":
        state = dict(resource.state)
        state.setdefault("uuid", f"osd-uuid-{resource.external_id}")
        state.setdefault("dev", f"/dev/{resource.external_id.replace('.', '')}")
        state.setdefault("device_class", "hdd")
        return state
    return dict(resource.state)


def _string_list(state: dict[str, object], key: str) -> tuple[str, ...]:
    value = state.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"seed state {key} must be a string list")
    return tuple(value)


def _node(name: str, status: str = "online") -> SeedNode:
    return SeedNode(stable_id(f"node:{name}"), name, status)


def _resource(
    node: SeedNode, kind: str, external_id: str, state: dict[str, object]
) -> SeedResource:
    return SeedResource(stable_id(f"{kind}:{external_id}"), node.id, kind, external_id, state)


def _completed_task(index: int, task_type: str, resource_id: str) -> SeedTask:
    return SeedTask(
        stable_id(f"task:{index}:{task_type}:{resource_id}"),
        f"UPID:pve01:0000000{index}:0000000{index}:6500000{index}:"
        f"{task_type}:{resource_id}:root@pam:",
        task_type,
        {"resource_id": resource_id, "seeded": True},
    )


def small_profile() -> SeedProfile:
    node = _node("pve01")
    resources = (
        _resource(
            node,
            "qemu",
            "100",
            {
                "name": "demo",
                "status": "stopped",
                "agent": {"files": {"/etc/hostname": "demo\n"}},
            },
        ),
        _resource(
            node,
            "qemu",
            "101",
            {
                "name": "worker",
                "status": "stopped",
                "agent": {"files": {"/etc/hostname": "worker\n"}},
            },
        ),
        _resource(
            node,
            "lxc",
            "200",
            {
                "name": "service",
                "status": "stopped",
                "agent": {"files": {"/etc/hostname": "service\n"}},
            },
        ),
        _resource(node, "storage", "local", {"content": ["iso", "backup"], "status": "available"}),
        _resource(
            node, "storage", "local-lvm", {"content": ["images", "rootdir"], "status": "available"}
        ),
    )
    tasks = (_completed_task(1, "qmstart", "100"), _completed_task(2, "qmstop", "100"))
    return SeedProfile("small", (node,), resources, tasks)


def medium_profile() -> SeedProfile:
    nodes = tuple(_node(f"pve{index}") for index in range(1, 4))
    resources: list[SeedResource] = []
    for vmid in range(100, 150):
        node = nodes[(vmid - 100) % len(nodes)]
        resources.append(
            _resource(node, "qemu", str(vmid), {"name": f"vm-{vmid}", "status": "stopped"})
        )
    for vmid in range(200, 220):
        node = nodes[(vmid - 200) % len(nodes)]
        resources.append(
            _resource(node, "lxc", str(vmid), {"name": f"ct-{vmid}", "status": "stopped"})
        )
    for node in nodes:
        resources.append(
            _resource(
                node,
                "storage",
                f"local-{node.name}",
                {"content": ["images"], "shared": False, "status": "available"},
            )
        )
    resources.append(
        _resource(
            nodes[0],
            "storage",
            "shared",
            {"content": ["images", "backup"], "shared": True, "status": "available"},
        )
    )
    resources.append(_resource(nodes[0], "pool", "development", {"members": ["100", "101", "200"]}))
    tasks = tuple(_completed_task(index, "qmstart", str(99 + index)) for index in range(1, 11))
    return SeedProfile("medium", nodes, tuple(resources), tasks)


def large_profile(*, node_count: int = 10, resource_count: int = 10_000) -> SeedProfile:
    if node_count < 1 or resource_count < 1:
        raise ValueError("large profile counts must be positive")
    nodes = tuple(_node(f"pve{index}") for index in range(1, node_count + 1))
    resources = tuple(
        _resource(
            nodes[index % node_count],
            "qemu" if index % 4 else "lxc",
            str(100 + index),
            {"name": f"guest-{100 + index}", "status": "stopped"},
        )
        for index in range(resource_count)
    )
    return SeedProfile("large", nodes, resources)


def ha_demo_profile() -> SeedProfile:
    profile = medium_profile()
    resources = (
        *profile.resources,
        _resource(profile.nodes[0], "ha", "vm:100", {"state": "started", "group": "primary"}),
    )
    return SeedProfile("ha-demo", profile.nodes, resources, profile.tasks)


def minimal_profile() -> SeedProfile:
    node = _node("pve01")
    resources = (
        _resource(node, "storage", "local", {"content": ["iso", "backup"], "status": "available"}),
        _resource(
            node, "storage", "local-lvm", {"content": ["images", "rootdir"], "status": "available"}
        ),
    )
    return SeedProfile("minimal", (node,), resources)


def broken_storage_profile() -> SeedProfile:
    profile = small_profile()
    resources = tuple(
        _resource(
            next(node for node in profile.nodes if node.id == resource.node_id),
            resource.kind,
            resource.external_id,
            {**resource.state, "status": "offline", "error": "simulated I/O failure"}
            if resource.kind == "storage" and resource.external_id == "local-lvm"
            else resource.state,
        )
        for resource in profile.resources
    )
    return SeedProfile("broken-storage", profile.nodes, resources, profile.tasks)


def build_profile(
    name: str, *, large_nodes: int = 10, large_resources: int = 10_000
) -> SeedProfile:
    if name == "small":
        return small_profile()
    if name == "medium":
        return medium_profile()
    if name == "large":
        return large_profile(node_count=large_nodes, resource_count=large_resources)
    if name == "ha-demo":
        return ha_demo_profile()
    if name == "broken-storage":
        return broken_storage_profile()
    if name == "minimal":
        return minimal_profile()
    if name == "demo-cluster":
        from app.simulation.demo_cluster import demo_cluster_profile

        return demo_cluster_profile()
    raise ValueError(f"unknown seed profile: {name}")


def _storage_type(resource: SeedResource) -> str:
    configured = resource.state.get("storage_type")
    if isinstance(configured, str) and configured:
        return configured
    if resource.external_id.startswith("local"):
        if "lvm" in resource.external_id:
            return "lvmthin"
        if "zfs" in resource.external_id:
            return "zfspool"
        return "dir"
    if resource.external_id.startswith("ceph"):
        return "ceph"
    if resource.external_id.startswith("nfs"):
        return "nfs"
    return "dir"


def _storage_capacity(resource: SeedResource) -> tuple[int | None, int | None]:
    total = resource.state.get("total_bytes", resource.state.get("capacity_bytes"))
    used = resource.state.get("used_bytes")
    total_bytes = int(total) if isinstance(total, int) else None
    used_bytes = int(used) if isinstance(used, int) else None
    return total_bytes, used_bytes


async def clear_simulation_state(connection: Connection) -> None:
    """Remove all mutable simulator state so a seed/reset never fails on leftovers.

    API-created guests, storages, users, groups, roles, ACL/tokens and custom
    realms must not block "Remove demo data" / reseed. Builtin auth realms
    (`pam`, `pve`, `test`) are kept because principals reference them.
    """
    for statement in (
        "DELETE FROM task_logs",
        "DELETE FROM task_events",
        "DELETE FROM resource_locks",
        "DELETE FROM tasks",
        "DELETE FROM pool_members",
        "DELETE FROM backups",
        "DELETE FROM snapshots",
        "DELETE FROM storage_contents",
        "DELETE FROM vm_disks",
        "DELETE FROM vm_network_interfaces",
        "DELETE FROM virtual_machines",
        "DELETE FROM containers",
        "DELETE FROM storages",
        "DELETE FROM pools",
        "DELETE FROM resources",
        "DELETE FROM nodes",
        "DELETE FROM openid_pending",
        "DELETE FROM tfa_entries",
        "DELETE FROM group_acl_entries",
        "DELETE FROM identity_group_members",
        "DELETE FROM acl_entries",
        "DELETE FROM api_tokens",
        "DELETE FROM auth_tickets",
        "DELETE FROM identity_groups",
        "DELETE FROM principals",
        "DELETE FROM roles",
        "DELETE FROM realms WHERE name NOT IN ('pam', 'pve', 'test')",
        "DELETE FROM fault_injections",
        "DELETE FROM scenario_rules",
        "DELETE FROM audit_events",
    ):
        await connection.execute(statement)
    await connection.execute(
        """UPDATE clusters
        SET name = 'pve-simulator',
            metadata = '{}'::jsonb,
            updated_at = now()
        WHERE id = $1""",
        CLUSTER_ID,
    )


async def simulation_state_summary(connection: Connection) -> dict[str, object]:
    row = await connection.fetchrow(
        """SELECT
            c.name AS cluster_name,
            COALESCE(c.metadata->>'profile', 'unknown') AS profile,
            (SELECT count(*)::int FROM nodes) AS nodes,
            (SELECT count(*)::int FROM resources WHERE kind = 'qemu') AS qemu,
            (SELECT count(*)::int FROM resources WHERE kind = 'lxc') AS lxc,
            (SELECT count(*)::int FROM resources WHERE kind = 'ceph-osd') AS ceph_osds,
            (SELECT count(*)::int FROM resources WHERE kind = 'storage') AS storages,
            (SELECT count(*)::int FROM backups) AS backups,
            (SELECT count(*)::int FROM tasks) AS tasks,
            (SELECT count(*)::int FROM task_logs) AS task_logs,
            (SELECT count(*)::int FROM snapshots) AS snapshots,
            (SELECT count(*)::int FROM principals) AS principals,
            COALESCE(
                (SELECT sum(capacity_bytes)::bigint FROM storages WHERE storage_type = 'ceph'),
                0
            ) AS ceph_capacity_bytes
        FROM clusters c
        WHERE c.id = $1""",
        CLUSTER_ID,
    )
    if row is None:
        return {"profile": "unknown", "loaded": False}
    payload = dict(row)
    payload["loaded"] = payload["profile"] == "demo-cluster"
    payload["ceph_capacity_pib"] = round((payload.get("ceph_capacity_bytes") or 0) / 1024**5, 2)
    return payload


async def apply_seed(connection: Connection, profile: SeedProfile) -> None:
    async with connection.transaction():
        await clear_simulation_state(connection)
        await connection.execute(
            """UPDATE clusters
            SET name = $2,
                metadata = $3::jsonb,
                updated_at = now()
            WHERE id = $1""",
            CLUSTER_ID,
            "prod-pve-cluster" if profile.name == "demo-cluster" else "pve-simulator",
            json.dumps(
                {
                    "profile": profile.name,
                    "nodes": len(profile.nodes),
                    "resources": len(profile.resources),
                    **cluster_domain_metadata(profile),
                },
                sort_keys=True,
            ),
        )
        await connection.executemany(
            "INSERT INTO nodes(id, name, status, metadata) VALUES($1, $2, $3, $4::jsonb)",
            [
                (
                    node.id,
                    node.name,
                    node.status,
                    json.dumps({"ops": default_node_ops_for_seed(node.name)}, sort_keys=True),
                )
                for node in profile.nodes
            ],
        )
        await connection.executemany(
            """INSERT INTO resources(id, node_id, kind, external_id, state)
            VALUES($1, $2, $3, $4, $5::jsonb)""",
            [
                (
                    resource.id,
                    resource.node_id,
                    resource.kind,
                    resource.external_id,
                    json.dumps(_seed_resource_state(resource), sort_keys=True),
                )
                for resource in profile.resources
            ],
        )
        qemu = [resource for resource in profile.resources if resource.kind == "qemu"]
        if qemu:
            await connection.executemany(
                """INSERT INTO virtual_machines(resource_id, cluster_id, vmid, config)
                VALUES($1, 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f', $2, $3::jsonb)""",
                [
                    (
                        resource.id,
                        int(resource.external_id),
                        json.dumps(_seed_resource_state(resource), sort_keys=True),
                    )
                    for resource in qemu
                ],
            )
        containers = [resource for resource in profile.resources if resource.kind == "lxc"]
        if containers:
            await connection.executemany(
                """INSERT INTO containers(resource_id, cluster_id, vmid, config)
                VALUES($1, 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f', $2, $3::jsonb)""",
                [
                    (
                        resource.id,
                        int(resource.external_id),
                        json.dumps(_seed_resource_state(resource), sort_keys=True),
                    )
                    for resource in containers
                ],
            )
        storages = [resource for resource in profile.resources if resource.kind == "storage"]
        if storages:
            await connection.executemany(
                """INSERT INTO storages(
                    resource_id, cluster_id, storage_id, storage_type, shared,
                    capacity_bytes, used_bytes, config
                ) VALUES($1, $2, $3, $4, $5, $6, $7, $8::jsonb)""",
                [
                    (
                        resource.id,
                        str(CLUSTER_ID),
                        resource.external_id,
                        _storage_type(resource),
                        bool(resource.state.get("shared", False)),
                        *_storage_capacity(resource),
                        json.dumps(_seed_resource_state(resource), sort_keys=True),
                    )
                    for resource in storages
                ],
            )
            contents = [
                (
                    stable_id(f"content:{resource.external_id}:{content}"),
                    resource.id,
                    f"{resource.external_id}:{content}/seeded",
                    str(content),
                )
                for resource in storages
                for content in _string_list(resource.state, "content")
            ]
            if contents:
                await connection.executemany(
                    """INSERT INTO storage_contents(
                        id, storage_resource_id, volume_id, content_type
                    ) VALUES($1, $2, $3, $4)""",
                    contents,
                )
        pools = [resource for resource in profile.resources if resource.kind == "pool"]
        if pools:
            await connection.executemany(
                """INSERT INTO pools(id, cluster_id, pool_id, metadata)
                VALUES($1, 'dc760c47-d8d7-57e6-9404-f0c6f2395d8f', $2, $3::jsonb)""",
                [
                    (resource.id, resource.external_id, json.dumps(resource.state, sort_keys=True))
                    for resource in pools
                ],
            )
            members = [
                (pool.id, member.id)
                for pool in pools
                for external_id in _string_list(pool.state, "members")
                for member in profile.resources
                if member.external_id == external_id and member.kind in {"qemu", "lxc"}
            ]
            if members:
                await connection.executemany(
                    "INSERT INTO pool_members(pool_id, resource_id) VALUES($1, $2)", members
                )
        if profile.tasks:
            await connection.executemany(
                """INSERT INTO tasks(id, upid, status, payload, task_type, progress, result)
                VALUES($1, $2, 'success', $3::jsonb, $4, 100, '{\"seeded\":true}'::jsonb)""",
                [
                    (task.id, task.upid, json.dumps(task.payload, sort_keys=True), task.task_type)
                    for task in profile.tasks
                ],
            )
        await connection.execute(
            """INSERT INTO principals(id, name, password_hash, realm_name)
            VALUES($1, 'root@pam', $2, 'pam')
            ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
            realm_name=EXCLUDED.realm_name""",
            stable_id("principal:root@pam"),
            hash_secret("secret", salt=b"pve-simulator-v1"),
        )
        await connection.execute(
            """INSERT INTO api_tokens(principal_id, token_id, secret_hash, privileges)
            VALUES($1, 'automation', $2, $3)
            ON CONFLICT (principal_id, token_id) DO UPDATE
            SET secret_hash=EXCLUDED.secret_hash, privileges=EXCLUDED.privileges""",
            stable_id("principal:root@pam"),
            hash_secret("automation-secret", salt=b"pve-token-seed-v1"),
            ["VM.Audit", "VM.PowerMgmt", "Sys.Audit"],
        )
        auditor_id = stable_id("principal:auditor@pve")
        await connection.execute(
            """INSERT INTO principals(id, name, password_hash, realm_name)
            VALUES($1, 'auditor@pve', $2, 'pve')
            ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
            realm_name=EXCLUDED.realm_name""",
            auditor_id,
            hash_secret("auditor-secret", salt=b"pve-auditor-v1"),
        )
        await connection.execute(
            """INSERT INTO roles(name, privileges)
            VALUES('PVEAuditor', $1)
            ON CONFLICT (name) DO UPDATE SET privileges=EXCLUDED.privileges""",
            ["Sys.Audit", "VM.Audit"],
        )
        await connection.execute(
            "DELETE FROM acl_entries WHERE principal_id=$1 AND role_name='PVEAuditor'",
            auditor_id,
        )
        auditor_group_id = await connection.fetchval(
            """INSERT INTO identity_groups(id, group_id, comment)
            VALUES($1, 'auditors', 'Read-only operators')
            ON CONFLICT (group_id) DO UPDATE SET comment=EXCLUDED.comment
            RETURNING id""",
            stable_id("group:auditors"),
        )
        await connection.execute(
            """INSERT INTO identity_group_members(group_id, principal_id)
            VALUES($1, $2) ON CONFLICT DO NOTHING""",
            auditor_group_id,
            auditor_id,
        )
        await connection.execute(
            """INSERT INTO group_acl_entries(group_id, role_name, path, propagate)
            VALUES($1, 'PVEAuditor', '/', true)
            ON CONFLICT (group_id, role_name, path) DO UPDATE
            SET propagate=EXCLUDED.propagate""",
            auditor_group_id,
        )
        await connection.execute(
            """INSERT INTO api_tokens(principal_id, token_id, secret_hash, privileges)
            VALUES($1, 'readonly', $2, $3)
            ON CONFLICT (principal_id, token_id) DO UPDATE
            SET secret_hash=EXCLUDED.secret_hash, privileges=EXCLUDED.privileges""",
            auditor_id,
            hash_secret("readonly-secret", salt=b"pve-readonly-v1"),
            ["Sys.Audit", "VM.Audit"],
        )
        for username, role_name, privileges, acl_path, token_id, token_secret in (
            (
                "operator@pve",
                "PVEVMOperator",
                ["VM.Audit", "VM.PowerMgmt"],
                "/vms",
                "operator",
                "operator-secret",
            ),
            (
                "storage@pve",
                "PVEStorageUser",
                ["Datastore.Audit", "Datastore.AllocateSpace"],
                "/storage",
                "storage",
                "storage-secret",
            ),
        ):
            principal_id = stable_id(f"principal:{username}")
            await connection.execute(
                """INSERT INTO principals(id, name, password_hash, realm_name)
                VALUES($1, $2, $3, 'pve')
                ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
                realm_name=EXCLUDED.realm_name""",
                principal_id,
                username,
                hash_secret(f"{username}-password", salt=f"seed:{username}".encode()),
            )
            await connection.execute(
                """INSERT INTO roles(name, privileges) VALUES($1, $2)
                ON CONFLICT (name) DO UPDATE SET privileges=EXCLUDED.privileges""",
                role_name,
                privileges,
            )
            await connection.execute(
                """INSERT INTO acl_entries(principal_id, role_name, path, propagate)
                VALUES($1, $2, $3, true)
                ON CONFLICT (principal_id, role_name, path) DO UPDATE
                SET propagate=EXCLUDED.propagate""",
                principal_id,
                role_name,
                acl_path,
            )
            await connection.execute(
                """INSERT INTO api_tokens(principal_id, token_id, secret_hash, privileges)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (principal_id, token_id) DO UPDATE
                SET secret_hash=EXCLUDED.secret_hash, privileges=EXCLUDED.privileges,
                privilege_separation=true""",
                principal_id,
                token_id,
                hash_secret(token_secret, salt=f"token:{username}".encode()),
                privileges,
            )
        if profile.name == "demo-cluster":
            await _apply_demo_cluster_extras(connection, profile)


async def _apply_demo_cluster_extras(connection: Connection, profile: SeedProfile) -> None:
    names = {node.id: node.name for node in profile.nodes}
    guests = [resource for resource in profile.resources if resource.kind in {"qemu", "lxc"}]

    disks: list[tuple[uuid.UUID, uuid.UUID, str, str, int, str]] = []
    for index, resource in enumerate(guests):
        node_name = names[resource.node_id]
        disk_count = 1 + (index % 3)
        for disk_index in range(disk_count):
            device = "rootfs" if resource.kind == "lxc" and disk_index == 0 else f"scsi{disk_index}"
            storage_id = "ceph-prod" if (index + disk_index) % 4 == 0 else f"local-lvm-{node_name}"
            size_bytes = (20 + (index % 9) * 10 + disk_index * 15) * 1024**3
            disks.append(
                (
                    stable_id(f"disk:{resource.external_id}:{device}"),
                    resource.id,
                    device,
                    storage_id,
                    size_bytes,
                    json.dumps({"format": "raw" if disk_index else "qcow2"}, sort_keys=True),
                )
            )
    if disks:
        await connection.executemany(
            """INSERT INTO vm_disks(id, resource_id, device, storage_id, size_bytes, metadata)
            VALUES($1, $2, $3, $4, $5, $6::jsonb)""",
            disks,
        )

    interfaces: list[tuple[uuid.UUID, uuid.UUID, str, str]] = []
    for index, resource in enumerate(guests):
        interfaces.append(
            (
                stable_id(f"net:{resource.external_id}:net0"),
                resource.id,
                "net0",
                json.dumps(
                    {
                        "bridge": "vmbr0",
                        "firewall": index % 7 != 0,
                        "tag": (index % 12) * 10 or None,
                    },
                    sort_keys=True,
                ),
            )
        )
        if index % 5 == 0:
            interfaces.append(
                (
                    stable_id(f"net:{resource.external_id}:net1"),
                    resource.id,
                    "net1",
                    json.dumps({"bridge": "vmbr1", "firewall": True}, sort_keys=True),
                )
            )
    if interfaces:
        await connection.executemany(
            """INSERT INTO vm_network_interfaces(id, resource_id, device, config)
            VALUES($1, $2, $3, $4::jsonb)""",
            interfaces,
        )

    snapshots: list[tuple[uuid.UUID, uuid.UUID, str, str | None, str, str]] = []
    for index, resource in enumerate(guests):
        if index % 7 != 0:
            continue
        for snap_index in range(1 + (index % 3)):
            snap_name = f"snap-{snap_index:02d}"
            snapshots.append(
                (
                    stable_id(f"snapshot:{resource.external_id}:{snap_name}"),
                    resource.id,
                    snap_name,
                    None if snap_index == 0 else f"snap-{snap_index - 1:02d}",
                    f"Automated snapshot #{snap_index}",
                    json.dumps({"vmstate": index % 2 == 0}, sort_keys=True),
                )
            )
    if snapshots:
        await connection.executemany(
            """INSERT INTO snapshots(id, resource_id, name, parent_name, description, state)
            VALUES($1, $2, $3, $4, $5, $6::jsonb)""",
            snapshots,
        )

    storage_rows = await connection.fetch(
        """SELECT s.resource_id, s.storage_id, n.name AS node_name
        FROM storages s
        JOIN resources r ON r.id = s.resource_id
        JOIN nodes n ON n.id = r.node_id
        WHERE s.storage_id LIKE 'backup-%' OR s.storage_id IN ('ceph-prod', 'nfs-backup')"""
    )
    storage_by_id = {row["storage_id"]: row["resource_id"] for row in storage_rows}
    storage_by_node = {
        str(row["node_name"]): row["resource_id"]
        for row in storage_rows
        if str(row["storage_id"]).startswith("backup-")
    }
    fallback_backup = storage_by_id.get("nfs-backup") or storage_by_id.get("ceph-prod")
    if fallback_backup is not None:
        backups: list[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, str, int, str]] = []
        qemu_guests = [resource for resource in guests if resource.kind == "qemu"]
        for index, resource in enumerate(qemu_guests):
            node_name = names[resource.node_id]
            backup_storage = storage_by_node.get(node_name, fallback_backup)
            volume_id = f"backup/vzdump-qemu-{resource.external_id}-2026_07_15-{index:04d}.vma.zst"
            backups.append(
                (
                    stable_id(f"backup:{resource.external_id}:{index}"),
                    resource.id,
                    backup_storage,
                    volume_id,
                    (8 + (index % 40)) * 1024**3,
                    json.dumps(
                        {
                            "mode": "snapshot" if index % 3 else "suspend",
                            "notes-template": "Daily backup",
                            "node": node_name,
                        },
                        sort_keys=True,
                    ),
                )
            )
        if backups:
            await connection.executemany(
                """INSERT INTO backups(
                    id, resource_id, storage_resource_id, volume_id, size_bytes, metadata
                ) VALUES($1, $2, $3, $4, $5, $6::jsonb)""",
                backups,
            )

    guest_list = sorted(
        guests, key=lambda resource: (names[resource.node_id], resource.external_id)
    )
    extra_tasks: list[tuple[uuid.UUID, str, str, str, str]] = []
    for index in range(251, 321):
        guest = guest_list[(index - 251) % len(guest_list)]
        node_name = names[guest.node_id]
        node = next(node for node in profile.nodes if node.name == node_name)
        task_type = ("vzdump", "qmmigrate", "qmstart", "cephosd")[index % 4]
        status = "running" if index % 17 == 0 else "error" if index % 23 == 0 else "success"
        extra_tasks.append(
            (
                stable_id(f"demo-task-extra:{index}"),
                f"UPID:{node.name}:{index:07X}:{index:07X}:68{index:06X}:"
                f"{task_type}:{guest.external_id}:operator@pve:",
                status,
                json.dumps(
                    {"resource_id": guest.external_id, "node": node.name},
                    sort_keys=True,
                ),
                task_type,
            )
        )
    if extra_tasks:
        await connection.executemany(
            """INSERT INTO tasks(id, upid, status, payload, task_type, progress, result, error)
            VALUES($1, $2, $3, $4::jsonb, $5,
                CASE WHEN $3 = 'success' THEN 100 WHEN $3 = 'running' THEN 45 ELSE 0 END,
                CASE WHEN $3 = 'success' THEN '{\"seeded\":true}'::jsonb ELSE NULL END,
                CASE WHEN $3 = 'error' THEN 'simulated backup failure' ELSE NULL END)""",
            extra_tasks,
        )

    task_rows = await connection.fetch(
        "SELECT id, task_type, payload FROM tasks ORDER BY upid LIMIT 180"
    )
    logs: list[tuple[uuid.UUID, str]] = []
    for task in task_rows:
        payload = task["payload"]
        if isinstance(payload, dict):
            resource_id = payload.get("resource_id", "unknown")
            node_label = payload.get("node", "pve01")
        else:
            resource_id = "unknown"
            node_label = "unknown"
        messages: tuple[str, ...] = (
            f"starting task {task['task_type']} on {node_label}",
            f"processing guest {resource_id}",
            f"task {task['task_type']} finished successfully",
        )
        if task["task_type"] == "vzdump":
            messages = (
                f"INFO: starting backup of VM {resource_id} on {node_label}",
                f"INFO: snapshot create VM {resource_id}",
                f"INFO: archive file size: {(8 + hash(str(task['id'])) % 40)}GB",
                "INFO: Backup finished successfully",
            )
        logs.extend((task["id"], message) for message in messages)
    if logs:
        await connection.executemany(
            "INSERT INTO task_logs(task_id, message) VALUES($1, $2)",
            logs,
        )

    demo_users = (
        ("admin@pve", "PVEAdmin", ["/"], ["Sys.Modify", "Sys.Audit", "Datastore.Allocate"]),
        ("devops@pve", "PVEAdmin", ["/vms"], ["Sys.Audit", "VM.Allocate", "VM.PowerMgmt"]),
        (
            "backup-operator@pve",
            "PVEDatastoreAdmin",
            ["/storage"],
            ["Datastore.Allocate", "Datastore.Audit"],
        ),
        ("ceph-monitor@pve", "PVEAuditor", ["/"], ["Sys.Audit", "Datastore.Audit"]),
        ("junior@pve", "PVEAuditor", ["/vms"], ["Sys.Audit", "VM.Audit"]),
        ("security@pve", "PVEAuditor", ["/access"], ["Sys.Audit", "User.Modify"]),
    )
    for username, role_name, acl_paths, privileges in demo_users:
        principal_id = stable_id(f"principal:{username}")
        await connection.execute(
            """INSERT INTO principals(id, name, password_hash, realm_name)
            VALUES($1, $2, $3, 'pve')
            ON CONFLICT (name) DO UPDATE SET password_hash=EXCLUDED.password_hash,
            realm_name=EXCLUDED.realm_name""",
            principal_id,
            username,
            hash_secret(f"{username}-password", salt=f"seed:{username}".encode()),
        )
        await connection.execute(
            """INSERT INTO roles(name, privileges) VALUES($1, $2)
            ON CONFLICT (name) DO UPDATE SET privileges=EXCLUDED.privileges""",
            role_name,
            privileges,
        )
        for acl_path in acl_paths:
            await connection.execute(
                """INSERT INTO acl_entries(principal_id, role_name, path, propagate)
                VALUES($1, $2, $3, true)
                ON CONFLICT (principal_id, role_name, path) DO UPDATE
                SET propagate=EXCLUDED.propagate""",
                principal_id,
                role_name,
                acl_path,
            )


async def seed_url(
    database_url: str,
    profile_name: str = "small",
    *,
    large_nodes: int = 10,
    large_resources: int = 10_000,
) -> dict[str, object]:
    connection = await asyncpg.connect(database_url)
    try:
        profile = build_profile(
            profile_name, large_nodes=large_nodes, large_resources=large_resources
        )
        await apply_seed(connection, profile)
        return profile.logical_state()
    finally:
        await connection.close()
