"""VM state-machine and deterministic fault properties."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.simulation.scenarios import FaultContext, FaultRule, matches
from app.simulation.transitions import InvalidTransitionError, VmState, plan_transition


@pytest.mark.parametrize(
    ("state", "operation", "final"),
    [
        (VmState.STOPPED, "start", VmState.RUNNING),
        (VmState.RUNNING, "stop", VmState.STOPPED),
        (VmState.RUNNING, "shutdown", VmState.STOPPED),
        (VmState.RUNNING, "reboot", VmState.RUNNING),
        (VmState.RUNNING, "reset", VmState.RUNNING),
        (VmState.RUNNING, "suspend", VmState.PAUSED),
        (VmState.RUNNING, "pause", VmState.PAUSED),
        (VmState.PAUSED, "resume", VmState.RUNNING),
        (VmState.RUNNING, "snapshot", VmState.RUNNING),
        (VmState.STOPPED, "migrate", VmState.STOPPED),
    ],
)
def test_valid_transitions(state: VmState, operation: str, final: VmState) -> None:
    transition = plan_transition(state, operation)
    assert transition.before is state
    assert transition.after is final
    assert transition.intermediate is not state


@given(st.sampled_from(tuple(VmState)), st.text(min_size=1, max_size=12))
def test_transition_result_is_declared_or_rejected(state: VmState, operation: str) -> None:
    try:
        transition = plan_transition(state, operation)
    except InvalidTransitionError:
        return
    assert transition.before is state


def test_fault_evaluation_is_seeded_and_filtered() -> None:
    context = FaultContext("POST", "/nodes/pve1/qemu/100/status/start", node="pve1")
    certain = FaultRule("task-failure", method="POST", node="pve1")
    impossible = FaultRule("task-failure", probability=0)

    assert matches(certain, context, seed=42)
    assert not matches(impossible, context, seed=42)
    probabilistic = FaultRule("task-failure", probability=0.5)
    assert matches(probabilistic, context, 42) == matches(probabilistic, context, 42)
