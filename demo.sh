#!/usr/bin/env bash
# demo.sh — the new pitch, on the customer's terms: fat jars everywhere, no
# re-architecture asked. One question: how much testing does this upgrade owe you?
#
#   DEMO_AUTOPLAY=1        auto-advance instead of waiting for Enter
#   DEMO_TYPE_DELAY=0.015  seconds per typed character
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; RESET=$'\e[0m'
narrate() { echo; echo "${BOLD}==> $*${RESET}"; }
type_cmd() {
  local d="${DEMO_TYPE_DELAY:-0.015}"; printf '   $ '
  local s="$*"; for ((i=0;i<${#s};i++)); do printf '%s' "${s:i:1}"; sleep "$d"; done; echo
}
step_pause() {
  if [[ "${DEMO_AUTOPLAY:-0}" == "1" ]]; then sleep 1.2; else
    echo "${DIM}   [Enter to continue]${RESET}"; read -r; fi
}

J=samples/jars
APP=${J}/payments-service-1.0.0.jar

if [[ ! -f "${APP}" ]]; then
  narrate "First run: building the sample corpus (3 libraries, several versions, 1 fat-jar app)"
  type_cmd "python3 samples/build_samples.py"
  python3 samples/build_samples.py
fi
mkdir -p out/evidence out/reports

narrate "The setup — and what we are NOT asking for"
echo "   payments-service is a plain fat jar. The libraries live inside it. That stays true"
echo "   for this entire demo. Nobody re-architects anything."
echo
echo "   A CVE just landed in acme-logging. Two artifacts close it:"
echo "     - the community forward-upgrade:  1.14.1 -> 1.17.1"
echo "     - a maintained backport:          1.12.1 -> 1.12.2   (same fix, minimal delta)"
echo "   Same CVE. The question nobody can answer today: how much testing does each one owe?"
step_pause

narrate "Path 1: the forward upgrade everyone did that December"
type_cmd "upgrade-delta analyze acme-logging-1.14.1.jar acme-logging-1.17.1.jar --app payments-service.jar"
python3 upgrade_delta.py analyze ${J}/acme-logging-1.14.1.jar ${J}/acme-logging-1.17.1.jar \
  --app "${APP}" --old-version 1.14.1 --new-version 1.17.1 --library acme-logging \
  --json out/evidence/logging-forward.json --html out/reports/tmp-f.html
echo
echo "   ${RED}That verdict IS the six weeks.${RESET} Nothing above is scripted — it's a structural"
echo "   diff of the two real jars, intersected with the app's own bytecode. The app calls"
echo "   a member that no longer exists. This upgrade doesn't need a bigger test plan;"
echo "   it needs a migration."
step_pause

narrate "Path 2: the backport — same CVE closed"
type_cmd "upgrade-delta analyze acme-logging-1.12.1.jar acme-logging-1.12.2.jar --app payments-service.jar"
python3 upgrade_delta.py analyze ${J}/acme-logging-1.12.1.jar ${J}/acme-logging-1.12.2.jar \
  --app "${APP}" --old-version 1.12.1 --new-version 1.12.2 --library acme-logging \
  --json out/evidence/logging-backport.json --html out/reports/tmp-b.html
echo
echo "   ${GREEN}Same fix. One class changed. The app touches nothing that moved.${RESET}"
echo "   Smoke test, canary, promote. The six-week difference was never the code —"
echo "   it was which artifact you sourced. Now that's a measured number, not a vendor claim."
step_pause

narrate "The rule is honest about patches that only CLAIM to be small"
type_cmd "upgrade-delta analyze acme-http-client-4.5.13.jar acme-http-client-4.5.14.jar --app payments-service.jar"
python3 upgrade_delta.py analyze ${J}/acme-http-client-4.5.13.jar ${J}/acme-http-client-4.5.14.jar \
  --app "${APP}" --old-version 4.5.13 --new-version 4.5.14 --library acme-http-client \
  --json out/evidence/http.json --html out/reports/tmp-h.html
echo
echo "   ${YELLOW}A z-stream on the label, but half the internals rewritten and a shipped default"
echo "   flipped — so it does NOT get the fast lane.${RESET} The rating escalates on evidence,"
echo "   not version-number optimism. That's what makes the fast lane defensible when it IS granted."
step_pause

python3 upgrade_delta.py analyze ${J}/acme-json-2.13.4.jar ${J}/acme-json-2.13.4.2.jar \
  --app "${APP}" --old-version 2.13.4 --new-version 2.13.4.2 --library acme-json \
  --json out/evidence/json.json --html out/reports/tmp-j.html >/dev/null

narrate "Publish: one report card per remediated artifact — the thing you hand the change board"
type_cmd "upgrade-delta publish out/evidence/*.json --out out/reports"
rm -f out/reports/tmp-*.html
python3 upgrade_delta.py publish out/evidence/logging-forward.json out/evidence/logging-backport.json \
  out/evidence/http.json out/evidence/json.json --out out/reports
echo
echo "   Open ${BOLD}out/reports/index.html${RESET} — a rated catalog, one certificate per upgrade,"
echo "   each with the full evidence AND an explicit 'what this cannot see' section."
echo "   In an FSI shop the bottleneck isn't the engineer's confidence — it's the approval."
echo "   ${BOLD}The report is the product.${RESET}"
step_pause

narrate "The plugin view: score the WHOLE project — transitives included, at full weight"
type_cmd "upgrade-delta scan payments-service.jar --evidence out/evidence --sbom sbom.json --lib-jars jars/"
python3 upgrade_delta.py scan "${APP}" --evidence out/evidence \
  --sbom ${J}/payments-service.sbom.json --lib-jars ${J} \
  --json out/scorecard.json --html out/reports/scorecard.html || true
echo
echo "   ${RED}acme-codec never appears in the app's own bytecode${RESET} — the SBOM says"
echo "   acme-http-client brought it in, and two-hop reachability walks app -> parent"
echo "   closure -> codec. It scores D and the PROJECT is D: risk does not roll up."
echo "   But look at the evidence: the removed member is only called from parent paths"
echo "   this app never reaches. De-escalation is ${BOLD}offered, not applied${RESET}."
step_pause

narrate "The engineer signs off — with the evidence chain printed on the report"
type_cmd "upgrade-delta scan ... --accept-transitive-scope --fail-on D"
python3 upgrade_delta.py scan "${APP}" --evidence out/evidence \
  --sbom ${J}/payments-service.sbom.json --lib-jars ${J} --accept-transitive-scope \
  --json out/scorecard-signed.json --html out/reports/scorecard-signed.html --fail-on D || true
echo
echo "   Four things on that scorecard, none of them an average:"
echo "     1. ${BOLD}Headline = worst pending grade on the best available path per library.${RESET}"
echo "        One migration-grade dependency makes it a migration-grade project."
echo "     2. ${BOLD}B with the backport, F without it${RESET} — the gap between those two numbers"
echo "        is what a maintained backport is worth, measured, per project."
echo "     3. ${BOLD}com.acme.xml is unrated and visible${RESET} — every uncovered dependency is"
echo "        an upgrade you'd be testing blind. Whitespace is a subscription conversation."
echo "     4. ${BOLD}codec D -> B only under an explicit sign-off flag${RESET} — the CAB sees who"
echo "        accepted the two-hop evidence and the report says reflection blindness compounds."
echo "   And --fail-on turns it into a CI gate: the same project FAILS at D without the"
echo "   sign-off and passes with it. The gate enforces the conversation."
step_pause

narrate "Why the churn number can be trusted at all"
echo "   A skeptic's first move: hash two functionally-identical builds and watch a"
echo "   naive tool report 100% churn. So churn here is a ${BOLD}semantic fingerprint${RESET}:"
echo "   debug tables, stack frames, and constant-pool ordering stripped; bytecode"
echo "   walked instruction-by-instruction with pool indices resolved to values."
type_cmd "python3 samples/verify_churn.py"
python3 samples/verify_churn.py
echo
echo "   ${GREEN}Same source, different toolchain flags: every byte differs, semantic churn 0.0%.${RESET}"
echo "   The one real method edit still reads 6.2%. And anything the fingerprint can't"
echo "   parse falls back to raw — over-reporting is the only permitted failure."
step_pause

narrate "Close the loop: from affected CODE to an actual test list"
echo "   The scan emitted a routing payload — affected classes, lanes, obligations,"
echo "   confidence. ${BOLD}Never test names${RESET}: the scanner doesn't know the customer's tests."
echo "   The router (in production: a Maven plugin) joins it with THEIR coverage map:"
type_cmd "test-router routing.json --coverage coverage.json --tests-dir src/test"
python3 test_router.py out/routing.json --coverage samples/tests/coverage.json \
  --tests-dir samples/tests --head-sha def5678 \
  --changed-since-map com.acme.payments.Ledger --out-dir out/routing-out
echo
echo "   Every RUN has a printed reason tracing back to a changed member. Every skip"
echo "   is recorded. MetricsTest ran because it's ${BOLD}absent from the map — unknown"
echo "   means run${RESET}. LedgerTest ran via the widening rule. BootSmokeIT was appended"
echo "   as mandatory: it would run ${BOLD}even if the join had selected nothing${RESET}."
step_pause

narrate "The handoff: a DIFFERENT process, at deploy time, consumes the gate file"
type_cmd "./mock-cd-gate.sh out/routing-out/deploy-gate.json"
./mock-cd-gate.sh out/routing-out/deploy-gate.json
step_pause

narrate "And the security paths — watch it fail closed, on purpose"
echo "   ${YELLOW}(1) Coverage map 41 commits stale:${RESET}"
python3 test_router.py out/routing.json --coverage samples/tests/coverage-stale.json \
  --tests-dir samples/tests --head-sha def5678 --out-dir /tmp/r-stale 2>&1 | grep -E "coverage:|mode:|totals:"
echo "   ${YELLOW}(2) Someone untagged the boot test:${RESET}"
python3 test_router.py out/routing.json --coverage samples/tests/coverage.json \
  --tests-dir samples/tests-untagged --head-sha def5678 --out-dir /tmp/r-untag || true
echo "   ${YELLOW}(3) Deploy without a gate file:${RESET}"
./mock-cd-gate.sh /tmp/does-not-exist.json || true
echo
echo "   Wrong answers are LOUD: too many tests, a failed build, a blocked promotion."
echo "   Never a silently skipped gate."
step_pause

narrate "Phase 2 precision: method-level reachability defuses the RestTemplate problem"
echo "   HttpClient now has a debugDump() that calls the codec's REMOVED member. The old"
echo "   class-granular closure would flag it and kill the de-escalation. Method-level:"
python3 upgrade_delta.py scan ${J}/payments-service-1.0.0.jar --evidence out/evidence \
  --sbom ${J}/payments-service.sbom.json --lib-jars ${J} --accept-transitive-scope 2>/dev/null \
  | grep -E "reachability:|precision:"
echo "   The app never calls debugDump, so that path is provably unreached — the"
echo "   sign-off survives ${BOLD}because${RESET} the analysis got sharper, not looser."
step_pause

narrate "Phase 2 reality: reactor modules, fat jars, and the map-vs-territory check"
echo "   Same scan, three packagings — a thin jar, two reactor module jars, one uber jar:"
python3 upgrade_delta.py scan ${J}/payments-uber-1.0.0.jar --evidence out/evidence \
  --sbom ${J}/payments-service.sbom.json --lib-jars ${J} --accept-transitive-scope 2>/dev/null \
  | grep -E "bundles|HAZARD|heuristic|PROJECT"
echo "   Bundled dependency internals are excluded from the app view; the SBOM-vs-artifact"
echo "   drift and the ${BOLD}relocated shaded codec copy${RESET} surface as hazard rows; and the"
echo "   config-file reference to ConsoleAppender is a visible heuristic row instead of"
echo "   an invisible blind spot."
step_pause

narrate "Phase 3: the evidence chain gets sealed — and edits get caught"
type_cmd "upgrade-delta seal scorecard.json routing.json && upgrade-delta verify ..."
python3 upgrade_delta.py seal out/scorecard-signed.json out/routing.json --key out/keys/evidence-signing.pem >/dev/null
python3 upgrade_delta.py verify out/scorecard-signed.json out/routing.json
cp out/scorecard-signed.json /tmp/tampered.json; cp out/scorecard-signed.json.sig /tmp/tampered.json.sig
python3 -c "import json; d=json.load(open('/tmp/tampered.json')); d['project']['headline_grade']='A'; json.dump(d, open('/tmp/tampered.json','w'))"
python3 upgrade_delta.py verify /tmp/tampered.json --pub out/keys/evidence-signing.pem.pub || true
echo "   Someone edited the grade from B to A after sealing. ${RED}Caught.${RESET} To a change"
echo "   board, an unsigned JSON is a text document; a sealed one is an audit artifact."
step_pause

narrate "Phase 3: where this lives — the PR, not a dashboard"
python3 integration/github-action/pr_comment.py out/scorecard-uber.json out/pr-comment.md >/dev/null
head -6 out/pr-comment.md
echo "   ..."
echo "   Rendered by the GitHub Action on every Renovate PR (integration/github-action/),"
echo "   Jenkins snippet alongside it, and the Maven plugin scaffold does mandatory-test"
echo "   resolution with REAL JUnit Platform discovery instead of the demo's regex."
step_pause

narrate "Close with the caveat that keeps this credible"
echo "   Structural analysis cannot see every behavioral change. A patch with zero structural"
echo "   fingerprint still gets a canary and a rollback path — the tool sizes the risk,"
echo "   it doesn't abolish it. That honesty is printed on every report, on purpose."
echo
echo "${GREEN}Done. Evidence in out/evidence/, published reports in out/reports/.${RESET}"
