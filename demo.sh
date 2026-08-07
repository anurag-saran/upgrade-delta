#!/usr/bin/env bash
# Narrated offline demo against the committed real-library corpus.
# Needs: Python 3. No JDK required for scan/coverage (tests jar is prebuilt).
set -euo pipefail
cd "$(dirname "$0")"
APP=examples/demo-jars/payments-service-1.0.0.jar
SBOM=examples/demo-jars/payments-service.sbom.json
EV=examples/evidence
mkdir -p out/reports

echo "== 1. Lightwell coverage (same SBOM the scan uses) =="
python3 upgrade_delta.py coverage \
  --sbom "$SBOM" \
  --catalog catalogs/lightwell-remediated-java-sbom.json \
  --json out/coverage.json --html out/reports/coverage.html
cp -f out/coverage.json examples/coverage.json
cp -f out/reports/coverage.html examples/coverage.html

echo
echo "== 2. Project scan — spring-core B / json-path C / snakeyaml F =="
set +e
python3 upgrade_delta.py scan "$APP" \
  --evidence "$EV" --sbom "$SBOM" \
  --osv-dir examples/osv --no-osv-fetch \
  --lib-jars examples/demo-jars \
  --routing-payload out/routing.json \
  --json out/scorecard.json --html out/reports/scorecard.html \
  --fail-on D
RC=$?
set -e
cp -f out/scorecard.json examples/scorecard.json
cp -f out/reports/scorecard.html examples/scorecard.html
echo "(scan exit $RC — F on snakeyaml breaches --fail-on D; that is the demo gate)"

# Keep the PR comment in sync with scorecard.html (GAV + named calls + CVEs)
python3 integration/github-action/pr_comment.py out/scorecard.json out/pr-comment.md
cp -f out/pr-comment.md examples/pr-comment.md 2>/dev/null || true

echo
echo "== 3. Route tests this upgrade owes =="
python3 test_router.py out/routing.json \
  --coverage examples/tests/coverage.json \
  --tests-dir examples/tests \
  --head-sha demo --out-dir out/routing-out

echo
echo "== 4. Run selected tests (MiniRunner) =="
export JAVA_HOME="${JAVA_HOME:-$(/usr/libexec/java_home 2>/dev/null || true)}"
if command -v java >/dev/null 2>&1; then
  CP=$(ls examples/demo-jars/*.jar | tr '\n' ':')
  java -cp "$CP" testing.MiniRunner out/routing-out/surefire-includes.txt || true
else
  echo "java not on PATH — skip MiniRunner (jar is still committed for the cluster demo)"
fi

echo
echo "Done. Open out/reports/coverage.html and out/reports/scorecard.html"
