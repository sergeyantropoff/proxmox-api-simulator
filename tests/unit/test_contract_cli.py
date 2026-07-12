"""Offline command workflows for contract management."""

import argparse
import json
from pathlib import Path

import pytest

from app.contracts.cli import parser, run

FIXTURE = Path(__file__).parents[1] / "fixtures" / "api-viewer" / "pve-9.2.3-version.json"


async def test_validate_command_reports_source_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = argparse.Namespace(command="validate", store=tmp_path, file=FIXTURE)

    assert await run(arguments) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"nodes": 1, "warnings": 0}


async def test_local_import_list_and_show(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import_arguments = argparse.Namespace(
        command="import",
        store=tmp_path,
        file=FIXTURE,
        url=None,
        version="9.2.3",
    )
    assert await run(import_arguments) == 0
    revision = Path(capsys.readouterr().out.strip()).name

    assert await run(argparse.Namespace(command="list", store=tmp_path)) == 0
    assert capsys.readouterr().out.strip() == revision

    assert await run(argparse.Namespace(command="show", store=tmp_path, revision=revision)) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["source_version"] == "9.2.3"
    assert manifest["snapshot_sha256"] == revision


def test_cli_parser_accepts_local_import() -> None:
    arguments = parser().parse_args(
        ["--store", "saved", "import", "--file", str(FIXTURE), "--version", "9.2.3"]
    )

    assert arguments.command == "import"
    assert arguments.store == Path("saved")
