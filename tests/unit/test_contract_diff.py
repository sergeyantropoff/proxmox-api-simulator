"""Semantic contract diff classification and rendering tests."""

import json
from datetime import UTC, datetime

from app.contracts.diff import (
    Severity,
    compare_snapshots,
    has_breaking_changes,
    render_html,
    render_json,
    render_markdown,
    render_text,
)
from app.contracts.model import Method, PathContract, Schema, Snapshot


def snapshot(paths: tuple[PathContract, ...]) -> Snapshot:
    return Snapshot(
        source_version="test",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_sha256="0" * 64,
        paths=paths,
        path_count=len(paths),
        method_count=sum(len(path.methods) for path in paths),
    )


def method(description: str = "old", returns: Schema | None = None) -> Method:
    return Method(
        verb="GET",
        name="read",
        description=description,
        returns=returns or Schema(type="string"),
        checksum="1" * 64,
    )


def test_classifies_added_removed_and_changed_contracts() -> None:
    before = snapshot(
        (
            PathContract(path="/removed", methods=(method(),)),
            PathContract(path="/version", methods=(method(),)),
        )
    )
    after = snapshot(
        (
            PathContract(path="/added", methods=(method(),)),
            PathContract(
                path="/version",
                methods=(method("new", Schema(type="integer", minimum=1)),),
            ),
        )
    )

    changes = compare_snapshots(before, after)

    assert changes == tuple(sorted(changes))
    assert {change.category for change in changes} >= {
        "path",
        "method",
        "documentation",
        "schema",
        "constraint",
    }
    assert has_breaking_changes(changes)
    assert any(change.severity is Severity.NON_BREAKING for change in changes)


def test_renderers_are_stable_and_escape_html() -> None:
    before = snapshot((PathContract(path="/<old>", methods=(method(),)),))
    after = snapshot(())
    changes = compare_snapshots(before, after)

    assert render_text(changes).startswith("breaking:")
    assert "| breaking |" in render_markdown(changes)
    assert "&lt;old&gt;" in render_html(changes)
    decoded = json.loads(render_json(changes))
    assert decoded[0]["severity"] == "breaking"
    assert render_json(changes) == render_json(changes)


def test_no_changes_has_clean_ci_policy() -> None:
    value = snapshot((PathContract(path="/version", methods=(method(),)),))

    assert compare_snapshots(value, value) == ()
    assert not has_breaking_changes(())
