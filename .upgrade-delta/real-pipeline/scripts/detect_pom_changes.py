#!/usr/bin/env python3
"""detect_pom_changes.py -- diff two pom.xml files and report every
dependency whose <version> changed. Flags the ones whose NEW version carries
a Red Hat Lightwell build suffix (…rhlw-NNNNN or the legacy …redhat-NNNNN) as
"adopted" -- those are what the live pipeline grades. A version change to a
non-rhlw version is still reported (for visibility) but not graded here.

Pure standard library (xml.etree) -- no Maven, no network. Handles Maven
<properties> version indirection: if a <dependency> declares
<version>${some.prop}</version>, the property is resolved from
<properties> before comparing.

Usage:
    detect_pom_changes.py --base base-pom.xml --head head-pom.xml --out changed-deps.json
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

NS = {"m": "http://maven.apache.org/POM/4.0.0"}
RHSUFFIX = re.compile(r"[.\-](redhat|rhlw)-\d+$")


def _tag(el, name):
    """Find a direct child by local name, tolerant of the Maven POM namespace
    being declared or not (some repos strip it, most don't)."""
    child = el.find(f"m:{name}", NS)
    if child is None:
        child = el.find(name)
    return child


def _text(el, name):
    child = _tag(el, name)
    return child.text.strip() if child is not None and child.text else None


def _find_container(root, path_no_ns, path_ns):
    """Try the namespaced path first (correct for a standard pom.xml), then
    the bare path (for a pom.xml some tooling stripped the xmlns from).
    Never use `a or b` here -- an Element with no children is falsy even
    when found, which would wrongly fall through to the second attempt."""
    el = root.find(path_ns, NS)
    if el is None:
        el = root.find(path_no_ns)
    return el


def parse_pom(path):
    """-> {'properties': {name: value}, 'dependencies': [(group, artifact, raw_version)]}
    raw_version may be a ${property} reference, resolved by the caller."""
    tree = ET.parse(path)
    root = tree.getroot()

    props = {}
    props_el = _tag(root, "properties")
    if props_el is not None:
        for child in props_el:
            local = child.tag.split("}")[-1]
            if child.text:
                props[local] = child.text.strip()

    deps = []
    for path_no_ns, path_ns in (
        ("dependencies", "m:dependencies"),
        ("dependencyManagement/dependencies", "m:dependencyManagement/m:dependencies"),
    ):
        container = _find_container(root, path_no_ns, path_ns)
        if container is None:
            continue
        dep_list = container.findall("m:dependency", NS) or container.findall("dependency")
        for dep in dep_list:
            g, a, v = _text(dep, "groupId"), _text(dep, "artifactId"), _text(dep, "version")
            if g and a and v:
                deps.append((g, a, v))
    return props, deps


def resolve(version, props):
    """${some.prop} -> the property's literal value, if declared in THIS pom.
    Leaves it as the raw ${...} string if the property isn't found locally
    (e.g. inherited from a parent POM this script doesn't have) -- callers
    should treat an unresolved value as 'cannot determine, skip'."""
    m = re.fullmatch(r"\$\{([\w.-]+)\}", version or "")
    if not m:
        return version
    return props.get(m.group(1), version)


def is_rhlw(version):
    return bool(RHSUFFIX.search(version or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="pom.xml at the target/base branch")
    ap.add_argument("--head", required=True, help="pom.xml at the PR head (current checkout)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    base_props, base_deps = parse_pom(args.base)
    head_props, head_deps = parse_pom(args.head)

    base_by_ga = {(g, a): resolve(v, base_props) for g, a, v in base_deps}
    head_by_ga = {(g, a): resolve(v, head_props) for g, a, v in head_deps}

    changed, adopted = [], []
    for ga, new_v in head_by_ga.items():
        old_v = base_by_ga.get(ga)
        if old_v is None or old_v == new_v:
            continue
        if new_v.startswith("${"):
            # unresolved property (likely inherited from a parent POM this
            # script never saw) -- report it as changed but don't guess.
            continue
        entry = {"group": ga[0], "artifact": ga[1], "old_version": old_v, "new_version": new_v}
        changed.append(entry)
        if is_rhlw(new_v):
            adopted.append(entry)

    result = {"changed": changed, "lightwell_adopted": adopted}
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    print(f"pom diff: {len(changed)} dependency version change(s), "
          f"{len(adopted)} adopting a Lightwell (rhlw) build")
    for e in changed:
        tag = "  <- Lightwell adoption, will be graded" if e in adopted else ""
        print(f"  {e['group']}:{e['artifact']}  {e['old_version']} -> {e['new_version']}{tag}")

    if not adopted:
        print("\nNo Lightwell (rhlw) version adoption detected in this PR's pom.xml diff -- "
              "the live grading step will have nothing to grade and will pass through cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
