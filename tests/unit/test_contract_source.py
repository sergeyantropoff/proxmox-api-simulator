"""Tests for safe API Viewer source parsing."""

import json
from pathlib import Path

import pytest

from app.contracts.source import ApiViewerParser, LocalFileImporter, SourceError

FIXTURE = Path(__file__).parents[1] / "fixtures" / "api-viewer" / "pve-9.2.3-version.json"


def test_parse_saved_json_fixture() -> None:
    parsed = ApiViewerParser().parse(FIXTURE.read_bytes())

    assert parsed.nodes[0]["path"] == "/version"
    assert parsed.warnings == ()


def test_extract_api_schema_without_executing_trailing_javascript() -> None:
    raw = b'const apiSchema = [{"path":"/x]y","leaf":1}]; throw new Error("no");'

    parsed = ApiViewerParser().parse(raw)

    assert parsed.nodes[0]["path"] == "/x]y"


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"", "empty"),
        (b"const other = [];", "not found"),
        (b"const apiSchema = [", "truncated"),
        (b"const apiSchema = [}];", "invalid"),
        (b"42", "not found"),
    ],
)
def test_reject_malformed_sources(raw: bytes, message: str) -> None:
    with pytest.raises(SourceError, match=message):
        ApiViewerParser().parse(raw)


def test_preserve_unknown_fields_and_warn() -> None:
    raw = json.dumps([{"path": "/version", "future": {"enabled": True}}]).encode()

    parsed = ApiViewerParser().parse(raw)

    assert parsed.nodes[0]["future"] == {"enabled": True}
    assert parsed.warnings[0].code == "unknown-node-field"
    assert parsed.warnings[0].path == "/0/future"


async def test_local_file_importer(tmp_path: Path) -> None:
    artifact = tmp_path / "api.json"
    artifact.write_bytes(b"[]")

    assert await LocalFileImporter(artifact).load() == b"[]"
