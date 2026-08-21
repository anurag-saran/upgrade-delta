#!/usr/bin/env python3
"""Render scorecard.json as a short CAB PR comment.

CAB-facing: grade, path, lane, CVEs, test outcome. Deep reachability /
call-chain / unrated package dumps stay on scorecard.html — not here.
Kept in sync with the Tekton upgrade-delta-pr-comment Task.
"""
import argparse
import json
import os
import sys

BADGE = {"A": "🟢", "B": "🟡", "C": "🟡", "D": "🔴", "F": "🔴"}


def _display_name(lib):
    return lib.get("gav") or lib.get("library") or "?"


def _short_path(rec, gav=None):
    old, new = rec.get("old") or "?", rec.get("new") or "?"
    # Prefer artifactId-only in the path cell when GAV is long.
    art = (gav or "").rsplit(":", 1)[-1] if gav else ""
    if art and ":" not in old and ":" not in new:
        return f"`{old}` → `{new}`"
    return f"`{old}` → `{new}`"


def _load(path):
    if path and os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return None


def _load_demo_grades(scorecard=None):
    """Catalog context from scorecard payload or catalogs/lightwell-demo-grades.json."""
    if scorecard and scorecard.get("catalog_context"):
        return scorecard["catalog_context"]
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "catalogs", "lightwell-demo-grades.json"),
        os.path.join(here, "..", "..", "catalogs", "lightwell-demo-grades.json"),
        os.path.join(here, "..", "catalogs", "lightwell-demo-grades.json"),
        os.path.join("catalogs", "lightwell-demo-grades.json"),
        os.path.join(".upgrade-delta", "catalogs", "lightwell-demo-grades.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _catalog_context_md(scorecard):
    """Compact remidiated + validated tables for the PR (not this change's grade)."""
    ctx = _load_demo_grades(scorecard)
    if not ctx:
        return []
    rem = ctx.get("remediated_same_base") or []
    val = ctx.get("validated_ranked") or []
    if not rem and not val:
        return []
    lines = [
        "",
        "### Lightwell catalog context *(not this PR's grade)*",
        "",
        "_" + (ctx.get("note") or
               "Same-base remidiated / validated corpus — community vs `.rhlw`.") + "_",
    ]
    if rem:
        lines += [
            "",
            "| Library | Pair | Grade |",
            "|---|---|---|",
        ]
        for row in rem:
            grade = row.get("grade") or "?"
            flag = row.get("flag") or ""
            shown = f"{BADGE.get(grade, '⚪')} {grade}" + (f" ({flag})" if flag else "")
            lines.append(
                f"| **`{row.get('library') or '?'}`** | "
                f"`{row.get('old') or '?'}` → `{row.get('new') or '?'}` | "
                f"{shown} |"
            )
    if val:
        lines += [
            "",
            f"*{ctx.get('validated_summary') or 'Validated catalog: all 7 = B (none A / C / F).'}*",
            "",
            "| Rank | Library | Churn | Flag for “just a rebuild” |",
            "|---:|---|---:|---|",
        ]
        for row in val:
            lines.append(
                f"| {row.get('rank') or ''} | **`{row.get('library') or '?'}`** | "
                f"{row.get('churn_pct', '?')}% | {row.get('flag') or ''} |"
            )
    lines.append("")
    lines.append("Full tables: `scorecard.html` → *Lightwell catalog grades*.")
    return lines


def render(scorecard, *, selection=None, test_results=None, cab_signoff=None):
    r = scorecard
    p = r["project"]
    g = p["headline_grade"] or "—"
    lines = [
        f"## {BADGE.get(g, '⚪')} upgrade-delta: project grade **{g}**",
        f"*{p.get('headline_note') or 'graded upgrade'}* — "
        f"**{p.get('rated_libraries', 0)}** libraries in this change",
    ]
    if p.get("worst_without_best_path") and p["worst_without_best_path"] != g:
        lines.append(
            f"> Without best remediation paths: **{p['worst_without_best_path']}** "
            f"(gap = value of maintained backports)."
        )

    libs = r.get("libraries") or []
    if libs:
        lines += [
            "",
            "| Dependency | Version | Grade | Lane | CVEs fixed |",
            "|---|---|---|---|---|",
        ]
        for l in libs:
            rec = l["recommended"]
            rt = rec["rating"]
            grade = rt.get("effective_grade") or rt["grade"]
            shown = (
                f"{rt['grade']} → {rt['effective_grade']} ✍️"
                if rt.get("effective_grade")
                else rt["grade"]
            )
            label = _display_name(l)
            # Short artifact name for CAB; full GAV is on scorecard.html
            short = label.rsplit(":", 1)[-1] if ":" in label else label
            name = (
                f"↳ `{short}` *(via {l['parent']})*"
                if l.get("transitive")
                else f"**`{short}`**"
            )
            cves = ", ".join(f"`{c}`" for c in (rec.get("cves_fixed") or [])) or "—"
            lines.append(
                f"| {name} | {_short_path(rec, l.get('gav'))} | "
                f"{BADGE.get(grade, '⚪')} {shown} | {rt['lane']} | {cves} |"
            )
    else:
        lines += ["", "_No Lightwell adoption detected in this change — nothing to grade._"]

    lines += _catalog_context_md(r)

    if selection:
        t = selection["totals"]
        mode = selection.get("mode") or ""
        selected = selection.get("selected") or []
        mandatory = (selection.get("mandatory") or {}).get("appended") or []
        skipped = selection.get("skipped") or []
        if mode == "REACHABILITY_ONLY" or (t.get("suite") or 0) == 0:
            lines += [
                "",
                "### Validation — reachability only",
                "- **No test suite present** — grade based on **reachability alone** "
                "(call-site / API intersection). Detail: `scorecard.html`.",
                "- **Compensating control:** progressive canary (see `deploy-gate.json`).",
            ]
            note = selection.get("note")
            if note:
                lines.append(f"- _{note}_")
        else:
            lines += ["", f"### Tests — {t['final']} of {t['suite']} classes"]
            for s in selected:
                lines.append(f"- ✅ **{s['test']}**")
            for m in mandatory:
                lines.append(f"- 🔒 **{m}** *(upgrade-gate)*")
            if skipped:
                names = ", ".join(s["test"] for s in skipped[:8])
                more = f" (+{len(skipped) - 8} more)" if len(skipped) > 8 else ""
                lines.append(f"- ⚪ skipped: {names}{more}")

    if test_results:
        lines += ["", "### Results"]
        grade = p.get("headline_grade") or ""
        status = test_results.get("status") or ""
        if status == "reachability_only":
            lines.append(
                "- Reachability-only — **no Surefire run** (not a green pass). "
                "Canary is the compensating control."
            )
        elif status != "ran":
            lines.append("- Tests were **not run** in this pipeline.")
        elif test_results.get("methods_failed"):
            fails = test_results.get("failed_names") or []
            who = (" — `" + "`, `".join(fails[:5]) + "`") if fails else ""
            lines.append(
                f"- ❌ **{test_results.get('methods_failed')} failed** / "
                f"{test_results.get('methods_passed', 0)} passed{who}"
            )
        else:
            caveat = ""
            if grade in ("F", "D"):
                caveat = f" — does **not** clear project **{grade}**"
            lines.append(
                f"- ✅ **All passed** — {test_results.get('methods_passed', 0)} methods{caveat}"
            )

    lines += [
        "",
        "---",
    ]
    if cab_signoff and cab_signoff.get("approved"):
        mode = cab_signoff.get("mode") or "?"
        if mode == "auto":
            lines.append(
                f"**CAB:** auto-approved (`{cab_signoff.get('grade', g)}`) — "
                f"no human in the loop. Signoff `{cab_signoff.get('timestamp', '')}` "
                f"· scorecard `{cab_signoff.get('scorecard_sha256_16', '')}`."
            )
            if (test_results or {}).get("status") == "reachability_only" or (
                selection and (
                    selection.get("mode") == "REACHABILITY_ONLY"
                    or (selection.get("totals") or {}).get("suite") == 0
                )
            ):
                lines.append(
                    "_Auto-CAB on this path is reachability + canary, not regression-suite proof._"
                )
        else:
            lines.append(
                f"**CAB:** human-approved by `{cab_signoff.get('approver', '?')}` "
                f"at `{cab_signoff.get('timestamp', '')}` "
                f"(grade `{cab_signoff.get('grade', g)}`)."
            )
    else:
        lines.append(
            "**CAB:** A/B auto-approve with audit log; C needs human CAB; "
            "grade ≥ D fails the pipeline (`fail-on`). "
            "Full call-site / reachability detail: `scorecard.html`."
        )
    lines.append("Full call-site / reachability detail: `scorecard.html`.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scorecard")
    ap.add_argument("out", nargs="?", default="pr-comment.md")
    ap.add_argument("--selection", help="selection-report.json (test plan)")
    ap.add_argument("--test-results", help="test-results.json (pass/fail)")
    ap.add_argument("--cab-signoff", help="cab-signoff.json (auto or human)")
    args = ap.parse_args(argv)
    body = render(
        json.load(open(args.scorecard)),
        selection=_load(args.selection),
        test_results=_load(args.test_results),
        cab_signoff=_load(args.cab_signoff),
    )
    open(args.out, "w").write(body)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
