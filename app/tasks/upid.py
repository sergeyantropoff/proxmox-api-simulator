"""Proxmox-compatible unique process/task identifiers."""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass

UPID_RE = re.compile(
    r"^UPID:(?P<node>[A-Za-z0-9][A-Za-z0-9_-]*):"
    r"(?P<pid>[0-9A-Fa-f]{8}):(?P<pstart>[0-9A-Fa-f]{8}):"
    r"(?P<start>[0-9A-Fa-f]{8}):(?P<type>[A-Za-z0-9_-]+):"
    r"(?P<task_id>[^:]*):(?P<user>[^:]+):$"
)


@dataclass(frozen=True, slots=True)
class Upid:
    node: str
    pid: int
    process_start: int
    start_time: int
    task_type: str
    task_id: str
    user: str

    def __post_init__(self) -> None:
        for name, value in (
            ("pid", self.pid),
            ("process_start", self.process_start),
            ("start_time", self.start_time),
        ):
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"{name} is outside the 32-bit UPID range")
        if not self.node or ":" in self.node or not self.task_type or ":" in self.task_type:
            raise ValueError("invalid UPID node or task type")
        if ":" in self.task_id or not self.user or ":" in self.user:
            raise ValueError("invalid UPID task id or user")

    def __str__(self) -> str:
        return (
            f"UPID:{self.node}:{self.pid:08X}:{self.process_start:08X}:"
            f"{self.start_time:08X}:{self.task_type}:{self.task_id}:{self.user}:"
        )

    @classmethod
    def parse(cls, value: str) -> Upid:
        match = UPID_RE.fullmatch(value)
        if match is None:
            raise ValueError("invalid UPID")
        values = match.groupdict()
        return cls(
            node=values["node"],
            pid=int(values["pid"], 16),
            process_start=int(values["pstart"], 16),
            start_time=int(values["start"], 16),
            task_type=values["type"],
            task_id=values["task_id"],
            user=values["user"],
        )

    @classmethod
    def allocate(cls, node: str, task_type: str, task_id: str, user: str) -> Upid:
        """Build a collision-resistant UPID for a new task."""

        return cls(
            node=node,
            pid=secrets.randbits(32),
            process_start=secrets.randbits(32),
            start_time=int(time.time()) & 0xFFFFFFFF,
            task_type=task_type,
            task_id=str(task_id),
            user=user,
        )
