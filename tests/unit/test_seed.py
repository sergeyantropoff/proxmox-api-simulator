"""Deterministic seed profile tests."""

import pytest

from app.simulation.seed import build_profile, large_profile, small_profile, stable_id


def test_small_profile_matches_required_logical_shape() -> None:
    first = small_profile()
    second = small_profile()

    assert first == second
    state = first.logical_state()
    assert state == second.logical_state()
    assert state["nodes"] == [{"name": "pve1", "status": "online"}]
    resources = state["resources"]
    assert isinstance(resources, list)
    assert [resource["kind"] for resource in resources].count("qemu") == 2
    assert [resource["kind"] for resource in resources].count("lxc") == 1
    assert [resource["kind"] for resource in resources].count("storage") == 2
    tasks = state["tasks"]
    assert isinstance(tasks, list)
    assert len(tasks) == 2


def test_medium_and_fault_profiles_are_deterministic() -> None:
    medium = build_profile("medium")
    assert len(medium.nodes) == 3
    assert sum(resource.kind == "qemu" for resource in medium.resources) == 50
    assert sum(resource.kind == "lxc" for resource in medium.resources) == 20
    assert build_profile("ha-demo") == build_profile("ha-demo")
    broken = build_profile("broken-storage")
    assert any(resource.state.get("status") == "offline" for resource in broken.resources)


def test_large_profile_is_configurable_and_stable() -> None:
    first = large_profile(node_count=4, resource_count=1_000)
    second = large_profile(node_count=4, resource_count=1_000)
    assert first == second
    assert len(first.nodes) == 4
    assert len(first.resources) == 1_000


def test_profile_validation() -> None:
    with pytest.raises(ValueError, match="unknown seed profile"):
        build_profile("missing")
    with pytest.raises(ValueError, match="positive"):
        large_profile(node_count=0, resource_count=1)


def test_stable_ids_are_namespaced_and_repeatable() -> None:
    assert stable_id("qemu:100") == stable_id("qemu:100")
    assert stable_id("qemu:100") != stable_id("qemu:101")
