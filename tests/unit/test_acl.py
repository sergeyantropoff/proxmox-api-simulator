"""ACL propagation, token separation, and contract mapping tests."""

from app.contracts.model import Permissions
from app.security.acl import AclEntry, authorize, effective_privileges, requirement_from_contract

ENTRIES = (
    AclEntry("alice@pve", "/vms", frozenset({"VM.Audit", "VM.PowerMgmt"})),
    AclEntry("alice@pve", "/vms/200", frozenset({"VM.Config"}), propagate=False),
)


def test_acl_propagation_matrix() -> None:
    assert effective_privileges("alice@pve", "/vms/100", ENTRIES) == frozenset(
        {"VM.Audit", "VM.PowerMgmt"}
    )
    assert "VM.Config" in effective_privileges("alice@pve", "/vms/200", ENTRIES)
    assert "VM.Config" not in effective_privileges("alice@pve", "/vms/200/snapshot", ENTRIES)
    assert not effective_privileges("bob@pve", "/vms/100", ENTRIES)


def test_api_token_privileges_are_intersection_not_escalation() -> None:
    assert authorize(
        "alice@pve",
        "/vms/100",
        frozenset({"VM.Audit"}),
        ENTRIES,
        token_privileges=frozenset({"VM.Audit"}),
    )
    assert not authorize(
        "alice@pve",
        "/vms/100",
        frozenset({"VM.PowerMgmt"}),
        ENTRIES,
        token_privileges=frozenset({"VM.Audit"}),
    )


def test_contract_permission_maps_to_capability_requirement() -> None:
    permissions = Permissions(expression={"check": ["perm", "/vms/{vmid}", ["VM.PowerMgmt"]]})

    requirement = requirement_from_contract(permissions, {"vmid": "100"})

    assert requirement is not None
    assert requirement.path == "/vms/100"
    assert requirement.privileges == frozenset({"VM.PowerMgmt"})
