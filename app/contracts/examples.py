"""Generate example values from Proxmox contract schemas."""

from __future__ import annotations

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
}


def path_param_example(name: str) -> object | None:
    """Return a realistic placeholder for a common Proxmox path parameter."""

    return _PATH_PARAM_EXAMPLES.get(name)


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
        if schema.format == "email":
            return "user@example.com"
        if schema.format == "uri":
            return "https://example.com"
        return "example"
    return None
