"""Enterprise-scale demo cluster profile for realistic emulator workloads."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from app.simulation.seed import (
    SeedNode,
    SeedProfile,
    SeedResource,
    SeedTask,
    _node,
    _resource,
    stable_id,
)

DEMO_NODE_COUNT = 20
DEMO_QEMU_COUNT = 850
DEMO_LXC_COUNT = 150
DEMO_CEPH_OSD_COUNT = 300
CEPH_TOTAL_BYTES = 5 * 1024**5
QEMU_VMID_START = 100
LXC_VMID_START = 10_000

QEMU_PREFIXES = (
    "web",
    "api",
    "db",
    "cache",
    "mq",
    "batch",
    "ml",
    "monitor",
    "log",
    "ci",
    "k8s",
    "vpn",
    "ldap",
    "git",
    "proxy",
)
LXC_PREFIXES = (
    "svc-nginx",
    "svc-haproxy",
    "svc-dns",
    "svc-vault",
    "svc-redis",
    "mon-agent",
    "backup-agent",
    "ceph-mgr",
    "lb-vip",
    "proxy-squid",
    "jump-host",
    "ntp",
    "syslog",
    "metrics",
    "bastion",
)
TIERS = ("prod", "staging", "dev", "qa", "dr")
POOLS = (
    ("production", 280),
    ("staging", 160),
    ("development", 130),
    ("qa", 100),
    ("gpu-workloads", 80),
    ("legacy", 100),
)
TASK_TYPES = (
    "vzdump",
    "qmstart",
    "qmstop",
    "qmmigrate",
    "qmreboot",
    "qmclone",
    "aptupdate",
    "startall",
    "stopall",
    "cephosd",
    "pct-start",
    "pct-stop",
)


def _even_node_slots(node_count: int, total: int, *, phase: int = 0) -> tuple[int, ...]:
    """Return `total` node indices distributed as evenly as possible."""

    if total <= 0:
        return ()
    base, remainder = divmod(total, node_count)
    slots: list[int] = []
    for node_index in range(node_count):
        slots.extend([node_index] * (base + (1 if node_index < remainder else 0)))
    if phase:
        phase %= len(slots)
        slots = slots[phase:] + slots[:phase]
    return tuple(slots)


def _even_sample(resources: Sequence[SeedResource], count: int) -> list[str]:
    """Pick `count` resource IDs spread evenly across the provided sequence."""

    if count <= 0 or not resources:
        return []
    if count >= len(resources):
        return [resource.external_id for resource in resources]
    step = len(resources) / count
    return [resources[int(index * step)].external_id for index in range(count)]


def _guest_name(prefixes: tuple[str, ...], index: int) -> str:
    prefix = prefixes[index % len(prefixes)]
    tier = TIERS[index % len(TIERS)]
    return f"{tier}-{prefix}-{index:04d}"


def _qemu_state(vmid: int, index: int) -> dict[str, object]:
    statuses = ("running", "running", "running", "running", "stopped", "paused")
    cpus = (1, 2, 2, 4, 4, 8, 8, 16, 32)[index % 9]
    memory_mb = (512, 1024, 2048, 4096, 8192, 16_384, 32_768, 65_536)[index % 8]
    pool_name = POOLS[index % len(POOLS)][0]
    return {
        "name": _guest_name(QEMU_PREFIXES, index),
        "status": statuses[index % len(statuses)],
        "cpus": cpus,
        "cores": cpus,
        "memory": memory_mb,
        "maxmem": memory_mb,
        "pool": pool_name,
        "tags": f"{TIERS[index % len(TIERS)]};{pool_name}",
        "agent": index % 3 != 0,
        "template": index % 97 == 0,
        "onboot": index % 5 != 0,
        "vmid": vmid,
    }


def _lxc_state(vmid: int, index: int) -> dict[str, object]:
    statuses = ("running", "running", "stopped", "stopped")
    memory_mb = (256, 512, 1024, 2048, 4096)[index % 5]
    pool_name = POOLS[(index + 2) % len(POOLS)][0]
    return {
        "name": _guest_name(LXC_PREFIXES, index),
        "status": statuses[index % len(statuses)],
        "cpus": (1, 1, 2, 2, 4)[index % 5],
        "memory": memory_mb,
        "maxmem": memory_mb,
        "pool": pool_name,
        "tags": f"container;{pool_name}",
        "unprivileged": index % 4 != 0,
        "template": index % 41 == 0,
        "vmid": vmid,
    }


def _demo_task(index: int, node: SeedNode, task_type: str, resource_id: str) -> SeedTask:
    return SeedTask(
        stable_id(f"demo-task:{index}:{task_type}:{resource_id}"),
        f"UPID:{node.name}:{index:07X}:{index:07X}:67{index:06X}:"
        f"{task_type}:{resource_id}:root@pam:",
        task_type,
        {"resource_id": resource_id, "node": node.name, "seeded": True},
    )


def demo_cluster_profile() -> SeedProfile:
    nodes = tuple(
        _node(f"pve{index:02d}", "offline" if index == 19 else "online")
        for index in range(1, DEMO_NODE_COUNT + 1)
    )
    node_count = len(nodes)
    resources: list[SeedResource] = []

    qemu_slots = _even_node_slots(node_count, DEMO_QEMU_COUNT, phase=0)
    lxc_slots = _even_node_slots(node_count, DEMO_LXC_COUNT, phase=node_count // 2)
    osd_slots = _even_node_slots(node_count, DEMO_CEPH_OSD_COUNT, phase=node_count // 4)

    qemu_resources: list[SeedResource] = []
    for offset, node_index in enumerate(qemu_slots):
        vmid = QEMU_VMID_START + offset
        resource = _resource(nodes[node_index], "qemu", str(vmid), _qemu_state(vmid, offset))
        qemu_resources.append(resource)
        resources.append(resource)

    lxc_resources: list[SeedResource] = []
    for offset, node_index in enumerate(lxc_slots):
        vmid = LXC_VMID_START + offset
        resource = _resource(nodes[node_index], "lxc", str(vmid), _lxc_state(vmid, offset))
        lxc_resources.append(resource)
        resources.append(resource)

    guests_by_node: dict[uuid.UUID, list[SeedResource]] = defaultdict(list)
    for guest in (*qemu_resources, *lxc_resources):
        guests_by_node[guest.node_id].append(guest)

    for node in nodes:
        resources.append(
            _resource(
                node,
                "storage",
                f"local-{node.name}",
                {
                    "content": ["iso", "vztmpl", "backup"],
                    "status": "available",
                    "storage_type": "dir",
                },
            )
        )
        resources.append(
            _resource(
                node,
                "storage",
                f"local-lvm-{node.name}",
                {
                    "content": ["images", "rootdir"],
                    "status": "available",
                    "storage_type": "lvmthin",
                    "shared": False,
                },
            )
        )
        resources.append(
            _resource(
                node,
                "storage",
                f"backup-{node.name}",
                {
                    "content": ["backup"],
                    "status": "available",
                    "storage_type": "dir",
                    "shared": False,
                    "total_bytes": 4 * 1024**4,
                    "used_bytes": int(2.2 * 1024**4),
                },
            )
        )
        if int(node.name[3:]) % 2 == 0:
            resources.append(
                _resource(
                    node,
                    "storage",
                    f"local-zfs-{node.name}",
                    {
                        "content": ["images", "rootdir"],
                        "status": "available",
                        "storage_type": "zfspool",
                        "shared": False,
                    },
                )
            )

    used_bytes = int(CEPH_TOTAL_BYTES * 0.62)
    resources.append(
        _resource(
            nodes[0],
            "storage",
            "ceph-prod",
            {
                "content": ["images", "rootdir", "backup"],
                "shared": True,
                "status": "available",
                "storage_type": "ceph",
                "ceph_pool": "rbd",
                "total_bytes": CEPH_TOTAL_BYTES,
                "used_bytes": used_bytes,
                "osd_count": DEMO_CEPH_OSD_COUNT,
            },
        )
    )
    resources.append(
        _resource(
            nodes[node_count // 2],
            "storage",
            "nfs-backup",
            {
                "content": ["backup", "iso"],
                "shared": True,
                "status": "available",
                "storage_type": "nfs",
                "total_bytes": 80 * 1024**4,
                "used_bytes": 52 * 1024**4,
            },
        )
    )

    for osd_index, node_index in enumerate(osd_slots):
        node = nodes[node_index]
        osd_id = osd_index
        weight = round(0.8 + (osd_index % 17) * 0.05, 2)
        size_bytes = CEPH_TOTAL_BYTES // DEMO_CEPH_OSD_COUNT
        resources.append(
            _resource(
                node,
                "ceph-osd",
                f"osd.{osd_id}",
                {
                    "osd_id": osd_id,
                    "status": "up" if osd_index != 42 else "down",
                    "in": osd_index != 42,
                    "weight": weight,
                    "size_bytes": size_bytes,
                    "used_bytes": int(size_bytes * (0.55 + (osd_index % 10) * 0.03)),
                    "device_class": "ssd" if osd_index % 4 else "hdd",
                },
            )
        )

    qemu_by_node = [
        sorted(guests_by_node[node.id], key=lambda resource: int(resource.external_id))
        for node in nodes
    ]
    pool_guest_cursor = 0
    for pool_index, (pool_id, member_count) in enumerate(POOLS):
        pool_guests: list[SeedResource] = []
        per_node, extra = divmod(member_count, node_count)
        for node_index, node_guests in enumerate(qemu_by_node):
            take = per_node + (1 if node_index < extra else 0)
            start = (pool_guest_cursor + node_index) % len(node_guests) if node_guests else 0
            for offset in range(take):
                if not node_guests:
                    break
                pool_guests.append(node_guests[(start + offset) % len(node_guests)])
        pool_guest_cursor += member_count
        pool_guests.sort(key=lambda resource: int(resource.external_id))
        resources.append(
            _resource(
                nodes[pool_index % node_count],
                "pool",
                pool_id,
                {
                    "members": _even_sample(pool_guests, min(40, len(pool_guests))),
                    "member_count": len(pool_guests),
                    "comment": f"Simulated {pool_id} pool",
                },
            )
        )

    ha_guests = [
        qemu_resources[int(index * len(qemu_resources) / min(120, len(qemu_resources)))]
        for index in range(min(120, len(qemu_resources)))
    ]
    for ha_index, guest in enumerate(ha_guests):
        node = next(node for node in nodes if node.id == guest.node_id)
        resources.append(
            _resource(
                node,
                "ha",
                f"vm:{guest.external_id}",
                {
                    "state": "started" if ha_index % 5 else "stopped",
                    "group": "critical-services",
                    "max_relocate": 2,
                    "max_restart": 3,
                },
            )
        )

    tasks: list[SeedTask] = []
    guest_cycle = sorted(
        (*qemu_resources, *lxc_resources),
        key=lambda resource: (resource.node_id, int(resource.external_id)),
    )
    for index in range(1, 251):
        guest = guest_cycle[(index - 1) % len(guest_cycle)]
        node = next(node for node in nodes if node.id == guest.node_id)
        task_type = TASK_TYPES[index % len(TASK_TYPES)]
        tasks.append(_demo_task(index, node, task_type, guest.external_id))

    return SeedProfile("demo-cluster", nodes, tuple(resources), tuple(tasks))
