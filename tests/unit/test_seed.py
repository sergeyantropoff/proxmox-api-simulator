"""Deterministic seed profile tests."""

from typing import Any, cast

import pytest

from app.simulation.seed import (
    big_profile,
    build_profile,
    clear_simulation_state,
    cluster_domain_metadata,
    default_node_ops_for_seed,
    enrich_guest_state,
    enrich_storage_state,
    lab_profile,
    large_profile,
    small_profile,
    stable_id,
)


def test_lab_profile_matches_required_logical_shape() -> None:
    first = lab_profile()
    second = lab_profile()

    assert first == second
    state = first.logical_state()
    assert state == second.logical_state()
    assert state["nodes"] == [{"name": "pve01", "status": "online"}]
    resources = state["resources"]
    assert isinstance(resources, list)
    assert [resource["kind"] for resource in resources].count("qemu") == 2
    assert [resource["kind"] for resource in resources].count("lxc") == 1
    assert [resource["kind"] for resource in resources].count("storage") == 3
    assert [resource["kind"] for resource in resources].count("ceph-osd") == 3
    assert [resource["kind"] for resource in resources].count("ha") == 1
    tasks = state["tasks"]
    assert isinstance(tasks, list)
    assert len(tasks) == 2


def test_sized_cluster_profiles() -> None:
    small = small_profile()
    assert len(small.nodes) == 3
    assert sum(resource.kind in {"qemu", "lxc"} for resource in small.resources) == 50
    assert sum(resource.kind == "ceph-osd" for resource in small.resources) == 10
    assert sum(resource.kind == "ha" for resource in small.resources) == 3
    assert len(small.tasks) == 12

    large = large_profile()
    assert len(large.nodes) == 10
    assert sum(resource.kind in {"qemu", "lxc"} for resource in large.resources) == 1_000
    assert sum(resource.kind == "ceph-osd" for resource in large.resources) == 100
    assert sum(resource.kind == "pool" for resource in large.resources) == 2
    assert len(large.tasks) == 50

    big = big_profile()
    assert len(big.nodes) == 20
    assert sum(resource.kind in {"qemu", "lxc"} for resource in big.resources) == 2_000
    assert sum(resource.kind == "ceph-osd" for resource in big.resources) == 500
    assert sum(resource.kind == "pool" for resource in big.resources) == 3
    assert len(big.tasks) == 100
    assert build_profile("big") == big


def test_sized_profiles_spread_osds_across_nodes() -> None:
    for profile_name, expected in (("small", 10), ("large", 100), ("big", 500)):
        profile = build_profile(profile_name)
        names = {node.id: node.name for node in profile.nodes}
        counts: dict[str, int] = {name: 0 for name in names.values()}
        for resource in profile.resources:
            if resource.kind == "ceph-osd":
                counts[names[resource.node_id]] += 1
        assert sum(counts.values()) == expected
        assert max(counts.values()) - min(counts.values()) <= 1


def test_medium_and_fault_profiles_are_deterministic() -> None:
    medium = build_profile("medium")
    assert len(medium.nodes) == 3
    assert sum(resource.kind in {"qemu", "lxc"} for resource in medium.resources) == 50
    assert build_profile("ha-demo") == build_profile("ha-demo")
    broken = build_profile("broken-storage")
    assert any(resource.state.get("status") == "offline" for resource in broken.resources)


def test_large_profile_is_configurable_and_stable() -> None:
    first = large_profile(node_count=4, resource_count=1_000)
    second = large_profile(node_count=4, resource_count=1_000)
    assert first == second
    assert len(first.nodes) == 4
    guests = [r for r in first.resources if r.kind in {"qemu", "lxc"}]
    assert len(guests) == 1_000
    assert any(r.kind == "storage" and r.external_id == "local" for r in first.resources)
    assert any(r.kind == "ceph-osd" for r in first.resources)


def test_profile_validation() -> None:
    with pytest.raises(ValueError, match="unknown seed profile"):
        build_profile("missing")
    with pytest.raises(ValueError, match="positive"):
        large_profile(node_count=0, resource_count=1)


def test_demo_cluster_profile_shape() -> None:
    profile = build_profile("demo-cluster")
    assert profile.name == "demo-cluster"
    assert len(profile.nodes) == 20
    assert sum(resource.kind == "qemu" for resource in profile.resources) == 850
    assert sum(resource.kind == "lxc" for resource in profile.resources) == 150
    assert sum(resource.kind == "ceph-osd" for resource in profile.resources) == 300
    assert sum(resource.kind == "storage" for resource in profile.resources) >= 62
    assert len(profile.tasks) == 250
    external_ids = {
        resource.external_id for resource in profile.resources if resource.kind in {"qemu", "lxc"}
    }
    assert len(external_ids) == 1000


def test_demo_cluster_spreads_guests_evenly_across_nodes() -> None:
    profile = build_profile("demo-cluster")
    names = {node.id: node.name for node in profile.nodes}

    def counts(kind: str) -> list[int]:
        counter: dict[str, int] = {name: 0 for name in names.values()}
        for resource in profile.resources:
            if resource.kind == kind:
                counter[names[resource.node_id]] += 1
        return list(counter.values())

    for kind, expected_total in (("qemu", 850), ("lxc", 150), ("ceph-osd", 300)):
        values = counts(kind)
        assert sum(values) == expected_total
        assert max(values) - min(values) <= 1

    guest_counts = counts("qemu")
    guest_counts = [a + b for a, b in zip(guest_counts, counts("lxc"), strict=True)]
    assert max(guest_counts) - min(guest_counts) <= 2


def test_minimal_profile() -> None:
    profile = build_profile("minimal")
    assert len(profile.nodes) == 1
    assert not any(resource.kind in {"qemu", "lxc"} for resource in profile.resources)


def test_stable_ids_are_namespaced_and_repeatable() -> None:
    assert stable_id("qemu:100") == stable_id("qemu:100")
    assert stable_id("qemu:100") != stable_id("qemu:101")


def test_cluster_domain_metadata_seeds_list_domains() -> None:
    meta = cast(dict[str, Any], cluster_domain_metadata(lab_profile()))
    assert meta["firewall"]["scopes"]["cluster"]["rules"]
    assert meta["firewall"]["scopes"]["cluster"]["aliases"]
    assert meta["firewall"]["scopes"]["cluster"]["ipset"]
    assert meta["firewall"]["scopes"]["cluster"]["groups"]
    assert meta["firewall"]["scopes"]["node:pve01"]["rules"]
    assert meta["firewall"]["scopes"]["qemu:pve01:100"]["rules"]
    assert meta["firewall"]["scopes"]["lxc:pve01:200"]["rules"]
    assert meta["firewall_macros"]
    assert meta["sdn"]["zones"]
    assert meta["sdn"]["vnets"]
    assert meta["sdn"]["controllers"]
    assert meta["sdn"]["ipams"]
    assert meta["sdn"]["dns"]
    assert meta["notifications"]["endpoints"]["smtp"]
    assert meta["notifications"]["endpoints"]["gotify"]
    assert meta["notifications"]["matchers"]
    assert meta["notifications"]["matcher_fields"]
    assert meta["acme"]["accounts"]
    assert meta["acme"]["accounts"]["letsencrypt"]["tos_url"]
    assert meta["acme"]["plugins"]
    assert meta["acme"]["directories"]
    assert meta["acme"]["challenge_schema"]
    assert meta["mapping"]["pci"]
    assert meta["mapping"]["usb"]
    assert meta["mapping"]["dir"]
    # Single-node lab must not invent ghost peers.
    assert meta["replication"] == []
    assert "pve02" not in str(meta["sdn"]["controllers"])
    assert meta["metrics"]["servers"]
    assert meta["ha_groups"]
    assert meta["ceph"]["pools"]
    assert meta["ceph"]["flags"]
    assert "noup" in meta["ceph"]["flags"]
    assert meta["ceph"]["flags"]["nobackfill"] == 0
    assert meta["ceph"]["health"]["status"] == "HEALTH_OK"
    assert meta["ceph"]["version"]
    assert len([r for r in lab_profile().resources if r.kind == "ceph-osd"]) == 3
    assert any(r.kind == "storage" and r.external_id == "ceph" for r in lab_profile().resources)
    local = next(r for r in lab_profile().resources if r.external_id == "local")
    assert int(cast(int, local.state["total_bytes"])) > 0
    assert lab_profile().tasks[0].payload["node"] == "pve01"
    assert meta["qemu_cpu_flags"]
    assert meta["metrics"]["export_data"]
    assert meta["jobs"]["schedule_analyze_results"]
    ops = cast(dict[str, Any], default_node_ops_for_seed("pve01"))
    assert ops["vzdump"]["defaults"]["storage"] == "local"
    assert ops["status"]["mem"] > 0
    assert ops["status"]["maxmem"] > 0
    assert ops["capabilities"]["cpu"]
    assert ops["capabilities"]["machines"]
    assert ops["hosts"]["data"]
    assert ops["journal"]
    assert ops["syslog"]
    assert ops["netstat"]
    assert ops["rrddata"]
    assert ops["status"]["uptime"]
    assert ops["ip"]
    assert meta["cluster_config"]["totem"]
    assert meta["cluster_config"]["config_digest"]
    assert meta["cluster_config"]["corosync_conf"]
    assert meta["cluster_config"]["corosync_authkey"]
    first_node = next(iter(meta["cluster_config"]["added_nodes"].values()))
    assert first_node["pve_fp"].count(":") == 31
    assert first_node["pve_addr"]
    assert meta["backup_jobs"]["backup-daily"]["storage"] == "local"
    assert meta["quorate"] == 1
    guest = cast(
        dict[str, Any],
        enrich_guest_state({"name": "demo", "status": "stopped"}, kind="qemu", vmid="100"),
    )
    assert guest["scsi0"].startswith("local-lvm:")
    assert guest["ostype"] == "l26"
    assert str(guest["net0"]).startswith("virtio=")
    assert guest["agent"]["results"]["info"]
    assert guest["rrddata"]
    assert guest["migrate_preconditions"]
    storage = cast(
        dict[str, Any],
        enrich_storage_state({"total_bytes": 1000, "used_bytes": 100}, storage_id="local"),
    )
    assert storage["rrddata"]
    assert storage["file_restore"]
    assert storage["import_metadata"]

    small_meta = cast(dict[str, Any], cluster_domain_metadata(small_profile()))
    assert len(small_meta["replication"]) == 2
    assert small_meta["replication"][0]["guest"] == 101
    assert len(small_meta["backup_jobs"]) == 2
    assert len(small_meta["ha_groups"]) == 2
    assert small_meta["sdn"]["zones"]["public"]["digest"]
    assert small_meta["sdn"]["zones"]["public"]["state"] == "available"
    assert len(cast(dict[str, Any], cluster_domain_metadata(large_profile()))["replication"]) == 8
    assert len(cast(dict[str, Any], cluster_domain_metadata(large_profile()))["ha_groups"]) == 4
    assert len(cast(dict[str, Any], cluster_domain_metadata(big_profile()))["replication"]) == 16
    assert len(cast(dict[str, Any], cluster_domain_metadata(big_profile()))["ha_groups"]) == 6
    assert len(cast(dict[str, Any], cluster_domain_metadata(big_profile()))["ceph"]["pools"]) == 3

    ops = cast(dict[str, Any], default_node_ops_for_seed("pve1", node_index=1, node_count=3))
    apt_repos = cast(dict[str, Any], cast(dict[str, Any], ops["apt"])["repositories"])
    assert "files" in apt_repos and "standard-repos" in apt_repos
    cert = cast(list[dict[str, Any]], cast(dict[str, Any], ops["certificates"])["info"])[0]
    assert cert["pem"] and cert["san"] and cert["public-key-bits"] == 4096


def test_sized_profile_artifact_targets() -> None:
    from app.simulation.seed import _CLUSTER_SIZE_SPECS

    assert _CLUSTER_SIZE_SPECS["small"]["backups"] == 10
    assert _CLUSTER_SIZE_SPECS["small"]["snapshots"] == 12
    assert _CLUSTER_SIZE_SPECS["large"]["backups"] == 80
    assert _CLUSTER_SIZE_SPECS["large"]["snapshots"] == 100
    assert _CLUSTER_SIZE_SPECS["big"]["backups"] == 160
    assert _CLUSTER_SIZE_SPECS["big"]["snapshots"] == 200


@pytest.mark.asyncio
async def test_clear_simulation_state_wipes_api_created_identity() -> None:
    executed: list[str] = []

    class FakeConnection:
        async def execute(self, sql: str, *args: object) -> str:
            del args
            executed.append(" ".join(sql.split()))
            return "DELETE 0"

    await clear_simulation_state(FakeConnection())
    joined = "\n".join(executed)
    for table in (
        "resources",
        "nodes",
        "principals",
        "identity_groups",
        "roles",
        "storage_contents",
        "api_tokens",
    ):
        assert f"DELETE FROM {table}" in joined  # noqa: S608 - asserting SQL text
    assert "DELETE FROM realms WHERE name NOT IN" in joined
    assert any(sql.startswith("UPDATE clusters") for sql in executed)
