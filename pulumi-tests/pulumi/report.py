"""Render HTML and optional JUnit reports for the Pulumi HX suite."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ElementTree, SubElement


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Drop per-method lists from majors for a lighter default JSON? Keep full for debugging.
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_junit(payload: dict[str, Any], path: Path) -> None:
    surface = payload.get("surface") or []
    scenarios = payload.get("scenarios") or []
    cases: list[dict[str, Any]] = []
    for major in surface:
        cases.append(
            {
                "classname": "surface",
                "name": f"PVE {major.get('version')} major={major.get('major')}",
                "time": major.get("time") or 0,
                "ok": bool(major.get("ok")),
                "error": _surface_error(major),
            }
        )
    for item in scenarios:
        cases.append(
            {
                "classname": "lifecycle",
                "name": item.get("id") or item.get("name") or "lifecycle",
                "time": item.get("time") or 0,
                "ok": bool(item.get("ok")),
                "error": item.get("error") or "",
            }
        )

    suite = Element(
        "testsuite",
        name="pulumi-hx",
        tests=str(len(cases)),
        failures=str(sum(1 for c in cases if not c["ok"])),
        time=f"{sum(float(c['time']) for c in cases):.3f}",
    )
    for item in cases:
        case = SubElement(
            suite,
            "testcase",
            classname=str(item["classname"]),
            name=str(item["name"]),
            time=f"{float(item['time']):.3f}",
        )
        if not item["ok"]:
            failure = SubElement(case, "failure", message=str(item["error"])[:500])
            failure.text = str(item["error"])
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _surface_error(major: dict[str, Any]) -> str:
    fails = major.get("failures") or []
    if not fails:
        return ""
    parts = [
        f"{f.get('verb')} {f.get('path')} -> {f.get('bucket')} {f.get('status', '')}"
        for f in fails[:20]
    ]
    return f"{len(fails)} critical: " + "; ".join(parts)


def _verb_histogram_rows(surface: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for major in surface:
        histogram = major.get("verb_histogram") or {}
        if not histogram:
            # Fall back to by_verb totals when slim payload lacks histogram.
            by_verb = major.get("by_verb") or {}
            histogram = {
                verb: {"total": sum(buckets.values()), "buckets": buckets}
                for verb, buckets in by_verb.items()
            }
        for verb, info in sorted(histogram.items()):
            buckets = info.get("buckets") or {}
            bucket_txt = ", ".join(
                f"{name}={count}" for name, count in sorted(buckets.items()) if count
            )
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(major.get('version') or major.get('major')))}</td>"
                f"<td>{html.escape(str(verb))}</td>"
                f"<td>{html.escape(str(info.get('total') or 0))}</td>"
                f"<td><code>{html.escape(bucket_txt)}</code></td>"
                "</tr>"
            )
    return rows


def write_html(payload: dict[str, Any], path: Path) -> None:
    surface = payload.get("surface") or []
    scenarios = payload.get("scenarios") or []
    coverage = payload.get("coverage") or {}
    ok = bool(payload.get("ok"))
    elapsed = float(payload.get("elapsed") or 0)

    coverage_by_major = coverage.get("by_major") or []
    coverage_rows = []
    for item in coverage_by_major:
        complete = bool(item.get("complete"))
        coverage_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('major')))}</td>"
            f"<td>{html.escape(str(item.get('version')))}</td>"
            f"<td>{html.escape(str(item.get('declared')))}</td>"
            f"<td>{html.escape(str(item.get('probed')))}</td>"
            f"<td>{html.escape(str(item.get('critical')))}</td>"
            f"<td class='{'ok' if complete else 'fail'}'>"
            f"{'yes' if complete else 'no'}</td>"
            "</tr>"
        )
    declared_total = int(coverage.get("declared_total") or 0)
    probed_total = int(coverage.get("probed_total") or 0)
    critical_total = int(coverage.get("critical_total") or 0)
    coverage_ok = bool(coverage.get("ok")) if coverage_by_major else True
    majs = coverage.get("majors") or []
    if len(majs) >= 2:
        majors_label = f"{majs[0]}–{majs[-1]}"
    elif majs:
        majors_label = str(majs[0])
    else:
        majors_label = "—"

    surface_rows = []
    failure_rows = []
    for major in surface:
        surface_rows.append(
            "<tr>"
            f"<td>{html.escape(str(major.get('major')))}</td>"
            f"<td>{html.escape(str(major.get('version')))}</td>"
            f"<td>{html.escape(str(major.get('declared')))}</td>"
            f"<td>{html.escape(str(major.get('probed')))}</td>"
            f"<td>{html.escape(str(major.get('success_2xx')))}</td>"
            f"<td>{html.escape(str(major.get('client_4xx')))}</td>"
            f"<td class='{'ok' if major.get('ok') else 'fail'}'>"
            f"{html.escape(str(major.get('failure_count')))}</td>"
            f"<td>{float(major.get('time') or 0):.1f}s</td>"
            "</tr>"
        )
        for fail in major.get("failures") or []:
            failure_rows.append(
                "<tr>"
                f"<td>{html.escape(str(major.get('version')))}</td>"
                f"<td>{html.escape(str(fail.get('verb')))}</td>"
                f"<td><code>{html.escape(str(fail.get('path')))}</code></td>"
                f"<td>{html.escape(str(fail.get('bucket')))}</td>"
                f"<td>{html.escape(str(fail.get('status', fail.get('error', ''))))}</td>"
                f"<td><code>{html.escape(str(fail.get('body', ''))[:200])}</code></td>"
                "</tr>"
            )

    scenario_rows = []
    for item in scenarios:
        scenario_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('id') or item.get('name')))}</td>"
            f"<td class='{'ok' if item.get('ok') else 'fail'}'>"
            f"{'PASS' if item.get('ok') else 'FAIL'}</td>"
            f"<td>{float(item.get('time') or 0):.2f}s</td>"
            f"<td><code>{html.escape(str(item.get('error') or ''))}</code></td>"
            "</tr>"
        )

    status = "PASS" if ok else "FAIL"
    status_class = "ok" if ok else "fail"
    coverage_status = "complete" if coverage_ok else "incomplete"
    coverage_class = "ok" if coverage_ok else "fail"
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Pulumi HX suite report</title>
<style>
:root {{
  --bg: #0f1419; --panel: #1a222c; --text: #e7ecf1; --muted: #9aa7b5;
  --ok: #3dd68c; --fail: #ff6b6b; --line: #2a3542;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --sans: "Segoe UI", system-ui, sans-serif;
}}
body {{ margin: 0; font-family: var(--sans); background: var(--bg); color: var(--text); }}
main {{ max-width: 1100px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
h1 {{ font-size: 1.6rem; margin: 0 0 .4rem; }}
h2 {{ font-size: 1.15rem; margin: 2rem 0 .75rem; }}
p.lead {{ color: var(--muted); margin: 0 0 1.5rem; }}
.badge {{ display: inline-block; padding: .2rem .6rem; border-radius: .35rem;
  font-weight: 700; letter-spacing: .02em; }}
.badge.ok {{ background: color-mix(in srgb, var(--ok) 25%, transparent); color: var(--ok); }}
.badge.fail {{ background: color-mix(in srgb, var(--fail) 25%, transparent); color: var(--fail); }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: .75rem; margin: 1rem 0 1.5rem; }}
.card {{ background: var(--panel); border: 1px solid var(--line); border-radius: .5rem;
  padding: .9rem 1rem; }}
.card .label {{ color: var(--muted); font-size: .8rem; }}
.card .value {{ font-size: 1.35rem; font-weight: 700; margin-top: .25rem; }}
table {{ width: 100%; border-collapse: collapse; background: var(--panel);
  border: 1px solid var(--line); border-radius: .5rem; overflow: hidden; }}
th, td {{ text-align: left; padding: .55rem .7rem; border-bottom: 1px solid var(--line);
  vertical-align: top; font-size: .92rem; }}
th {{ color: var(--muted); font-weight: 600; }}
tr:last-child td {{ border-bottom: 0; }}
td.ok {{ color: var(--ok); font-weight: 600; }}
td.fail {{ color: var(--fail); font-weight: 600; }}
code {{ font-family: var(--mono); font-size: .85em; }}
.empty {{ color: var(--muted); font-style: italic; }}
</style>
</head>
<body>
<main>
  <h1>Pulumi HX suite report</h1>
  <p class="lead">Contract surface probe (PVE majors 6–9) + lifecycle scenarios</p>
  <span class="badge {status_class}">{status}</span>
  <div class="cards">
    <div class="card"><div class="label">Elapsed</div>
      <div class="value">{elapsed:.1f}s</div></div>
    <div class="card"><div class="label">Majors</div>
      <div class="value">{len(surface)}</div></div>
    <div class="card"><div class="label">Critical surface fails</div>
      <div class="value">{sum(int(m.get('failure_count') or 0) for m in surface)}</div></div>
    <div class="card"><div class="label">Scenarios</div>
      <div class="value">{sum(1 for s in scenarios if s.get('ok'))}/{len(scenarios)}</div></div>
  </div>

  <h2>Full contract coverage</h2>
  <p class="lead">
    {probed_total}/{declared_total} methods across majors {html.escape(majors_label)}
    (critical={critical_total}) —
    <span class="{coverage_class}">{coverage_status}</span>
  </p>
  <table>
    <thead><tr>
      <th>Major</th><th>Version</th><th>Declared</th><th>Probed</th>
      <th>Critical</th><th>declared==probed</th>
    </tr></thead>
    <tbody>
      {''.join(coverage_rows) or '<tr><td colspan="6" class="empty">No coverage data</td></tr>'}
      <tr>
        <td colspan="2"><strong>Total</strong></td>
        <td><strong>{declared_total}</strong></td>
        <td><strong>{probed_total}</strong></td>
        <td><strong>{critical_total}</strong></td>
        <td class="{coverage_class}"><strong>{'yes' if coverage_ok else 'no'}</strong></td>
      </tr>
    </tbody>
  </table>

  <h2>Surface by major</h2>
  <table>
    <thead><tr>
      <th>Major</th><th>Version</th><th>Declared</th><th>Probed</th>
      <th>2xx</th><th>4xx/auth</th><th>Critical</th><th>Time</th>
    </tr></thead>
    <tbody>
      {''.join(surface_rows) or '<tr><td colspan="8" class="empty">No surface results</td></tr>'}
    </tbody>
  </table>

  <h2>Verb histogram (incl. synthetic HEAD)</h2>
  <p class="lead">
    Contract verbs GET/PUT/POST/DELETE count toward coverage.
    HEAD is probed on every GET path for the matrix but is not part of declared/probed.
  </p>
  <table>
    <thead><tr>
      <th>Major</th><th>Verb</th><th>Total</th><th>Buckets</th>
    </tr></thead>
    <tbody>
      {''.join(_verb_histogram_rows(surface)) or '<tr><td colspan="4" class="empty">No histogram</td></tr>'}
    </tbody>
  </table>

  <h2>Critical surface failures</h2>
  <table>
    <thead><tr>
      <th>Version</th><th>Verb</th><th>Path</th><th>Bucket</th><th>Status</th><th>Body</th>
    </tr></thead>
    <tbody>
      {''.join(failure_rows) or '<tr><td colspan="6" class="empty">None</td></tr>'}
    </tbody>
  </table>

  <h2>Lifecycle scenarios</h2>
  <table>
    <thead><tr><th>ID</th><th>Result</th><th>Time</th><th>Error</th></tr></thead>
    <tbody>
      {''.join(scenario_rows) or '<tr><td colspan="4" class="empty">No scenarios</td></tr>'}
    </tbody>
  </table>
</main>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
