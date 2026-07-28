#!/usr/bin/env python3
"""Render scorecard.json as a PR comment (markdown). Post with:
   gh pr comment $PR --body-file pr-comment.md   (or the REST API)"""
import json, sys

BADGE = {"A": "🟢", "B": "🟡", "C": "🟡", "D": "🔴", "F": "🔴"}

def main(scorecard_path, out_path):
    r = json.load(open(scorecard_path))
    p = r["project"]
    g = p["headline_grade"] or "—"
    lines = [f"## {BADGE.get(g,'⚪')} upgrade-delta: project grade **{g}**",
             f"*{p['headline_note']}* — {p['rated_libraries']} rated dependencies, "
             f"{p['unrated_package_roots']} unrated package roots"]
    if p.get("worst_without_best_path") and p["worst_without_best_path"] != g:
        lines.append(f"> Without the best available remediation paths this project scores "
                     f"**{p['worst_without_best_path']}** — that gap is the measured value "
                     f"of the maintained backports.")
    lines += ["", "| Dependency | Path | Grade | Lane |", "|---|---|---|---|"]
    for l in r["libraries"]:
        rec = l["recommended"]; rt = rec["rating"]
        shown = f"{rt['grade']} → {rt['effective_grade']} ✍️" if rt.get("effective_grade") else rt["grade"]
        name = f"↳ {l['library']} *(via {l['parent']})*" if l.get("transitive") else f"**{l['library']}**"
        lines.append(f"| {name} | `{rec['old']} → {rec['new']}` | "
                     f"{BADGE.get(rt.get('effective_grade') or rt['grade'],'⚪')} {shown} | {rt['lane']} |")
    if r.get("hazards"):
        lines += ["", "**⚠️ Hazards**"] + [f"- `{k}` — {m}" for k, m in r["hazards"]]
    chain_hits = []
    for l in r["libraries"]:
        chain = l["recommended"]["ix"].get("internal_chain") if l["recommended"].get("ix") else None
        if not chain or not chain.get("closure_methods_reached"):
            continue
        hits = (chain.get("internal_touched_incompatible", []) + chain.get("internal_touched_changed", [])
                + chain.get("internal_touched_impl_changed", []))
        if hits:
            chain_hits.append((l["library"], chain, hits))
    if chain_hits:
        lines += ["", "**🔗 Internal call-chain reachability** "
                       "*(reaches changed code this app never calls by name)*"]
        for name, chain, hits in chain_hits:
            more = f" (+{len(hits)-1} more)" if len(hits) > 1 else ""
            lines.append(f"- **{name}** — traced {chain['closure_methods_reached']} method(s) from "
                         f"{chain['closure_seed_count']} entry point(s) → reaches `{hits[0]}`{more}")
    hits = [h for h in r.get("heuristics", []) if h["intersects_change"]]
    if hits:
        lines += ["", "**🔍 Config/reflection reachability**"] + \
                 [f"- `{h['fqcn']}` found in {h['found_in'][0]} — treat as reachable" for h in hits]
    if r.get("unrated_packages"):
        lines += ["", f"**Unrated:** {', '.join(x.replace('/', '.') for x in r['unrated_packages'])} "
                      f"— upgrades here are currently tested blind."]
    lines += ["", "<sub>Ratings computed by upgrade-delta; evidence JSON is sealed — "
                  "verify with `upgrade-delta verify`. ✍️ = de-escalation signed off.</sub>"]
    open(out_path, "w").write("\n".join(lines) + "\n")
    print(f"wrote {out_path}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "pr-comment.md")
