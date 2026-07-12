"""UPID examples and round-trip properties."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.tasks.upid import Upid

SAFE = st.from_regex(r"[a-z0-9][a-z0-9_-]{0,19}", fullmatch=True)


@given(
    node=SAFE,
    pid=st.integers(min_value=0, max_value=0xFFFFFFFF),
    process_start=st.integers(min_value=0, max_value=0xFFFFFFFF),
    start_time=st.integers(min_value=0, max_value=0xFFFFFFFF),
    task_type=SAFE,
    task_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", max_size=20),
    user=SAFE,
)
def test_upid_round_trip(
    node: str,
    pid: int,
    process_start: int,
    start_time: int,
    task_type: str,
    task_id: str,
    user: str,
) -> None:
    upid = Upid(node, pid, process_start, start_time, task_type, task_id, user)

    assert Upid.parse(str(upid)) == upid


def test_known_upid_shape() -> None:
    value = "UPID:pve1:0000002A:00000010:65A1B2C3:qmstart:100:root@pam:"

    parsed = Upid.parse(value)

    assert parsed.pid == 42
    assert parsed.task_id == "100"
    assert str(parsed) == value


@pytest.mark.parametrize("value", ["", "UPID:broken", "UPID:pve:GGGGGGGG:00000000:00000000:x::u:"])
def test_invalid_upids_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        Upid.parse(value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pid": -1},
        {"node": "bad:node"},
        {"task_id": "bad:id"},
    ],
)
def test_invalid_upid_components_are_rejected(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "node": "pve1",
        "pid": 1,
        "process_start": 1,
        "start_time": 1,
        "task_type": "test",
        "task_id": "100",
        "user": "root@pam",
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        Upid(**values)  # type: ignore[arg-type]
