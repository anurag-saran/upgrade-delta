#!/usr/bin/env python3
"""Render scorecard.json as a PR comment (markdown). Post with:
   gh pr comment $PR --body-file pr-comment.md   (or the REST API)

Kept in sync with the scorecard HTML and the Tekton pr-comment Task:
full Maven GAV, named call sites, CVEs, optional test plan + outcomes.
"""
import argparse
import json
import os
import re
import sys

BADGE = {"A": "🟢", "B": "🟡", "C": "🟡", "D": "🔴", "F": "🔴"}


def _humanize_member(desc):
    if not desc:
        return ""
    cls, _, rest = desc.partition("#")
    simple = cls.rsplit(".", 1)[-1] if cls else desc
    if rest.startswith("<init>(") or rest.startswith("<init>"):
        args = re.findall(r"L([\w/$]+);", rest)
        short = ", ".join(a.rsplit("/", 1)[-1] for a in args)
        return f"{simple}({short})"
    if "(" in rest:
        name, _, sig = rest.partition("(")
        args = re.findall(r"L([\w/$]+);", "(" + sig)
        short = ", ".join(a.rsplit("/", 1)[-1] for a in args)
        return f"{simple}.{name}({short})"
    return f"{simple}.{rest}" if rest else simple


def _display_name(lib):
    return lib.get("gav") or lib.get("library") or "?"


def _coord(gav, version):
    if gav and version:
        return f"{gav}:{version}"
    return version or "?"


def _calls_line(rec):
    ix = rec.get("ix") or {}
    members = ix.get("lib_members_used") or []
    app_classes = ix.get("affected_app_classes") or []
    if not members:
        n = ix.get("lib_call_sites") or 0
        return f"{n} call site(s)" if n else "no direct call sites"
    shown = ", ".join(f"`{_humanize_member(m)}`" for m in members[:4])
    more = f" (+{len(members)-4} more)" if len(members) > 4 else ""
    from_bit = f" from `{app_classes[0]}`" if app_classes else ""
    return f"{shown}{more}{from_bit}"


def _load(path):
    if path and os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return None


def render(scorecard, *, selection=None, test_results=None):
    r = scorecard
    p = r["project"]
    g = p["headline_grade"] or "—"
    lines = [f"## {BADGE.get(g,'⚪')} upgrade-delta: project grade **{g}**",
             f"*{p['headline_note']}* — {p['rated_libraries']} rated dependencies, "
             f"{p['unrated_package_roots']} unrated package roots"]
    if p.get("worst_without_best_path") and p["worst_without_best_path"] != g:
        lines.append(f"> Without the best available remediation paths this project scores "
                     f"**{p['worst_without_best_path']}** — that gap is the measured value "
                     f"of the maintained backports.")
    cov = p.get("catalog_coverage") or {}
    if cov:
        lines.append(
            f"> **Catalog coverage** `{cov.get('exact', 0)}/{cov.get('dependencies', 0)}` "
            f"drop-in ready — that is *not* the scorecard row count. This comment grades "
            f"**{p['rated_libraries']}** libraries with published delta evidence; drop-in "
            f"deps stay on coverage.html as suffix swaps.")
    lines += ["",
              "| Dependency | Path | Calls | Grade | Lane | CVEs fixed |",
              "|---|---|---|---|---|---|"]
    for l in r["libraries"]:
        rec = l["recommended"]
        rt = rec["rating"]
        shown = (f"{rt['grade']} → {rt['effective_grade']} ✍️"
                 if rt.get("effective_grade") else rt["grade"])
        gav = l.get("gav")
        label = _display_name(l)
        name = (f"↳ `{label}` *(via {l['parent']})*" if l.get("transitive")
                else f"**`{label}`**")
        path = f"`{_coord(gav, rec['old'])} → {_coord(gav, rec['new'])}`"
        cves = ", ".join(f"`{c}`" for c in (rec.get("cves_fixed") or [])) or "—"
        lines.append(
            f"| {name} | {path} | {_calls_line(rec)} | "
            f"{BADGE.get(rt.get('effective_grade') or rt['grade'],'⚪')} {shown} | "
            f"{rt['lane']} | {cves} |")

    if r.get("hazards"):
        lines += ["", "**SBOM vs. shipped artifact (informational)**"] + [
            f"- `{k}` — {m}" for k, m in r["hazards"]]

    chain_hits = []
    for l in r["libraries"]:
        chain = l["recommended"]["ix"].get("internal_chain") if l["recommended"].get("ix") else None
        if not chain or not chain.get("closure_methods_reached"):
            continue
        hits = (chain.get("internal_touched_incompatible", [])
                + chain.get("internal_touched_changed", [])
                + chain.get("internal_touched_impl_changed", []))
        if hits:
            chain_hits.append((_display_name(l), chain, hits))
    if chain_hits:
        lines += ["", "**Internal call-chain reachability** "
                       "*(reaches changed code this app never calls by name)*"]
        for name, chain, hits in chain_hits:
            more = f" (+{len(hits)-1} more)" if len(hits) > 1 else ""
            hit0 = _humanize_member(hits[0]) if "#" in str(hits[0]) else hits[0]
            lines.append(f"- **`{name}`** — traced {chain['closure_methods_reached']} method(s) from "
                         f"{chain['closure_seed_count']} entry point(s) → reaches `{hit0}`{more}")

    hits = [h for h in r.get("heuristics", []) if h["intersects_change"]]
    if hits:
        lines += ["", "**Config/reflection reachability**"] + [
            f"- `{h['fqcn']}` found in {h['found_in'][0]} — treat as reachable" for h in hits]
    if r.get("unrated_packages"):
        lines += ["", f"**Coverage gap — not rated yet:** "
                      f"{', '.join(x.replace('/', '.') for x in r['unrated_packages'])} "
                      f"— no delta report published yet; upgrades here are tested blind."]

    if selection:
        t = selection["totals"]
        lines += ["", f"### Test plan — {t['final']} of {t['suite']} test classes",
                  "Every RUN carries a printed reason; skips are recorded too.", ""]
        for s in selection.get("selected") or []:
            lines.append(f"- ✅ **{s['test']}** — {s['reason']}")
        for m in (selection.get("mandatory") or {}).get("appended") or []:
            lines.append(f"- 🔒 **{m}** — mandatory `@Tag(upgrade-gate)`, always runs")
        for s in selection.get("skipped") or []:
            lines.append(f"- ⚪ {s['test']} — {s['reason']}")

    if test_results:
        lines += ["", "### Test results"]
        grade = p.get("headline_grade") or ""
        if test_results.get("status") != "ran":
            lines.append("- Tests were **not run** in this pipeline.")
        elif test_results.get("methods_failed"):
            fails = test_results.get("failed_names") or []
            who = (" — `" + "`, `".join(fails[:8]) + "`") if fails else ""
            lines.append(
                f"- ❌ **{test_results.get('methods_failed')} FAILED** / "
                f"{test_results.get('methods_passed', 0)} passed "
                f"({test_results.get('methods_run', 0)} methods run){who}")
        else:
            caveat = ""
            if grade in ("F", "D"):
                caveat = (f" — on current jars; does **not** clear project **{grade}** "
                          f"(re-test after you migrate)")
            lines.append(
                f"- ✅ **All passed** — {test_results.get('methods_passed', 0)} methods "
                f"({test_results.get('methods_run', 0)} run, 0 failed){caveat}")
        for lib, o in sorted((test_results.get("by_library") or {}).items()):
            if not o.get("selected_count") and o.get("status") == "not_selected":
                continue
            # Per-lib grade from scorecard libraries list
            lib_grade = None
            for l in r.get("libraries") or []:
                if l.get("library") == lib:
                    rt = l["recommended"]["rating"]
                    lib_grade = rt.get("effective_grade") or rt.get("grade")
                    break
            mark = "✅" if o.get("status") == "passed" else (
                "❌" if o.get("status") == "failed" else "⚪")
            extra = ""
            if o.get("failed_names"):
                extra = " — `" + "`, `".join(o["failed_names"][:3]) + "`"
            elif o.get("status") == "passed" and lib_grade in ("F", "D"):
                extra = (f" — on current jars; does not clear **{lib_grade}**")
            lines.append(
                f"- {mark} **`{lib}`** — {o.get('selected_count', 0)} selected, "
                f"status `{o.get('status')}`{extra}")

    lines += ["", "---",
              "**CAB approval:** this comment is the change-board summary. "
              "Approve by reviewing here and merging — branch protection requires this "
              "check to pass.",
              "*Grade ≥ D auto-fails the pipeline (after tests); any de-escalation is "
              "signed off and recorded on the sealed evidence.*",
              "",
              "<sub>Same data as scorecard.html (Maven GAV + named call sites + CVEs + "
              "test outcomes). Coverage.html answers catalog availability; this comment "
              "answers graded upgrade cost. ✍️ = de-escalation signed off.</sub>"]
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
