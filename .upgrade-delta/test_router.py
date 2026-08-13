#!/usr/bin/env python3
"""
test-router — the consumer-side half of the bridge (in production: a Maven plugin).

Ingests:
  routing.json      from `upgrade-delta scan --routing-payload` (affected code, lanes,
                    obligations, confidence — NEVER test names; the scanner doesn't know them)
  coverage.json     the customer's per-test coverage map (JaCoCo-derived), with provenance:
                    the git SHA it was collected at, its age in commits, build id
  --tests-dir       test sources, scanned for @Tag("upgrade-gate") / @UpgradeGate declarations

Emits:
  surefire-includes.txt    what Surefire actually runs (native <includesFile> support)
  selection-report.json    why every test is on (or off) the list — the CAB artifact
  deploy-gate.json         downstream obligations for the CD pipeline to consume

Fail-closed rules (non-negotiable):
  * shrink only when the payload says every lane allows it; D/F lanes -> full suite
  * coverage missing/stale beyond threshold -> full suite, loudly
  * tests absent from the coverage map run unconditionally (unknown means run)
  * a declared mandatory obligation resolving to zero tests is a HARD FAILURE (exit 3)
"""
import argparse, json, os, re, sys
from datetime import date

BOLD, DIM, GREEN, RED, YELLOW, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"

TAG_RE = re.compile(r'@Tag\(\s*"(?P<tag>[^"]+)"\s*\)|@(?P<anno>UpgradeGate)\b')


def resolve_tagged_tests(tests_dir, tag):
    """Scan test sources for the tag declaration. In the real plugin this is the
    JUnit Platform's own discovery; here we read what's written in the source."""
    resolved = []
    for root, _, files in os.walk(tests_dir):
        for f in sorted(files):
            if not f.endswith(".java"):
                continue
            text = open(os.path.join(root, f)).read()
            for m in TAG_RE.finditer(text):
                if m.group("tag") == tag or (m.group("anno") and tag == "upgrade-gate"):
                    resolved.append(f[:-5])
                    break
    return sorted(set(resolved))


def all_tests(tests_dir):
    out = []
    for root, _, files in os.walk(tests_dir):
        out += [f[:-5] for f in files if f.endswith(".java")]
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser(prog="test-router")
    ap.add_argument("routing")
    ap.add_argument("--coverage", required=True)
    ap.add_argument("--tests-dir", required=True)
    ap.add_argument("--head-sha", required=True, help="current HEAD (the real plugin asks git)")
    ap.add_argument("--changed-since-map", default="",
                    help="comma list of app classes modified since the coverage map's SHA "
                         "(the real plugin computes this via git diff)")
    ap.add_argument("--max-drift-commits", type=int, default=25)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    with open(args.routing) as f:
        payload = json.load(f)
    os.makedirs(args.out_dir, exist_ok=True)
    suite = all_tests(args.tests_dir)

    print(f"\n== test-router :: {payload['app']} ==")
    print(f"   payload: {len(payload['upgrades'])} pending upgrade(s), "
          f"project grade {payload['project_grade']}, "
          f"shrink_allowed={payload['shrink_allowed']}")

    # ---- 1) mandatory obligations FIRST — they must resolve before anything shrinks
    mandatory, downstream = [], []
    for ob in payload["obligations"]:
        if ob["stage"] == "downstream":
            downstream.append(ob)
            continue
        decl = ob["declaration"]
        resolved = resolve_tagged_tests(args.tests_dir, decl["value"]) \
            if decl["type"] == "tag" else list(decl.get("classes", []))
        print(f"   mandatory: {ob['id']} ({decl['type']}={decl['value']}) -> "
              f"{', '.join(resolved) or 'NOTHING'} ({len(resolved)} resolved)")
        if len(resolved) < ob.get("min_resolved", 1):
            print(f"{RED}   HARD FAILURE: declared obligation '{ob['id']}' resolved to "
                  f"{len(resolved)} test(s) (min {ob.get('min_resolved', 1)}).{RESET}")
            print(f"{RED}   The declaration is stale — someone renamed/untagged the gate test."
                  f" Refusing to produce a test plan that silently omits it.{RESET}")
            sys.exit(3)
        mandatory += [{"test": t, "obligation": ob["id"]} for t in resolved]

    # ---- 2) coverage provenance — decide whether shrinking is even permitted
    reasons_full = []
    if not payload["shrink_allowed"]:
        reasons_full.append("a pending upgrade's lane is Partial/Full regression — "
                            "coverage of the old code says nothing about the new code paths")
    cov = None
    try:
        with open(args.coverage) as f:
            cov = json.load(f)
    except Exception as e:
        reasons_full.append(f"coverage map unreadable ({e}) — unknown means run")
    if cov:
        drift = cov.get("age_commits", 10**6)
        print(f"   coverage: build {cov.get('build','?')} @ {cov.get('collected_at_sha','?')} "
              f"— {drift} commit(s) behind HEAD {args.head_sha}")
        if cov.get("_note"):
            print(f"   note: {cov['_note']}")
        if drift > args.max_drift_commits:
            reasons_full.append(f"coverage map is {drift} commits stale "
                                f"(threshold {args.max_drift_commits}) — refusing to select from it")

    selection, widened = [], []
    if reasons_full:
        mode = "FULL SUITE (fail-closed)"
        selection = [{"test": t, "reason": "full-suite fallback: " + "; ".join(reasons_full)}
                     for t in suite]
    else:
        mode = "TARGETED SELECTION"
        affected = {}
        for up in payload["upgrades"]:
            for cls in up["affected_app_classes"]:
                affected.setdefault(cls, []).append(
                    f"{up['library']} {up['path']} [{up['confidence']['evidence']}"
                    + (", signed-off" if up["confidence"]["signed_off"] else "") + "]")
        changed_since = [c for c in args.changed_since_map.split(",") if c]
        cov_tests = cov.get("tests", {})
        for t in suite:
            info = cov_tests.get(t)
            if info is None:
                selection.append({"test": t,
                                  "reason": "not in coverage map — unknown means run"})
                continue
            hits = sorted(set(info.get("covers", [])) & set(affected))
            if hits:
                why = "; ".join(f"covers {h} <- {' & '.join(affected[h])}" for h in hits)
                selection.append({"test": t, "reason": why})
            elif set(info.get("covers", [])) & set(changed_since):
                widened.append({"test": t,
                                "reason": "covers app code modified since the coverage map's SHA "
                                          "— widening rule, runs regardless of selection"})
            # else: legitimately skipped, recorded below

    selected_names = {s["test"] for s in selection} | {w["test"] for w in widened}
    mand_names = {m["test"] for m in mandatory}
    appended = sorted(mand_names - selected_names)
    overlap = sorted(mand_names & selected_names)
    final = sorted(selected_names | mand_names)
    skipped = [{"test": t, "reason": "no covered class intersects any affected class"}
               for t in suite if t not in final]

    # ---- 3) outputs
    with open(os.path.join(args.out_dir, "surefire-includes.txt"), "w") as f:
        f.writelines(f"**/{t}.java\n" for t in final)

    report = {
        "schema": "upgrade-delta/selection-report/v1",
        "date": str(date.today()), "app": payload["app"], "mode": mode,
        "coverage_provenance": None if not cov else {
            "build": cov.get("build"), "sha": cov.get("collected_at_sha"),
            "age_commits": cov.get("age_commits"), "head_sha": args.head_sha},
        "selected": sorted(selection, key=lambda s: s["test"]),
        "widened": widened,
        "mandatory": {"entries": mandatory, "appended": appended,
                      "already_selected_by_coverage": overlap,
                      "note": "mandatory tests run even when the coverage join selects nothing"},
        "skipped": skipped,
        "totals": {"suite": len(suite), "selected": len(selected_names),
                   "mandatory_appended": len(appended), "final": len(final)},
    }
    with open(os.path.join(args.out_dir, "selection-report.json"), "w") as f:
        json.dump(report, f, indent=2)

    gate = {
        "schema": "upgrade-delta/deploy-gate/v1",
        "app": payload["app"], "date": str(date.today()),
        "project_grade": payload["project_grade"],
        "build_stage": {"mode": mode, "tests_final": len(final), "suite": len(suite),
                        "mandatory_verified": sorted(mand_names)},
        "signoffs": [{"library": u["library"], "signed_off": True,
                      "evidence": u["confidence"]["evidence"]}
                     for u in payload["upgrades"] if u["confidence"]["signed_off"]],
        "obligations_downstream": [
            {"id": ob["id"], "status": "OPEN", "note": ob.get("note", "")}
            for ob in downstream],
        "note": "This build did NOT run these obligations. Promotion must close them.",
    }
    with open(os.path.join(args.out_dir, "deploy-gate.json"), "w") as f:
        json.dump(gate, f, indent=2)

    # ---- 4) terminal narrative
    print(f"   mode: {BOLD}{mode}{RESET}")
    for s in sorted(selection, key=lambda x: x["test"]):
        print(f"     {GREEN}RUN {s['test']}{RESET}  {DIM}{s['reason']}{RESET}")
    for wnd in widened:
        print(f"     {YELLOW}RUN {wnd['test']}{RESET}  {DIM}{wnd['reason']}{RESET}")
    for t in appended:
        print(f"     {BOLD}RUN {t}{RESET}  {DIM}mandatory (upgrade-gate) — appended; "
              f"would run even if the join selected nothing{RESET}")
    for t in overlap:
        print(f"     {DIM}    ({t}: mandatory AND selected by coverage — counted once){RESET}")
    for s in skipped:
        print(f"     {DIM}skip {s['test']}  {s['reason']}{RESET}")
    print(f"   totals: {report['totals']['final']} of {len(suite)} "
          f"({report['totals']['selected']} selected, "
          f"{report['totals']['mandatory_appended']} mandatory appended)")
    print(f"   downstream obligations -> deploy-gate.json: "
          + ", ".join(o["id"] for o in downstream)
          + "  (OPEN — this build cannot close them)")
    print(f"   wrote: surefire-includes.txt, selection-report.json, deploy-gate.json")


if __name__ == "__main__":
    main()
