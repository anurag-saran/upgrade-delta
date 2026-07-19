#!/usr/bin/env bash
# fetch-real-log4j.sh — run the exact same analysis on the REAL Log4j artifacts.
# Needs outbound access to repo1.maven.org (not available in every sandbox;
# the bundled sample corpus exists so the demo also runs fully offline).
#
# Pairs:
#   2.14.1 -> 2.17.1   the community forward-upgrade of December 2021
#   2.12.1 -> 2.12.2   Log4j's own emergency z-stream backport of the Log4Shell fix
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "${ROOT}"
BASE="https://repo1.maven.org/maven2/org/apache/logging/log4j/log4j-core"
mkdir -p real-jars out/evidence out/reports

for v in 2.14.1 2.17.1 2.12.1 2.12.2; do
  [[ -f "real-jars/log4j-core-${v}.jar" ]] || \
    curl -fSL "${BASE}/${v}/log4j-core-${v}.jar" -o "real-jars/log4j-core-${v}.jar"
done

APP_FLAG=()
if [[ -n "${APP_JAR:-}" ]]; then APP_FLAG=(--app "${APP_JAR}"); fi

python3 upgrade_delta.py analyze real-jars/log4j-core-2.14.1.jar real-jars/log4j-core-2.17.1.jar \
  "${APP_FLAG[@]}" --old-version 2.14.1 --new-version 2.17.1 --library log4j-core \
  --json out/evidence/log4j-forward.json --html out/reports/log4j-forward.html

python3 upgrade_delta.py analyze real-jars/log4j-core-2.12.1.jar real-jars/log4j-core-2.12.2.jar \
  "${APP_FLAG[@]}" --old-version 2.12.1 --new-version 2.12.2 --library log4j-core \
  --json out/evidence/log4j-backport.json --html out/reports/log4j-backport.html

python3 upgrade_delta.py publish out/evidence/log4j-*.json --out out/reports
echo "Real-artifact reports written to out/reports/"
echo "Tip: set APP_JAR=/path/to/your-app.jar to intersect with your own application."
