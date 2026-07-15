"""Tests for contract example generation."""

from app.contracts.examples import path_param_example, schema_example
from app.contracts.model import Schema


def test_path_param_examples_use_known_placeholders() -> None:
    assert path_param_example("node") == "pve01"
    assert path_param_example("vmid") == 100


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
