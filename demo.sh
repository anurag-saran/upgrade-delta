#!/usr/bin/env bash
# Narrated offline demo against the committed real-library corpus.
# Needs: Python 3. No JDK required for scan/coverage (tests jar is prebuilt).
# Keeps examples/{coverage,scorecard,pr-comment,test-results} in sync.
set -euo pipefail
cd "$(dirname "$0")"
APP=examples/demo-jars/payments-service-1.0.0.jar
SBOM=examples/demo-jars/payments-service.sbom.json
EV=examples/evidence
mkdir -p out/reports out/routing-out

echo "== 1. Lightwell coverage (same SBOM the scan uses) =="
python3 upgrade_delta.py coverage \
  --sbom "$SBOM" \
  --catalog catalogs/lightwell-remediated-java-sbom.json \
  --json out/coverage.json --html out/reports/coverage.html

echo
echo "== 2. Project scan — spring-core B / json-path C / snakeyaml F =="
set +e
python3 upgrade_delta.py scan "$APP" \
  --evidence "$EV" --sbom "$SBOM" \
  --osv-dir examples/osv --no-osv-fetch \
  --coverage out/coverage.json \
  --lib-jars examples/demo-jars \
  --routing-payload out/routing.json \
  --json out/scorecard.json --html out/reports/scorecard.html \
  --fail-on D
RC=$?
set -e
echo "(scan exit $RC — F on snakeyaml breaches --fail-on D; that is the demo gate)"

echo
echo "== 3. Route tests this upgrade owes =="
python3 test_router.py out/routing.json \
  --coverage examples/tests/coverage.json \
  --tests-dir examples/tests \
  --head-sha demo --out-dir out/routing-out

echo
echo "== 4. Run selected tests (MiniRunner) =="
export JAVA_HOME="${JAVA_HOME:-$(/usr/libexec/java_home 2>/dev/null || true)}"
PASSED=0; FAILED=0; SUMMARY="tests not run"; STATUS=not_run
FAIL_ARGS=()
if command -v java >/dev/null 2>&1; then
  CP=$(ls examples/demo-jars/*.jar examples/demo-jars/lib/*.jar 2>/dev/null | tr '\n' ':')
  set +e
  java -cp "$CP" testing.MiniRunner out/routing-out/surefire-includes.txt | tee /tmp/demo-exec.log
  set -e
  PASSED=$(grep -cE '^[[:space:]]*PASS[[:space:]]' /tmp/demo-exec.log || true)
  FAILED=$(grep -cE '^[[:space:]]*FAIL[[:space:]]' /tmp/demo-exec.log || true)
  PASSED=${PASSED:-0}; FAILED=${FAILED:-0}
  EXECUTED=$((PASSED + FAILED))
  STATUS=ran
  if [ "$FAILED" -eq 0 ] && [ "$EXECUTED" -gt 0 ]; then
    SUMMARY=$(printf 'Ran %s test method(s) for real in this JVM -- all passed, 0 failed.' "$EXECUTED")
  elif [ "$EXECUTED" -eq 0 ]; then
    SUMMARY='MiniRunner produced no PASS/FAIL lines — 0 tests recorded.'
  else
    SUMMARY=$(printf 'Ran %s test method(s) for real in this JVM -- %s FAILED.' "$EXECUTED" "$FAILED")
  fi
  while IFS= read -r line; do
    name=$(echo "$line" | sed -E 's/^[[:space:]]*FAIL[[:space:]]+//; s/[[:space:]]*->.*//; s/#/./')
    [ -n "$name" ] && FAIL_ARGS+=(--failed-name "$name")
  done < <(grep -E '^[[:space:]]*FAIL[[:space:]]' /tmp/demo-exec.log || true)
else
  echo "java not on PATH — skip MiniRunner (jar is still committed for the cluster demo)"
fi

python3 upgrade_delta.py record-test-results \
  --out out/test-results.json \
  --passed "$PASSED" --failed "$FAILED" \
  --summary "$SUMMARY" --status "$STATUS" \
  --selection out/routing-out/selection-report.json \
  --scorecard out/scorecard.json \
  --routing out/routing.json \
  --coverage examples/tests/coverage.json \
  "${FAIL_ARGS[@]+"${FAIL_ARGS[@]}"}"

python3 upgrade_delta.py render-scorecard out/scorecard.json \
  --html out/reports/scorecard.html \
  --test-results out/test-results.json

python3 integration/github-action/pr_comment.py out/scorecard.json out/pr-comment.md \
  --selection out/routing-out/selection-report.json \
  --test-results out/test-results.json

# Committed snapshots — keep coverage / scorecard / PR comment / tests aligned
cp -f out/coverage.json examples/coverage.json
cp -f out/reports/coverage.html examples/coverage.html
cp -f out/scorecard.json examples/scorecard.json
cp -f out/reports/scorecard.html examples/scorecard.html
cp -f out/test-results.json examples/test-results.json
cp -f out/pr-comment.md examples/pr-comment.md

echo
echo "Done. Open out/reports/coverage.html and out/reports/scorecard.html"
echo "Synced examples/{coverage,scorecard,pr-comment,test-results}.*"
