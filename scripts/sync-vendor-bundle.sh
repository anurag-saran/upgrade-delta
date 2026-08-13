#!/usr/bin/env bash
# Regenerate .upgrade-delta/ from canonical sources (root + integration/).
# Usage:
#   ./scripts/sync-vendor-bundle.sh          # write bundle
#   ./scripts/sync-vendor-bundle.sh --check  # exit 1 if bundle would change
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DEST=".upgrade-delta"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "$STAGING/$DEST/real-pipeline/scripts" "$STAGING/$DEST/catalogs" "$STAGING/$DEST/jacoco"

# Core tool + catalog + jacoco converter
cp -f upgrade_delta.py "$STAGING/$DEST/upgrade_delta.py"
cp -f test_router.py "$STAGING/$DEST/test_router.py"
cp -f integration/github-action/pr_comment.py "$STAGING/$DEST/pr_comment.py"
cp -f catalogs/lightwell-remediated-java-sbom.json \
  "$STAGING/$DEST/catalogs/lightwell-remediated-java-sbom.json"
cp -f integration/jacoco/jacoco2coverage.py "$STAGING/$DEST/jacoco/jacoco2coverage.py"

# Real pipeline (source of truth)
cp -a integration/tekton/real-pipeline/. "$STAGING/$DEST/real-pipeline/"

# Demo/shared Tekton tasks also vendored into real-pipeline for drop-in use
for f in \
  task-upgrade-delta-pr-comment.yaml \
  task-upgrade-delta-run-tests.yaml \
  task-upgrade-delta-scan.yaml \
  task-upgrade-delta-select-tests.yaml \
  task-upgrade-delta-summary.yaml
do
  cp -f "integration/tekton/$f" "$STAGING/$DEST/real-pipeline/$f"
done

# Bundle README (canonical text — do not hand-edit under .upgrade-delta/)
cat > "$STAGING/$DEST/README.md" <<'EOF'
# .upgrade-delta/ — the vendorable bundle

**Generated** by `scripts/sync-vendor-bundle.sh`. Do not edit files here by hand;
change the sources and re-run the sync script.

| Bundle path | Source of truth |
|-------------|-----------------|
| `upgrade_delta.py` | repo root `upgrade_delta.py` |
| `catalogs/` | repo `catalogs/` |
| `jacoco/` | `integration/jacoco/` |
| `real-pipeline/` | `integration/tekton/real-pipeline/` plus shared tasks from `integration/tekton/task-upgrade-delta-*.yaml` |

Copy this directory wholesale into a target application repository so the live/real
pipeline can run standalone. See `real-pipeline/README.md` for setup.
EOF

check_mode=0
if [[ "${1:-}" == "--check" ]]; then
  check_mode=1
fi

if [[ "$check_mode" -eq 1 ]]; then
  if [[ ! -d "$DEST" ]]; then
    echo "Missing $DEST — run ./scripts/sync-vendor-bundle.sh" >&2
    exit 1
  fi
  if ! diff -rq "$STAGING/$DEST" "$DEST" >/tmp/upgrade-delta-vendor-diff.txt; then
    echo "Vendor bundle out of sync with sources:" >&2
    cat /tmp/upgrade-delta-vendor-diff.txt >&2
    echo "Run: ./scripts/sync-vendor-bundle.sh" >&2
    exit 1
  fi
  echo "Vendor bundle up to date: $DEST"
  exit 0
fi

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -a "$STAGING/$DEST" "$DEST"
echo "Wrote $DEST from canonical sources"
