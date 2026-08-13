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


def render(scorecard, *, selection=None, test_results=None):
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

    if selection:
        t = selection["totals"]
        selected = selection.get("selected") or []
        mandatory = (selection.get("mandatory") or {}).get("appended") or []
        skipped = selection.get("skipped") or []
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
        if test_results.get("status") != "ran":
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
        "**CAB:** approve by merging. Grade ≥ D fails the pipeline. "
        "Full call-site / reachability detail: `scorecard.html`.",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scorecard")
    ap.add_argument("out", nargs="?", default="pr-comment.md")
    ap.add_argument("--selection", help="selection-report.json (test plan)")
    ap.add_argument("--test-results", help="test-results.json (pass/fail)")
    args = ap.parse_args(argv)
    body = render(
        json.load(open(args.scorecard)),
        selection=_load(args.selection),
        test_results=_load(args.test_results),
    )
    open(args.out, "w").write(body)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
