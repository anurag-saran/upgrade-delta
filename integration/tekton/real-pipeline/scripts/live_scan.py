#!/usr/bin/env python3
"""live_scan.py -- the real, PR-driven grading engine. For every dependency
the pom.xml diff shows adopting a Lightwell (rhlw) build, this:
  1. downloads the OLD (community) jar and the NEW (rhlw) jar for real,
  2. loads the freshly-built application jar,
  3. calls upgrade_delta's own diff/intersect/rate functions directly
     (imported as a module -- this is not a re-implementation, it is the
     exact same grading logic the fixture demo pipeline uses),
  4. writes out/scorecard.json in the same shape scan() produces, so the
     existing summary and pr-comment tasks work completely unmodified.

Deliberately out of scope for this version (documented, not silently
skipped): transitive/two-hop analysis (needs a published catalog of
transitive delta reports, which doesn't exist for a live single-PR diff),
and test routing/execution (needs a real per-test JaCoCo coverage map --
see docs/REAL-LIBRARIES.md Tier 3 in the upgrade-delta tool repo).

Usage:
    live_scan.py --changed-deps out/changed-deps.json --app-jar target/app.jar
                  --workdir /tmp/lw-jars --fail-on D --json out/scorecard.json
Env:
    RHLN_USER, RHLN_TOKEN   -- Lightwell console service-account credentials
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import upgrade_delta as ud  # the real tool, imported as a library

MAVEN_CENTRAL = "https://repo1.maven.org/maven2"
LIGHTWELL_REPO = "https://packages.redhat.com/lightwell/java/remediated"


def _gav_path(group, artifact, version):
    return f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar"


def _download(url, dest, auth=None):
    req = urllib.request.Request(url)
    if auth:
        import base64
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def fetch_old_jar(group, artifact, version, workdir):
    """The pre-change (community) version -- Maven Central, no auth."""
    dest = os.path.join(workdir, f"{artifact}-{version}-OLD.jar")
    url = f"{MAVEN_CENTRAL}/{_gav_path(group, artifact, version)}"
    print(f"  fetching old jar: {url}")
    _download(url, dest)
    return dest


def fetch_new_jar(group, artifact, version, workdir):
    """The Lightwell remediated build -- authenticated."""
    user, token = os.environ.get("RHLN_USER"), os.environ.get("RHLN_TOKEN")
    if not (user and token):
        raise RuntimeError("RHLN_USER / RHLN_TOKEN not set -- cannot fetch the "
                            "Lightwell remediated jar. Wire the "
                            "lightwell-maven-settings-derived credentials into "
                            "this task's environment.")
    dest = os.path.join(workdir, f"{artifact}-{version}-NEW.jar")
    url = f"{LIGHTWELL_REPO}/{_gav_path(group, artifact, version)}"
    print(f"  fetching Lightwell jar: {url}")
    _download(url, dest, auth=(user, token))
    return dest


def grade_one(app_model, group, artifact, old_version, new_version, old_jar_path, new_jar_path):
    old_model = ud.load_jar(old_jar_path)
    new_model = ud.load_jar(new_jar_path)
    delta = ud.diff_jars(old_model, new_model)
    stream = ud.classify_stream(old_version, new_version)
    ix = ud.intersect_app(app_model, old_model, delta)
    ix["internal_chain"] = ud.internal_chain_intersect(app_model, old_model, delta)
    rating = ud.rate(stream, delta, ix, transitive=False, signoff=False)
    machine = {
        "packages": sorted({c.rsplit("/", 1)[0] for c in old_model["classes"] if "/" in c}),
        "impl_churn_pct": delta["impl_churn_pct"],
        "api_incompatible": delta["api_incompatible"],
    }
    option = {
        "machine": machine, "old": old_version, "new": new_version, "stream": stream,
        "rating": rating, "ix": ix, "churn": delta["impl_churn_pct"],
        "incompatible": len(delta["api_incompatible"]), "in_place": True,
    }
    return {
        "library": artifact, "options": [option], "recommended": option, "worst": option,
        "call_sites": ix["lib_call_sites"], "transitive": False, "parent": None,
        "installed": old_version,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--changed-deps", required=True)
    ap.add_argument("--app-jar", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--fail-on", default="D", choices=ud.GRADE_ORDER)
    ap.add_argument("--json", required=True)
    ap.add_argument("--html", default=None, help="optional path to also write a rendered scorecard.html")
    args = ap.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    with open(args.changed_deps) as f:
        changes = json.load(f)
    adopted = changes.get("lightwell_adopted", [])

    if not adopted:
        result = {
            "tool": {"name": "upgrade-delta", "version": ud.TOOL_VERSION},
            "date": str(ud.date.today()), "app": os.path.basename(args.app_jar),
            "libraries": [], "unrated_packages": [], "heuristics": [], "hazards": [],
            "project": {
                "headline_grade": None,
                "headline_note": "no Lightwell (rhlw) dependency adoption in this PR's pom.xml diff",
                "worst_without_best_path": None, "rated_libraries": 0,
                "unrated_package_roots": 0, "lane_histogram": {},
            },
        }
        with open(args.json, "w") as f:
            json.dump(result, f, indent=2)
        if args.html:
            os.makedirs(os.path.dirname(args.html), exist_ok=True)
            with open(args.html, "w") as f:
                f.write(ud.render_scorecard(result))
        print("no Lightwell adoption in this PR -- wrote an empty (pass-through) scorecard")
        return 0

    app_model = ud.load_jar(args.app_jar)

    libs = []
    for dep in adopted:
        g, a = dep["group"], dep["artifact"]
        old_v, new_v = dep["old_version"], dep["new_version"]
        print(f"grading {g}:{a}  {old_v} -> {new_v}")
        try:
            old_jar = fetch_old_jar(g, a, old_v, args.workdir)
            new_jar = fetch_new_jar(g, a, new_v, args.workdir)
        except Exception as e:
            print(f"  ! could not fetch jars for {g}:{a}: {e}")
            print(f"    skipped -- this dependency will not appear in the scorecard. "
                  f"Check the old version really exists on Maven Central under these "
                  f"exact coordinates, and that RHLN_USER/RHLN_TOKEN are valid.")
            continue
        libs.append(grade_one(app_model, g, a, old_v, new_v, old_jar, new_jar))

    gi = {g: i for i, g in enumerate(ud.GRADE_ORDER)}
    def eff(o):
        return o["rating"]["effective_grade"] or o["rating"]["grade"]
    worst_rec = max((eff(l["recommended"]) for l in libs), key=lambda g: gi[g], default=None)
    worst_any = max((l["worst"]["rating"]["grade"] for l in libs), key=lambda g: gi[g], default=None)
    histogram = {}
    for l in libs:
        lane = l["recommended"]["rating"]["lane"]
        histogram.setdefault(lane, {"direct": 0, "transitive": 0})
        histogram[lane]["direct"] += 1

    result = {
        "tool": {"name": "upgrade-delta", "version": ud.TOOL_VERSION},
        "date": str(ud.date.today()), "app": os.path.basename(args.app_jar),
        "libraries": libs, "unrated_packages": [], "heuristics": [], "hazards": [],
        "project": {
            "headline_grade": worst_rec,
            "headline_note": "worst pending grade across this PR's adopted Lightwell builds",
            "worst_without_best_path": worst_any,
            "rated_libraries": len(libs), "unrated_package_roots": 0,
            "lane_histogram": histogram,
        },
    }
    with open(args.json, "w") as f:
        json.dump(result, f, indent=2)
    if args.html:
        os.makedirs(os.path.dirname(args.html), exist_ok=True)
        with open(args.html, "w") as f:
            f.write(ud.render_scorecard(result))
        print(f"wrote {args.html}")

    print(f"\n== live scan verdict: PROJECT_GRADE={worst_rec} "
          f"({len(libs)} Lightwell adoption(s) graded) ==")
    for l in libs:
        r = l["recommended"]["rating"]
        print(f"  {l['library']}: {l['recommended']['old']} -> {l['recommended']['new']}  "
              f"grade={r['grade']}  lane={r['lane']}")

    if worst_rec and gi[worst_rec] >= gi[args.fail_on]:
        print(f"\nGATE: project grade {worst_rec} breaches --fail-on {args.fail_on}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
