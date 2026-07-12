"""Safe source adapters for Proxmox API Viewer artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast


class SourceError(ValueError):
    """Raised when an API source cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """A recoverable variation found in a source artifact."""

    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ParsedSource:
    """Parsed source tree with non-fatal diagnostics."""

    nodes: tuple[dict[str, Any], ...]
    warnings: tuple[ParseWarning, ...] = ()


class SourceImporter(Protocol):
    """Asynchronous boundary for obtaining source artifact bytes."""

    async def load(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class LocalFileImporter:
    """Load an artifact from a caller-selected local path."""

    path: Path

    async def load(self) -> bytes:
        return self.path.read_bytes()


class ApiViewerParser:
    """Extract the JSON-compatible ``apiSchema`` value without executing JS."""

    declaration = b"const apiSchema"
    known_node_fields = frozenset({"children", "info", "leaf", "path", "text"})

    def parse(self, raw: bytes) -> ParsedSource:
        if not raw.strip():
            raise SourceError("source artifact is empty")

        payload = self._extract_payload(raw)
        try:
            decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceError(f"invalid apiSchema JSON: {exc}") from exc

        if isinstance(decoded, Mapping):
            raw_nodes = [decoded]
        elif isinstance(decoded, list):
            raw_nodes = decoded
        else:
            raise SourceError("apiSchema must be an object or array of objects")

        nodes: list[dict[str, Any]] = []
        warnings: list[ParseWarning] = []
        for index, value in enumerate(raw_nodes):
            if not isinstance(value, Mapping):
                raise SourceError(f"apiSchema node /{index} must be an object")
            node = cast(dict[str, Any], dict(value))
            nodes.append(node)
            self._inspect_node(node, f"/{index}", warnings)
        return ParsedSource(tuple(nodes), tuple(warnings))

    def _extract_payload(self, raw: bytes) -> bytes:
        stripped = raw.strip()
        if stripped.startswith((b"[", b"{")):
            return stripped

        declaration_at = raw.find(self.declaration)
        if declaration_at < 0:
            raise SourceError("apiSchema declaration was not found")
        equals_at = raw.find(b"=", declaration_at + len(self.declaration))
        if equals_at < 0:
            raise SourceError("apiSchema declaration has no assignment")

        start = self._next_non_space(raw, equals_at + 1)
        if start >= len(raw) or raw[start] not in b"[{":
            raise SourceError("apiSchema assignment must start with an array or object")
        end = self._matching_end(raw, start)
        return raw[start : end + 1]

    @staticmethod
    def _next_non_space(raw: bytes, start: int) -> int:
        while start < len(raw) and raw[start] in b" \t\r\n":
            start += 1
        return start

    @staticmethod
    def _matching_end(raw: bytes, start: int) -> int:
        opening = raw[start]
        closing = ord("]") if opening == ord("[") else ord("}")
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            byte = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif byte == ord("\\"):
                    escaped = True
                elif byte == ord('"'):
                    in_string = False
                continue
            if byte == ord('"'):
                in_string = True
            elif byte == opening:
                depth += 1
            elif byte == closing:
                depth -= 1
                if depth == 0:
                    return index
        raise SourceError("apiSchema assignment is truncated")

    def _inspect_node(
        self, node: Mapping[str, Any], path: str, warnings: list[ParseWarning]
    ) -> None:
        for field in sorted(node.keys() - self.known_node_fields):
            warnings.append(
                ParseWarning("unknown-node-field", f"{path}/{field}", "field was preserved")
            )
        children = node.get("children", [])
        if not isinstance(children, list):
            warnings.append(
                ParseWarning("invalid-children", f"{path}/children", "expected an array")
            )
            return
        for index, child in enumerate(children):
            child_path = f"{path}/children/{index}"
            if isinstance(child, Mapping):
                self._inspect_node(child, child_path, warnings)
            else:
                warnings.append(ParseWarning("invalid-child", child_path, "expected an object"))
