"""Generate example values from Proxmox contract schemas.

Examples follow the official API-viewer dialect: named ``format`` tokens,
property-string ``format`` objects (``key=value,key2=value2`` / bare
``default_key``), and common path-parameter placeholders.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.model import Schema

_PATH_PARAM_EXAMPLES: dict[str, object] = {
    "node": "pve01",
    "vmid": 100,
    "storage": "local",
    "pool": "testpool",
    "userid": "root@pam",
    "tokenid": "automation",
    "realm": "pam",
    "group": "admins",
    "role": "Administrator",
    "upid": "UPID:pve01:00000001:00000001:65000001:qmstart:100:root@pam:",
    "snapname": "snap1",
    "volume": "local:100/vm-100-disk-0.qcow2",
    "disk": "scsi0",
    "iface": "net0",
    "key": "cpu",
    "digest": "00000000",
    "name": "example",
    "clustername": "example",
}

_FORMAT_EXAMPLES: dict[str, object] = {
    "pve-node": "pve01",
    "pve-node-list": "pve01,pve02",
    "pve-vmid": 100,
    "pve-vmid-list": "100,101",
    "pve-storage-id": "local",
    "pve-storage-server": "192.168.0.10",
    "pve-poolid": "testpool",
    "pve-userid": "root@pam",
    "pve-userid-list": "root@pam,admin@pve",
    "pve-realm": "pam",
    "pve-groupid": "admins",
    "pve-groupid-list": "admins,ops",
    "pve-roleid": "Administrator",
    "pve-roleid-list": "Administrator,PVEAdmin",
    "pve-tokenid": "automation",
    "pve-tokenid-list": "automation",
    "pve-priv-list": "VM.Allocate,VM.Config.Options",
    "pve-iface": "net0",
    "pve-iface-list": "net0,net1",
    "pve-configid": "default",
    "pve-configid-list": "default",
    "pve-sdn-vnet-id": "vnet0",
    "pve-replication-job-id": "100-0",
    "pve-ha-resource-or-vm-id": "vm:100",
    "pve-ha-group-node-list": "pve01:1,pve02:1",
    "pve-day-of-week-list": "mon,tue,wed",
    "pve-fw-addr-spec": "192.168.0.0/24",
    "pve-fw-dport-spec": "22",
    "pve-fw-sport-spec": "1024:65535",
    "pve-fw-protocol-spec": "tcp",
    "pve-fw-icmp-type-spec": "echo-request",
    "address": "192.168.0.1",
    "ip": "192.168.0.1",
    "IPorCIDR": "192.168.0.0/24",
    "IPorCIDRorAlias": "192.168.0.0/24",
    "dns-name": "example.local",
    "email-opt": "admin@example.local",
    "email-list": "admin@example.local",
    "email-or-username-list": "admin@example.local",
    "ldap-simple-attr": "uid",
    "ldap-simple-attr-list": "posixGroup,groupOfNames",
    "string-alist": "/var/lib/vz",
    "pve-tfa-secret": "ABCDEFGHIJKLMNOP",
}


def path_param_example(name: str) -> object | None:
    """Return a realistic placeholder for a common Proxmox path parameter."""

    return _PATH_PARAM_EXAMPLES.get(name)


def wire_param_name(name: str, *, index: int = 0) -> str:
    """Map contract ``foo[n]`` names to a concrete wire key (``foo0``)."""

    if "[n]" in name:
        return name.replace("[n]", str(index))
    return name


def schema_example(schema: Schema, *, name: str | None = None) -> object:
    """Build a representative example value for a contract schema."""

    if schema.default is not None:
        return schema.default
    if schema.enum:
        return schema.enum[0]
    if name is not None:
        hinted = path_param_example(name)
        if hinted is not None:
            return hinted
        if "[n]" in name:
            indexed = name.replace("[n]", "0")
            hinted = path_param_example(indexed.rstrip("0123456789"))
            if hinted is not None:
                return hinted
            base = indexed.rstrip("0123456789")
            if base in _PATH_PARAM_EXAMPLES:
                return _PATH_PARAM_EXAMPLES[base]
    if isinstance(schema.format, Mapping):
        return property_string_example(schema.format)
    if isinstance(schema.format, str):
        formatted = _named_format_example(schema.format, name=name)
        if formatted is not None:
            return formatted
        if schema.format == "email":
            return "user@example.com"
        if schema.format == "uri":
            return "https://example.com"
    if schema.type == "array":
        if schema.items is not None:
            return [schema_example(schema.items)]
        return []
    if schema.type == "object":
        return {
            key: schema_example(definition, name=key)
            for key, definition in schema.properties.items()
            if not definition.optional
        }
    if schema.type == "boolean":
        return False
    if schema.type == "integer":
        if schema.minimum is not None:
            return int(schema.minimum)
        return 1
    if schema.type == "number":
        if schema.minimum is not None:
            return float(schema.minimum)
        return 1.0
    if schema.type == "string" or schema.type is None:
        return "example"
    return None


def property_string_example(fmt: Mapping[str, Any]) -> str:
    """Render a Proxmox property-string example from a ``format`` object.

    Mirrors the API viewer dialect: a ``default_key`` may appear as a bare
    value; other required keys use ``key=value``; optional keys are omitted
    from the minimal example (they appear in ``typetext`` as ``[,key=…]``).
    """

    bare: str | None = None
    keyed: list[str] = []
    for key, raw in sorted(fmt.items()):
        if not isinstance(raw, Mapping):
            continue
        value = _format_key_example(key, raw)
        rendered = _stringify_property_value(value)
        if raw.get("default_key"):
            bare = rendered
            continue
        if _is_optional_flag(raw.get("optional")):
            continue
        keyed.append(f"{key}={rendered}")

    if bare is not None and not keyed:
        return bare
    if bare is not None:
        return ",".join([bare, *keyed])
    if keyed:
        return ",".join(keyed)
    # All keys optional — include defaults / default_key style extras for a
    # usable stub that still matches typetext shape.
    fallback: list[str] = []
    for key, raw in sorted(fmt.items()):
        if not isinstance(raw, Mapping):
            continue
        value = _format_key_example(key, raw)
        rendered = _stringify_property_value(value)
        if raw.get("default_key"):
            return rendered
        fallback.append(f"{key}={rendered}")
    return ",".join(fallback) if fallback else "example"


def _named_format_example(fmt: str, *, name: str | None) -> object | None:
    if fmt in _FORMAT_EXAMPLES:
        return _FORMAT_EXAMPLES[fmt]
    if fmt.endswith("-list") and fmt[: -len("-list")] in _FORMAT_EXAMPLES:
        base = _FORMAT_EXAMPLES[fmt[: -len("-list")]]
        return str(base)
    if name and name in _FORMAT_EXAMPLES:
        return _FORMAT_EXAMPLES[name]
    return None


def _format_key_example(key: str, raw: Mapping[str, Any]) -> object:
    if "default" in raw and raw["default"] is not None:
        return raw["default"]
    enum = raw.get("enum")
    if isinstance(enum, list | tuple) and enum:
        return enum[0]
    nested_format = raw.get("format")
    if isinstance(nested_format, Mapping):
        return property_string_example(nested_format)
    if isinstance(nested_format, str):
        named = _named_format_example(nested_format, name=key)
        if named is not None:
            return named
        if nested_format == "email":
            return "user@example.com"
        if nested_format == "uri":
            return "https://example.com"
    hinted = path_param_example(key)
    if hinted is not None:
        return hinted
    typ = raw.get("type")
    if typ == "boolean":
        return 1
    if typ == "integer":
        minimum = raw.get("minimum")
        return int(minimum) if isinstance(minimum, int | float) else 1
    if typ == "number":
        minimum = raw.get("minimum")
        return float(minimum) if isinstance(minimum, int | float) else 1.0
    pattern = raw.get("pattern")
    if isinstance(pattern, str) and "second|minute|hour|day" in pattern:
        return "1/second"
    return "example"


def _stringify_property_value(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _is_optional_flag(value: object) -> bool:
    if value is True or value == 1 or value == "1":
        return True
    return False
