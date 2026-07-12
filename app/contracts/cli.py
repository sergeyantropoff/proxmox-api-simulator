"""Command-line interface for contract imports and inspection."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.contracts.importer import RemoteSourceImporter
from app.contracts.normalize import normalize_snapshot
from app.contracts.source import ApiViewerParser, LocalFileImporter, SourceImporter
from app.contracts.store import RevisionStore


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="proxmox-api-contract")
    root.add_argument("--store", type=Path, default=Path("contracts"))
    commands = root.add_subparsers(dest="command", required=True)
    import_command = commands.add_parser("import")
    source = import_command.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--url")
    import_command.add_argument("--version", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("file", type=Path)
    commands.add_parser("list")
    show = commands.add_parser("show")
    show.add_argument("revision")
    return root


async def run(arguments: argparse.Namespace) -> int:
    store = RevisionStore(arguments.store)
    if arguments.command == "list":
        for revision in store.list():
            print(revision)
        return 0
    if arguments.command == "show":
        print(json.dumps(store.manifest(arguments.revision).model_dump(mode="json"), indent=2))
        return 0
    if arguments.command == "validate":
        parsed = ApiViewerParser().parse(arguments.file.read_bytes())
        print(json.dumps({"nodes": len(parsed.nodes), "warnings": len(parsed.warnings)}))
        return 0
    importer: SourceImporter
    if arguments.file is not None:
        importer = LocalFileImporter(arguments.file)
    else:
        importer = RemoteSourceImporter(arguments.url)
    raw = await importer.load()
    parsed = ApiViewerParser().parse(raw)
    snapshot, manifest = normalize_snapshot(
        parsed, raw=raw, source_version=arguments.version, retrieved_at=datetime.now(UTC)
    )
    print(store.save(raw, snapshot, manifest))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run(parser().parse_args())))
