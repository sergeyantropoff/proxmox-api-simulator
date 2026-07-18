"""Tests for contract example generation."""

from app.contracts.examples import (
    path_param_example,
    property_string_example,
    schema_example,
    wire_param_name,
)
from app.contracts.model import Schema


def test_path_param_examples_use_known_placeholders() -> None:
    assert path_param_example("node") == "pve01"
    assert path_param_example("vmid") == 100


def test_wire_param_name_expands_indexed() -> None:
    assert wire_param_name("link[n]") == "link0"
    assert wire_param_name("scsi[n]", index=1) == "scsi1"
    assert wire_param_name("vmid") == "vmid"


def test_schema_example_prefers_default_and_enum() -> None:
    assert schema_example(Schema(type="string", default="custom")) == "custom"
    assert schema_example(Schema(type="string", enum=("a", "b"))) == "a"


def test_schema_example_builds_object_and_array() -> None:
    schema = Schema(
        type="object",
        properties={
            "count": Schema(type="integer", minimum=2),
            "enabled": Schema(type="boolean", optional=True),
        },
    )
    assert schema_example(schema) == {"count": 2}


def test_schema_example_uses_named_proxmox_formats() -> None:
    assert schema_example(Schema(type="string", format="pve-node"), name="node") == "pve01"
    assert schema_example(Schema(type="string", format="pve-storage-id")) == "local"
    assert schema_example(Schema(type="string", format="ip")) == "192.168.0.1"
    # Parameter name hints win over the format token when both apply.
    assert schema_example(Schema(type="string", format="pve-node"), name="clustername") == "example"


def test_property_string_example_uses_bare_default_key() -> None:
    fmt = {
        "address": {
            "default_key": 1,
            "format": "address",
            "type": "string",
        },
        "priority": {
            "default": 0,
            "optional": 1,
            "type": "integer",
        },
    }
    assert property_string_example(fmt) == "192.168.0.1"
    assert schema_example(Schema(type="string", format=fmt), name="link[n]") == "192.168.0.1"


def test_property_string_example_includes_required_keys() -> None:
    fmt = {
        "enable": {
            "default_key": 1,
            "default": "1",
            "type": "boolean",
        },
        "burst": {
            "default": 5,
            "type": "integer",
            "minimum": 0,
        },
        "rate": {
            "default": "1/second",
            "optional": 1,
            "type": "string",
        },
    }
    assert property_string_example(fmt) == "1,burst=5"
