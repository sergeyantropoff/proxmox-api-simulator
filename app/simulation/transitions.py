"""Explicit virtual-machine state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.simulation.clock import Clock


class VmState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    STOPPING = "stopping"
    MIGRATING = "migrating"
    SNAPSHOTTING = "snapshotting"
    BACKING_UP = "backing_up"
    ERROR = "error"


class InvalidTransitionError(ValueError):
    pass


TRANSITIONS: dict[tuple[VmState, str], tuple[VmState, VmState]] = {
    (VmState.STOPPED, "start"): (VmState.STARTING, VmState.RUNNING),
    (VmState.RUNNING, "stop"): (VmState.STOPPING, VmState.STOPPED),
    (VmState.RUNNING, "pause"): (VmState.PAUSING, VmState.PAUSED),
    (VmState.PAUSED, "resume"): (VmState.RESUMING, VmState.RUNNING),
    (VmState.RUNNING, "migrate"): (VmState.MIGRATING, VmState.RUNNING),
    (VmState.STOPPED, "migrate"): (VmState.MIGRATING, VmState.STOPPED),
    (VmState.RUNNING, "snapshot"): (VmState.SNAPSHOTTING, VmState.RUNNING),
    (VmState.STOPPED, "snapshot"): (VmState.SNAPSHOTTING, VmState.STOPPED),
    (VmState.RUNNING, "backup"): (VmState.BACKING_UP, VmState.RUNNING),
    (VmState.STOPPED, "backup"): (VmState.BACKING_UP, VmState.STOPPED),
}


@dataclass(frozen=True, slots=True)
class Transition:
    operation: str
    before: VmState
    intermediate: VmState
    after: VmState


def plan_transition(state: VmState, operation: str) -> Transition:
    states = TRANSITIONS.get((state, operation))
    if states is None:
        raise InvalidTransitionError(f"cannot {operation} VM while it is {state}")
    return Transition(operation, state, states[0], states[1])


async def execute_transition(
    state: VmState, operation: str, clock: Clock, duration_seconds: float
) -> tuple[VmState, VmState]:
    transition = plan_transition(state, operation)
    await clock.sleep(duration_seconds)
    return transition.intermediate, transition.after
