"""Immutable filesystem storage for imported contract revisions."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.contracts.model import Manifest, Snapshot, canonical_json


@dataclass(frozen=True, slots=True)
class RevisionStore:
    root: Path

    def save(self, raw: bytes, snapshot: Snapshot, manifest: Manifest) -> Path:
        revision = self.root / manifest.snapshot_sha256
        if revision.exists():
            return revision
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".import-", dir=self.root))
        try:
            self._write(temporary / "raw.js", raw)
            self._write(temporary / "snapshot.json", snapshot.canonical_bytes())
            self._write(temporary / "manifest.json", canonical_json(manifest))
            os.replace(temporary, revision)
        except BaseException:
            for child in temporary.iterdir():
                child.unlink()
            temporary.rmdir()
            raise
        return revision

    def list(self) -> tuple[str, ...]:
        if not self.root.exists():
            return ()
        return tuple(sorted(path.name for path in self.root.iterdir() if path.is_dir()))

    def manifest(self, revision: str) -> Manifest:
        return Manifest.model_validate_json((self.root / revision / "manifest.json").read_bytes())

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
