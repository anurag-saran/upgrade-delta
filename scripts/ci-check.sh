#!/usr/bin/env bash
# Non-mutating CI gate: unit tests, jacoco selftest, offline demo scan grades.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== unit tests =="
python3 -m unittest discover -s tests -v

echo
echo "== jacoco2coverage selftest =="
python3 integration/jacoco/jacoco2coverage.py --selftest

echo
echo "== offline scan (assert grades; do not sync examples/) =="
APP=examples/demo-jars/payments-service-1.0.0.jar
SBOM=examples/demo-jars/payments-service.sbom.json
EV=examples/evidence
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

python3 upgrade_delta.py coverage \
  --sbom "$SBOM" \
  --catalog catalogs/lightwell-remediated-java-sbom.json \
  --json "$OUT/coverage.json" --html "$OUT/coverage.html"

set +e
python3 upgrade_delta.py scan "$APP" \
  --evidence "$EV" --sbom "$SBOM" \
  --osv-dir examples/osv --no-osv-fetch \
  --coverage "$OUT/coverage.json" \
  --lib-jars examples/demo-jars \
  --routing-payload "$OUT/routing.json" \
  --json "$OUT/scorecard.json" --html "$OUT/scorecard.html" \
  --fail-on D
RC=$?
set -e
echo "scan exit=$RC (expect non-zero: F breaches --fail-on D)"

SCAN_RC="$RC" python3 - <<PY
import json, os, sys
sc = json.load(open("$OUT/scorecard.json"))
grades = {}
for lib in sc["libraries"]:
    rec = lib.get("recommended") or (lib.get("options") or [None])[0]
    if not rec:
        continue
    grades[lib["library"]] = rec["rating"]["grade"]
print("grades:", grades)
expected = {"spring-core": "B", "json-path": "C", "snakeyaml": "F"}
missing = [k for k in expected if k not in grades]
if missing:
    sys.exit(f"missing libraries in scorecard: {missing}")
bad = {k: grades[k] for k, v in expected.items() if grades[k] != v}
if bad:
    sys.exit(f"unexpected grades: {bad} (want {expected})")
if int(os.environ["SCAN_RC"]) == 0:
    sys.exit("expected scan to breach --fail-on D (snakeyaml F)")
print("CI check OK")
PY
