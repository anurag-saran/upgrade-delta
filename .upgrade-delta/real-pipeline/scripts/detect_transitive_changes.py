#!/usr/bin/env python3
"""detect_transitive_changes.py -- given a dependency that was directly bumped
(e.g. jackson-databind 2.13.4 -> 2.13.4.rhlw-00001), finds any of ITS OWN
transitive dependencies whose resolved version differs between the old and
new pom -- i.e. the version bump you made pulled in a DIFFERENT version of
something else too, without you touching it in your pom.xml.

This is genuinely common with library families Red Hat rebuilds together
(e.g. the whole jackson-* group, or the whole spring-* group): bumping the
one you declared can silently also move a transitive you never declared.

Mechanism: parses `mvn dependency:tree` text output (Maven's TGF-like ASCII
tree format, stable across Maven 3.x) for two scratch single-dependency
projects -- one pinned to the old version, one to the new -- and diffs the
resolved version of every artifact that appears in both trees.

Usage:
    mvn dependency:tree -f old-scratch-pom.xml > old-tree.txt
    mvn dependency:tree -f new-scratch-pom.xml > new-tree.txt
    detect_transitive_changes.py old-tree.txt new-tree.txt -o transitive-changes.json
"""
import argparse
import json
import re
import sys

# Matches a dependency:tree line after stripping the leading tree-drawing
# prefix (+-, \-, |, spaces): groupId:artifactId:packaging:version:scope
# Some Maven versions add a classifier: groupId:artifactId:packaging:classifier:version:scope
_GAV_RE = re.compile(
    r"^(?P<group>[\w.\-]+):(?P<artifact>[\w.\-]+):(?P<packaging>[\w.\-]+)"
    r"(?::(?P<classifier>[\w.\-]+))?:(?P<version>[\w.\-]+):(?P<scope>[\w]+)"
)

# Strips Maven's ASCII tree-drawing characters from the start of a line:
# "+- ", "\- ", "|  +- ", "   \- ", etc.
_PREFIX_RE = re.compile(r"^[\s|+\\`-]*")


def parse_tree(text):
    """-> {(group, artifact): version} -- the LAST (most specific/deepest)
    resolved version seen for each group:artifact in the tree. Maven's own
    conflict resolution already picked the version that will actually be
    used; we trust that and don't try to re-resolve conflicts ourselves."""
    result = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        stripped = _PREFIX_RE.sub("", line).strip()
        m = _GAV_RE.match(stripped)
        if not m:
            continue
        key = (m.group("group"), m.group("artifact"))
        result[key] = m.group("version")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old_tree", help="dependency:tree output for the OLD version")
    ap.add_argument("new_tree", help="dependency:tree output for the NEW version")
    ap.add_argument("--exclude", action="append", default=[],
                     help="group:artifact to ignore (e.g. the direct dependency itself, "
                          "and its own group -- repeatable)")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    old_tree = parse_tree(open(args.old_tree).read())
    new_tree = parse_tree(open(args.new_tree).read())
    excluded = set()
    for e in args.exclude:
        g, a = e.split(":", 1)
        excluded.add((g, a))

    changed = []
    for key in sorted(set(old_tree) & set(new_tree)):
        if key in excluded:
            continue
        old_v, new_v = old_tree[key], new_tree[key]
        if old_v != new_v:
            changed.append({"group": key[0], "artifact": key[1],
                             "old_version": old_v, "new_version": new_v})

    result = {"transitive_changes": changed}
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    print(f"transitive scan: {len(old_tree)} artifacts in old tree, "
          f"{len(new_tree)} in new tree, {len(changed)} version change(s) found")
    for c in changed:
        print(f"  {c['group']}:{c['artifact']}  {c['old_version']} -> {c['new_version']}")
    if not changed:
        print("  no transitive version changes -- the bump was fully self-contained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
