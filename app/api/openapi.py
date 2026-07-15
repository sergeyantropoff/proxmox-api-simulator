"""OpenAPI tag resolution for contract-driven routes."""

from __future__ import annotations

_NODE_SECTION_LABELS: dict[str, str] = {
    "qemu": "QEMU",
    "lxc": "LXC",
    "ceph": "Ceph",
    "storage": "Storage",
    "sdn": "SDN",
    "firewall": "Firewall",
    "apt": "APT",
    "certificates": "Certificates",
    "scan": "Scan",
    "network": "Network",
    "services": "Services",
    "capabilities": "Capabilities",
    "hardware": "Hardware",
    "replication": "Replication",
    "tasks": "Tasks",
    "subscription": "Subscription",
    "vzdump": "Backup",
    "disks": "Disks",
    "config": "Config",
    "dns": "DNS",
    "hosts": "Hosts",
    "status": "Status",
    "time": "Time",
    "aplinfo": "Appliance",
}

_CLUSTER_SECTION_LABELS: dict[str, str] = {
    "sdn": "SDN",
    "firewall": "Firewall",
    "notifications": "Notifications",
    "ha": "HA",
    "mapping": "Mapping",
    "acme": "ACME",
    "config": "Config",
    "ceph": "Ceph",
    "jobs": "Jobs",
    "metrics": "Metrics",
    "qemu": "QEMU",
    "backup": "Backup",
    "bulk-action": "Bulk Action",
    "replication": "Replication",
    "backup-info": "Backup Info",
    "options": "Options",
    "log": "Log",
    "nextid": "Next ID",
    "resources": "Resources",
    "status": "Status",
    "tasks": "Tasks",
}


def contract_openapi_tag(path: str) -> str:
    """Map a semantic contract path to a Swagger UI category."""

    parts = [part for part in path.strip("/").split("/") if part]
    if not parts or parts == ["version"]:
        return "Core"
    root = parts[0]
    if root == "access":
        return "Access"
    if root == "nodes":
        if len(parts) >= 3 and parts[1] == "{node}":
            section = parts[2]
            label = _NODE_SECTION_LABELS.get(section, section.replace("-", " ").title())
            return f"Nodes · {label}"
        return "Nodes"
    if root == "cluster":
        if len(parts) >= 2:
            section = parts[1]
            label = _CLUSTER_SECTION_LABELS.get(section, section.replace("-", " ").title())
            return f"Cluster · {label}"
        return "Cluster"
    if root == "storage":
        return "Storage"
    if root == "pools":
        return "Pools"
    return root.replace("-", " ").title()


def contract_openapi_tags(path: str, renderer: str) -> list[str]:
    """Return OpenAPI tags for a contract route, including the API renderer."""

    renderer_label = "API2 JSON" if renderer == "json" else "API2 ExtJS"
    return [contract_openapi_tag(path), renderer_label]


def openapi_tag_metadata() -> list[dict[str, str]]:
    """Descriptions shown in Swagger UI for each tag group."""

    descriptions: dict[str, str] = {
        "Core": "Version and global simulator metadata.",
        "Access": "Authentication, users, groups, roles, ACLs, and API tokens.",
        "Nodes": "Node inventory and node-level endpoints without a resource section.",
        "Storage": "Cluster-wide and node storage definitions and content.",
        "Pools": "Resource pools and membership.",
        "API2 JSON": "Proxmox `/api2/json` renderer routes.",
        "API2 ExtJS": "Proxmox `/api2/extjs` renderer routes.",
        "Simulator": "Health checks, compatibility reports, and the web console.",
    }
    for label in _NODE_SECTION_LABELS.values():
        descriptions.setdefault(f"Nodes · {label}", f"Node-level {label} API.")
    for label in _CLUSTER_SECTION_LABELS.values():
        descriptions.setdefault(f"Cluster · {label}", f"Cluster-level {label} API.")
    return [{"name": name, "description": text} for name, text in sorted(descriptions.items())]
