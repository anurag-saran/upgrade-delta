#!/usr/bin/env bash
# generate_evidence.sh — for every pom.xml version change, fetch OLD+NEW jars
# (Maven Central vs Lightwell by version string), run analyze, then scan the
# app against the freshly written evidence dir.
#
# Usage (from the cloned app workspace root):
#   generate_evidence.sh \
#     --changes out/changed-deps.json \
#     --app-module-dir sample-app \
#     --settings /path/to/settings.xml \
#     --ud-py .upgrade-delta/upgrade_delta.py \
#     [--lightwell-repo URL] [--fail-on D]
#
# Writes:
#   out/jars/*.jar
#   out/evidence/<artifact>-<old>-to-<new>.json
#   out/scorecard.json  out/reports/scorecard.html  out/routing.json
# Prints APP_JAR=<path> on stdout for the caller to capture.
set -euo pipefail

CHANGES=""
APP_MODULE="."
SETTINGS=""
UD_PY=".upgrade-delta/upgrade_delta.py"
LIGHTWELL_REPO="https://packages.redhat.com/lightwell/java/remediated"
FAIL_ON="D"

while [ $# -gt 0 ]; do
  case "$1" in
    --changes) CHANGES="$2"; shift 2 ;;
    --app-module-dir) APP_MODULE="$2"; shift 2 ;;
    --settings) SETTINGS="$2"; shift 2 ;;
    --ud-py) UD_PY="$2"; shift 2 ;;
    --lightwell-repo) LIGHTWELL_REPO="$2"; shift 2 ;;
    --fail-on) FAIL_ON="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$CHANGES" ] && [ -f "$CHANGES" ] || { echo "FATAL: --changes file required"; exit 1; }
[ -n "$SETTINGS" ] && [ -f "$SETTINGS" ] || { echo "FATAL: --settings file required"; exit 1; }
[ -f "$UD_PY" ] || { echo "FATAL: upgrade_delta.py not found at $UD_PY"; exit 1; }
command -v mvn >/dev/null || { echo "FATAL: mvn not found"; exit 1; }
command -v python3 >/dev/null || { echo "FATAL: python3 not found"; exit 1; }

mkdir -p out/jars out/evidence out/reports

# Route by version string: rhlw/redhat suffix → Lightwell repo; else Central.
is_remediated() {
  [[ "$1" =~ [.\-](redhat|rhlw)-[0-9]+$ ]]
}

fetch_jar() {
  local g="$1" a="$2" v="$3"
  local out="out/jars/${a}-${v}.jar"
  if [ -f "$out" ]; then
    echo "  already have $out"
    return 0
  fi
  echo "  fetching $g:$a:$v"
  if is_remediated "$v"; then
    mvn -B -s "$SETTINGS" dependency:copy \
      -Dartifact="$g:$a:$v:jar" -DoutputDirectory=out/jars \
      -Dmdep.stripVersion=false \
      -DremoteRepositories="lightwell-remediated::::${LIGHTWELL_REPO}"
  else
    mvn -B -s "$SETTINGS" dependency:copy \
      -Dartifact="$g:$a:$v:jar" -DoutputDirectory=out/jars \
      -Dmdep.stripVersion=false
  fi
  [ -f "$out" ] || { echo "FATAL: could not resolve $out"; return 1; }
}

COUNT=$(python3 -c "import json; print(len(json.load(open('$CHANGES'))['changed']))")
if [ "$COUNT" = "0" ]; then
  echo "No version changes to analyze — writing empty scorecard and exiting 0."
  python3 - <<'PY'
import json
empty = {
  "app": "", "project": {
    "headline_grade": None, "rated_libraries": 0,
    "unrated_package_roots": 0, "worst_without_best_path": None,
  },
  "libraries": [], "unrated_packages": [], "hazards": [], "heuristics": [],
}
json.dump(empty, open("out/scorecard.json", "w"), indent=2)
PY
  echo "APP_JAR="
  exit 0
fi

echo "building app module: $APP_MODULE"
( cd "$APP_MODULE" && mvn -B -s "$SETTINGS" -DskipTests package )
APP_JAR=$(find "$APP_MODULE/target" -maxdepth 1 -name '*.jar' \
             -not -name '*-sources.jar' -not -name '*-javadoc.jar' -not -name 'original-*' \
           | head -1)
[ -n "$APP_JAR" ] || { echo "FATAL: no built app jar under $APP_MODULE/target/"; exit 1; }
echo "APP_JAR=$APP_JAR"

# Avoid pipe+while subshell so analyze failures abort this script.
while IFS='|' read -r G A OV NV; do
  [ -z "$A" ] && continue
  echo
  echo "=== evidence: $G:$A  $OV -> $NV ==="
  fetch_jar "$G" "$A" "$OV"
  fetch_jar "$G" "$A" "$NV"
  OLD_JAR="out/jars/${A}-${OV}.jar"
  NEW_JAR="out/jars/${A}-${NV}.jar"
  EVIDENCE="out/evidence/${A}-${OV}-to-${NV}.json"
  python3 "$UD_PY" analyze "$OLD_JAR" "$NEW_JAR" \
    --app "$APP_JAR" \
    --old-version "$OV" --new-version "$NV" \
    --library "$A" \
    --json "$EVIDENCE" \
    --html "out/reports/${A}-${OV}-to-${NV}.html"
  echo "  wrote $EVIDENCE"
done < <(python3 -c "
import json
for c in json.load(open('$CHANGES'))['changed']:
    print(f\"{c['group']}|{c['artifact']}|{c['old_version']}|{c['new_version']}\")
")

EVIDENCE_N=$(find out/evidence -name '*.json' | wc -l | tr -d ' ')
[ "$EVIDENCE_N" -gt 0 ] || { echo "FATAL: no evidence files written"; exit 1; }

echo
echo "=== scan against $EVIDENCE_N live evidence file(s) ==="
FAIL_ARGS=()
[ -n "$FAIL_ON" ] && FAIL_ARGS=(--fail-on "$FAIL_ON")
set +e
python3 "$UD_PY" scan "$APP_JAR" \
  --evidence out/evidence \
  --lib-jars out/jars \
  --json out/scorecard.json \
  --html out/reports/scorecard.html \
  --routing-payload out/routing.json \
  "${FAIL_ARGS[@]+"${FAIL_ARGS[@]}"}"
SCAN_RC=$?
set -e
echo "scan exit=$SCAN_RC"
# Propagate grade-gate failure (exit 2) when --fail-on is set; allow 0.
exit "$SCAN_RC"
