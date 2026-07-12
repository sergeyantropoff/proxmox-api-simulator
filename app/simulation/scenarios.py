"""Seeded deterministic fault-rule evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FaultContext:
    method: str
    path: str
    principal: str | None = None
    node: str | None = None
    vmid: str | None = None
    call_number: int = 1


@dataclass(frozen=True, slots=True)
class FaultRule:
    kind: str
    probability: float = 1.0
    method: str | None = None
    path_prefix: str | None = None
    principal: str | None = None
    node: str | None = None
    vmid: str | None = None
    call_number: int | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.probability <= 1:
            raise ValueError("fault probability must be between zero and one")


def matches(rule: FaultRule, context: FaultContext, seed: int) -> bool:
    filters = (
        (rule.method, context.method),
        (rule.principal, context.principal),
        (rule.node, context.node),
        (rule.vmid, context.vmid),
        (rule.call_number, context.call_number),
    )
    if any(expected is not None and expected != actual for expected, actual in filters):
        return False
    if rule.path_prefix is not None and not context.path.startswith(rule.path_prefix):
        return False
    material = f"{seed}:{rule.kind}:{context.method}:{context.path}:{context.call_number}"
    sample = int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") / 2**64
    return sample < rule.probability
