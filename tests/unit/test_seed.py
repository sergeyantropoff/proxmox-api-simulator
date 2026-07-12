"""Deterministic seed profile tests."""

from app.simulation.seed import small_profile, stable_id


def test_small_profile_has_stable_logical_state() -> None:
    first = small_profile()
    second = small_profile()

    assert first == second
    assert first.logical_state() == {
        "profile": "small",
        "nodes": [
            {"name": "pve1", "status": "online"},
            {"name": "pve2", "status": "online"},
        ],
        "resources": [
            {
                "kind": "qemu",
                "external_id": "100",
                "node": "pve1",
                "state": {"name": "demo", "status": "stopped"},
            },
            {
                "kind": "qemu",
                "external_id": "101",
                "node": "pve1",
                "state": {"name": "worker", "status": "stopped"},
            },
            {
                "kind": "storage",
                "external_id": "local",
                "node": "pve1",
                "state": {"content": ["iso", "backup"]},
            },
        ],
    }


def test_stable_ids_are_namespaced_and_repeatable() -> None:
    assert stable_id("qemu:100") == stable_id("qemu:100")
    assert stable_id("qemu:100") != stable_id("qemu:101")
