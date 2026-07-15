"""OpenAPI tag categorization tests."""

from app.api.openapi import contract_openapi_tag, contract_openapi_tags, openapi_tag_metadata


def test_contract_openapi_tag_groups_by_domain() -> None:
    assert contract_openapi_tag("/version") == "Core"
    assert contract_openapi_tag("/access/ticket") == "Access"
    assert contract_openapi_tag("/nodes/{node}/qemu/{vmid}/config") == "Nodes · QEMU"
    assert contract_openapi_tag("/nodes/{node}/lxc/{vmid}/config") == "Nodes · LXC"
    assert contract_openapi_tag("/nodes/{node}/ceph/osd") == "Nodes · Ceph"
    assert contract_openapi_tag("/cluster/ha/resources") == "Cluster · HA"
    assert contract_openapi_tag("/pools") == "Pools"


def test_contract_openapi_tags_include_renderer() -> None:
    assert contract_openapi_tags("/version", "json") == ["Core", "API2 JSON"]
    assert contract_openapi_tags("/version", "extjs") == ["Core", "API2 ExtJS"]


def test_openapi_tag_metadata_is_deterministic() -> None:
    names = [entry["name"] for entry in openapi_tag_metadata()]
    assert names == sorted(names)
    assert "Nodes · QEMU" in names
    assert "Simulator" in names
