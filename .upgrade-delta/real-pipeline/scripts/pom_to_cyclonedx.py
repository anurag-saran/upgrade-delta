#!/usr/bin/env python3
"""pom_to_cyclonedx.py -- convert the CURRENT pom.xml's <dependencies> into
the minimal CycloneDX shape upgrade_delta.py's `coverage` command expects.
Pure standard library (xml.etree) -- no Maven plugin, no network. Property
indirection (<version>${x}</version>) is resolved the same way
detect_pom_changes.py does.

This is a deliberately minimal converter: it does NOT resolve the full
transitive dependency tree (that needs Maven itself), only the dependencies
declared directly in this pom.xml. That's the right scope for "what did the
developer just change or declare here", which is what the coverage meter is
answering in this pipeline.

Usage:
    pom_to_cyclonedx.py --pom pom.xml --name my-app --out sbom.json
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def _find_container(root, path_no_ns, path_ns):
    el = root.find(path_ns, NS)
    if el is None:
        el = root.find(path_no_ns)
    return el


def _tag(el, name):
    child = el.find(f"m:{name}", NS)
    if child is None:
        child = el.find(name)
    return child


def _text(el, name):
    child = _tag(el, name)
    return child.text.strip() if child is not None and child.text else None


def resolve(version, props):
    m = re.fullmatch(r"\$\{([\w.-]+)\}", version or "")
    return props.get(m.group(1), version) if m else version


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pom", required=True)
    ap.add_argument("--name", required=True, help="app name for the SBOM metadata")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tree = ET.parse(args.pom)
    root = tree.getroot()

    props = {}
    props_el = _tag(root, "properties")
    if props_el is not None:
        for child in props_el:
            local = child.tag.split("}")[-1]
            if child.text:
                props[local] = child.text.strip()

    components, skipped = [], []
    container = _find_container(root, "dependencies", "m:dependencies")
    if container is not None:
        dep_list = container.findall("m:dependency", NS) or container.findall("dependency")
        for dep in dep_list:
            g, a, v = _text(dep, "groupId"), _text(dep, "artifactId"), _text(dep, "version")
            if not (g and a and v):
                continue
            v = resolve(v, props)
            if v.startswith("${"):
                # inherited from a parent POM this script never saw -- can't
                # resolve, so skip it rather than reporting a fake version.
                skipped.append(f"{g}:{a} (unresolved property {v})")
                continue
            components.append({"type": "library", "group": g, "name": a, "version": v})

    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"type": "application", "name": args.name}},
        "components": components,
    }
    with open(args.out, "w") as f:
        json.dump(bom, f, indent=2)

    print(f"pom -> SBOM: {len(components)} declared dependencies written to {args.out}")
    if skipped:
        print(f"  ! {len(skipped)} skipped (version inherited from a parent POM this "
              f"script can't see): {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
