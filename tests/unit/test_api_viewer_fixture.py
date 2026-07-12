"""Offline checks for the researched API Viewer sample."""

import hashlib
import json
from pathlib import Path
from typing import Any, cast

FIXTURES = Path(__file__).parents[1] / "fixtures" / "api-viewer"


def test_version_fixture_matches_provenance() -> None:
    fixture_path = FIXTURES / "pve-9.2.3-version.json"
    provenance_path = FIXTURES / "pve-9.2.3-version.provenance.json"

    fixture_bytes = fixture_path.read_bytes()
    fixture = cast(dict[str, Any], json.loads(fixture_bytes))
    provenance = cast(dict[str, Any], json.loads(provenance_path.read_bytes()))

    assert fixture["path"] == "/version"
    assert fixture["info"]["GET"]["method"] == "GET"
    assert hashlib.sha256(fixture_bytes).hexdigest() == provenance["fixture_sha256"]
