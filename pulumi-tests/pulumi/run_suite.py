#!/usr/bin/env python3
"""Run Pulumi HX suite: full contract surface (majors 6–9) + lifecycle scenarios."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROGRAMS = HERE / "programs"
REPORTS = HERE / "reports"

# Ensure pvelib imports work when invoked as a script.
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))


def run_lifecycle(*, smoke: bool) -> dict[str, Any]:
    from pulumi import automation as auto

    program_dir = PROGRAMS / "lifecycle"
    stack_name = f"hxlife{os.getpid()}{int(time.time())}"
    os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "hx-test-passphrase")
    state = HERE / ".pulumi-state"
    state.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PULUMI_BACKEND_URL", f"file://{state}")

    env = {
        **os.environ,
        "PYTHONPATH": str(HERE)
        + os.pathsep
        + str(ROOT)
        + os.pathsep
        + os.environ.get("PYTHONPATH", ""),
    }
    if smoke:
        env["SMOKE_ONLY"] = "1"

    started = time.monotonic()
    stack = None
    try:
        # Pass env (incl. PULUMI_BACKEND_URL) at workspace creation — assigning
        # workspace.env_vars after create_or_select_stack can lose stack selection.
        stack = auto.create_or_select_stack(
            stack_name=stack_name,
            work_dir=str(program_dir),
            opts=auto.LocalWorkspaceOptions(env_vars=env),
        )
        stack.set_config("smoke", auto.ConfigValue(value="1" if smoke else "0"))
        up_result = stack.up(on_output=lambda _: None)
        outputs = stack.outputs()
        if not outputs and getattr(up_result, "outputs", None):
            outputs = up_result.outputs
        ids: list[str] = []
        sid_out = outputs.get("scenario_ids")
        if sid_out is not None and getattr(sid_out, "value", None) is not None:
            value = sid_out.value
            if isinstance(value, list):
                ids = [str(x) for x in value]
        # Also require inventory / vm exports to be non-empty when present.
        for key in ("inventory", "vm"):
            item = outputs.get(key)
            if item is None or getattr(item, "value", None) in (None, "", {}, []):
                raise RuntimeError(f"lifecycle export {key!r} is empty")
        stack.destroy(on_output=lambda _: None)
        try:
            stack.workspace.remove_stack(stack_name)
        except Exception:
            pass
        elapsed = time.monotonic() - started
        if ids:
            return {
                "ok": True,
                "scenarios": [{"id": sid, "ok": True, "error": "", "time": elapsed / max(len(ids), 1)} for sid in ids],
                "time": elapsed,
            }
        return {
            "ok": True,
            "scenarios": [{"id": "lifecycle", "ok": True, "error": "", "time": elapsed}],
            "time": elapsed,
        }
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        stderr = getattr(exc, "stderr", None)
        if stderr:
            detail = f"{detail}\n{stderr}"
        if stack is not None:
            try:
                stack.destroy(on_output=lambda _: None)
            except Exception:
                pass
            try:
                stack.workspace.remove_stack(stack_name)
            except Exception:
                pass
        return {
            "ok": False,
            "scenarios": [
                {
                    "id": "lifecycle",
                    "ok": False,
                    "error": detail,
                    "time": time.monotonic() - started,
                }
            ],
            "time": time.monotonic() - started,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Major 9 surface + short lifecycle")
    parser.add_argument(
        "--skip-lifecycle",
        action="store_true",
        help="Only run the contract surface probe",
    )
    parser.add_argument(
        "--skip-surface",
        action="store_true",
        help="Only run lifecycle scenarios",
    )
    parser.add_argument(
        "--majors",
        default="",
        help="Comma-separated majors (default: 6,7,8,9 or 9 with --smoke)",
    )
    parser.add_argument("--report-html", default=str(REPORTS / "report.html"))
    parser.add_argument("--report-json", default=str(REPORTS / "results.json"))
    parser.add_argument("--report-junit", default=str(REPORTS / "junit.xml"))
    args = parser.parse_args()

    from pvelib.surface import run_surface
    from report import write_html, write_json, write_junit

    started = time.monotonic()
    if args.majors.strip():
        majors = tuple(int(part.strip()) for part in args.majors.split(",") if part.strip())
    elif args.smoke:
        majors = (9,)
    else:
        majors = (6, 7, 8, 9)

    surface: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []

    # Lifecycle first: surface probing mutates shared auth/config state.
    if not args.skip_lifecycle:
        print("Lifecycle scenarios …")
        life = run_lifecycle(smoke=args.smoke)
        scenarios = life["scenarios"]
        for item in scenarios:
            print(f"  {'ok' if item['ok'] else 'FAIL'} {item['id']}")
            if not item["ok"]:
                print(item["error"][-2000:], file=sys.stderr)

    if not args.skip_surface:
        print(f"Surface probe majors={list(majors)} …")
        surface = run_surface(majors=majors)
        for item in surface:
            status = "ok" if item["ok"] else "FAIL"
            print(
                f"  {status} PVE {item['version']}: declared={item['declared']} "
                f"probed={item['probed']} critical={item['failure_count']} "
                f"2xx={item['success_2xx']} 4xx={item['client_4xx']}"
            )
            if not item["ok"]:
                for fail in (item.get("failures") or [])[:10]:
                    print(
                        f"    {fail.get('verb')} {fail.get('path')} "
                        f"-> {fail.get('bucket')} {fail.get('status', fail.get('error', ''))}",
                        file=sys.stderr,
                    )

    # Slim JSON: drop full method lists (keep failures)
    surface_slim = []
    for item in surface:
        slim = dict(item)
        slim.pop("methods", None)
        surface_slim.append(slim)

    coverage = build_coverage(surface_slim, majors=list(majors))
    if surface_slim:
        majs = coverage["majors"]
        if len(majs) >= 2:
            major_label = f"{majs[0]}–{majs[-1]}"
        elif majs:
            major_label = str(majs[0])
        else:
            major_label = "none"
        print(
            f"Coverage: {coverage['probed_total']}/{coverage['declared_total']} "
            f"methods across majors {major_label} "
            f"(critical={coverage['critical_total']})"
        )

    # Explicit gate: every major must have declared==probed and zero critical failures.
    surface_ok = all(
        int(m.get("declared") or 0) == int(m.get("probed") or 0)
        and int(m.get("failure_count") or 0) == 0
        and bool(m.get("ok"))
        for m in surface_slim
    )
    lifecycle_ok = all(bool(s.get("ok")) for s in scenarios)
    coverage_ok = bool(coverage.get("ok")) if surface_slim else True
    suite_ok = surface_ok and lifecycle_ok and coverage_ok

    payload = {
        "ok": suite_ok,
        "elapsed": time.monotonic() - started,
        "smoke": args.smoke,
        "majors": list(majors),
        "coverage": coverage,
        "surface": surface_slim,
        "scenarios": scenarios,
    }

    write_json(payload, Path(args.report_json))
    write_html(payload, Path(args.report_html))
    write_junit(payload, Path(args.report_junit))

    print(
        f"Suite {'PASS' if payload['ok'] else 'FAIL'} in {payload['elapsed']:.1f}s; "
        f"html={args.report_html} json={args.report_json}"
    )
    return 0 if payload["ok"] else 1


def build_coverage(
    surface: list[dict[str, Any]],
    *,
    majors: list[int] | None = None,
) -> dict[str, Any]:
    """Aggregate declared/probed/critical counts across surface majors."""
    by_major: list[dict[str, Any]] = []
    for item in surface:
        declared = int(item.get("declared") or 0)
        probed = int(item.get("probed") or 0)
        critical = int(item.get("failure_count") or 0)
        by_major.append(
            {
                "major": item.get("major"),
                "version": item.get("version"),
                "declared": declared,
                "probed": probed,
                "critical": critical,
                "complete": declared == probed and critical == 0,
            }
        )
    declared_total = sum(m["declared"] for m in by_major)
    probed_total = sum(m["probed"] for m in by_major)
    critical_total = sum(m["critical"] for m in by_major)
    major_ids = [m["major"] for m in by_major if m.get("major") is not None]
    if not major_ids and majors:
        major_ids = list(majors)
    complete = bool(by_major) and all(m["complete"] for m in by_major)
    return {
        "majors": major_ids,
        "declared_total": declared_total,
        "probed_total": probed_total,
        "critical_total": critical_total,
        "by_major": by_major,
        "ok": complete,
    }


if __name__ == "__main__":
    raise SystemExit(main())
