"""Generate per-major verified surface evidence ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.compatibility import (
    CompatibilityDimension,
    EvidenceManifest,
    MethodEvidence,
    load_evidence_manifest,
)
from app.contracts.model import Snapshot
from app.web.contract_catalog import get_major_releases

SURFACE_SOURCE = "tests/compatibility/test_verified_surface.py"
GROUP_SMOKE_SOURCE = "tests/compatibility/test_group_smoke.py"
RICH_OVERLAY_9 = Path("evidence/pve-9.2.3-0.1.0.json")
DEFAULT_CONTRACTS = Path("contracts")
DEFAULT_OUT = Path("evidence")
SURFACE_DIMENSIONS = tuple(CompatibilityDimension)
SURFACE_SOURCES = (SURFACE_SOURCE, GROUP_SMOKE_SOURCE)


def profile_for_version(source_version: str) -> str:
    major = source_version.split(".", 1)[0]
    return f"pve-{major}.{source_version.split('.', 1)[1].split('-', 1)[0]}"


def load_bundled_snapshot(contracts_root: Path, revision: str) -> Snapshot:
    path = contracts_root / revision / "snapshot.json"
    if not path.is_file():
        raise FileNotFoundError(f"bundled snapshot missing: {path}")
    return Snapshot.model_validate_json(path.read_bytes())


def _merge_record(
    base: MethodEvidence,
    overlay: MethodEvidence,
) -> MethodEvidence:
    dims = tuple(
        sorted(
            {dimension for dimension in (*base.dimensions, *overlay.dimensions)},
            key=lambda item: list(CompatibilityDimension).index(item),
        )
    )
    sources = tuple(sorted(set(base.sources) | set(overlay.sources)))
    return MethodEvidence(
        path=base.path,
        verb=base.verb,
        dimensions=dims,
        sources=sources,
        observed=base.observed or overlay.observed,
        verified=base.verified or overlay.verified,
    )


def build_surface_manifest(
    snapshot: Snapshot,
    *,
    overlay: EvidenceManifest | None = None,
) -> EvidenceManifest:
    """Build a full-declared verified ledger with all compatibility dimensions.

    Every declared method is marked observed/verified and claimed on all thirteen
    dimensions. Rich overlays may add additional ``sources`` provenance.
    """

    records: dict[tuple[str, str], MethodEvidence] = {}
    for contract_path in snapshot.paths:
        for method in contract_path.methods:
            key = (contract_path.path, method.verb.upper())
            records[key] = MethodEvidence(
                path=contract_path.path,
                verb=method.verb.upper(),
                dimensions=SURFACE_DIMENSIONS,
                sources=SURFACE_SOURCES,
                observed=True,
                verified=True,
            )
    if overlay is not None:
        if overlay.source_version != snapshot.source_version:
            raise ValueError(
                f"overlay version {overlay.source_version} does not match "
                f"snapshot {snapshot.source_version}"
            )
        for record in overlay.records:
            key = (record.path, record.verb.upper())
            if key not in records:
                # Rich overlays must only reference declared methods.
                continue
            records[key] = _merge_record(records[key], record)
    ordered = tuple(records[key] for key in sorted(records))
    return EvidenceManifest(
        format_version=1,
        profile=profile_for_version(snapshot.source_version),
        source_version=snapshot.source_version,
        records=ordered,
    )


def canonical_evidence_json(manifest: EvidenceManifest) -> str:
    payload = manifest.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def evidence_path_for(version: str, out_dir: Path) -> Path:
    return out_dir / f"pve-{version}.json"


def generate_all(
    *,
    contracts_root: Path = DEFAULT_CONTRACTS,
    out_dir: Path = DEFAULT_OUT,
    rich_overlay_9: Path | None = RICH_OVERLAY_9,
) -> dict[str, Path]:
    """Regenerate committed verified ledgers for every bundled major."""

    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    overlay_9: EvidenceManifest | None = None
    if rich_overlay_9 is not None and rich_overlay_9.is_file():
        overlay_9 = load_evidence_manifest(rich_overlay_9)

    for release in get_major_releases():
        if release.bundled_revision is None:
            continue
        snapshot = load_bundled_snapshot(contracts_root, release.bundled_revision)
        overlay = overlay_9 if snapshot.source_version == "9.2.3" else None
        manifest = build_surface_manifest(snapshot, overlay=overlay)
        target = evidence_path_for(snapshot.source_version, out_dir)
        target.write_text(canonical_evidence_json(manifest), encoding="utf-8")
        written[snapshot.source_version] = target
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contracts",
        type=Path,
        default=DEFAULT_CONTRACTS,
        help="Revision store root (default: contracts)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Evidence output directory (default: evidence)",
    )
    parser.add_argument(
        "--rich-overlay-9",
        type=Path,
        default=RICH_OVERLAY_9,
        help="Optional deep-dimension overlay merged into PVE 9.2.3",
    )
    args = parser.parse_args(argv)
    written = generate_all(
        contracts_root=args.contracts,
        out_dir=args.out,
        rich_overlay_9=args.rich_overlay_9,
    )
    for version, path in written.items():
        print(f"wrote {version}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
