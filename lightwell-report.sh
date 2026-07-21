#!/usr/bin/env bash
# lightwell-report.sh — generate an upgrade-delta report for a Lightwell-remediated library.
#
# Usage:
#   export RHLN_USER='XXXXXXX|my-service-account'    # org ID | service-account name
#   export RHLN_TOKEN='<your token>'                 # from console.redhat.com service account
#   ./lightwell-report.sh <groupId> <artifactId> <currentVersion> [remediatedVersion] [appJar]
#
# Examples:
#   ./lightwell-report.sh com.fasterxml.jackson.core jackson-databind 2.13.4
#       -> lists available .rhlw versions for 2.12.1 if you don't know the exact suffix
#   ./lightwell-report.sh com.fasterxml.jackson.core jackson-databind 2.13.4 2.12.1.rhlw-1 target/myapp.jar
#       -> full report incl. intersection with YOUR application
#
# The report is a LOCAL html file (this script prints its path and opens it if it can).
# console.redhat.com is where the service account lives, not where this report appears.
set -euo pipefail

RHLN_REPO="${RHLN_REPO:-https://packages.redhat.com/lightwell/java/remediated}"
CENTRAL="https://repo1.maven.org/maven2"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"

[[ -n "${RHLN_USER:-}" && -n "${RHLN_TOKEN:-}" ]] || {
  echo "Set RHLN_USER ('orgID|service-account-name') and RHLN_TOKEN first." >&2; exit 1; }
[[ $# -ge 3 ]] || { grep '^#' "$0" | head -16; exit 1; }

GROUP="$1"; ARTIFACT="$2"; CURRENT="$3"; REMEDIATED="${4:-}"; APP="${5:-}"
GPATH=$(printf %s "$GROUP" | tr . /)   # portable across bash 3.2 / zsh
mkdir -p lightwell-jars out/evidence out/reports

# ---- discover the remediated version if not supplied -------------------------
if [[ -z "$REMEDIATED" ]]; then
  echo "No remediated version given — listing what Lightwell publishes for ${ARTIFACT} ${CURRENT}:"
  META="${RHLN_REPO}/${GPATH}/${ARTIFACT}/maven-metadata.xml"
  if curl -fsSL -u "${RHLN_USER}:${RHLN_TOKEN}" "$META" -o /tmp/rhlw-meta.xml; then
    grep -o '<version>[^<]*</version>' /tmp/rhlw-meta.xml | sed 's/<[^>]*>//g' \
      | grep -F "$CURRENT" || echo "  (none matching ${CURRENT} — check the tier URL or version)"
    echo "Re-run with the exact remediated version as the 4th argument."
  else
    echo "Could not read ${META} — verify RHLN_REPO for your tier and your credentials." >&2
  fi
  exit 0
fi

# ---- fetch both artifacts ----------------------------------------------------
OLD_JAR="lightwell-jars/${ARTIFACT}-${CURRENT}.jar"
NEW_JAR="lightwell-jars/${ARTIFACT}-${REMEDIATED}.jar"
[[ -f "$OLD_JAR" ]] || curl -fSL \
  "${CENTRAL}/${GPATH}/${ARTIFACT}/${CURRENT}/${ARTIFACT}-${CURRENT}.jar" -o "$OLD_JAR"
[[ -f "$NEW_JAR" ]] || curl -fSL -u "${RHLN_USER}:${RHLN_TOKEN}" \
  "${RHLN_REPO}/${GPATH}/${ARTIFACT}/${REMEDIATED}/${ARTIFACT}-${REMEDIATED}.jar" -o "$NEW_JAR"

# ---- analyze -> the report ---------------------------------------------------
APP_FLAG=(); [[ -n "$APP" ]] && APP_FLAG=(--app "$APP")
SLUG="${ARTIFACT}-${CURRENT}-to-${REMEDIATED}"
python3 upgrade_delta.py analyze "$OLD_JAR" "$NEW_JAR" ${APP_FLAG[@]+"${APP_FLAG[@]}"} \
  --old-version "$CURRENT" --new-version "$REMEDIATED" --library "$ARTIFACT" \
  --json "out/evidence/${SLUG}.json" --html "out/reports/${SLUG}.html"
python3 upgrade_delta.py publish out/evidence/*.json --out out/reports

REPORT="$(cd out/reports && pwd)/${SLUG}.html"
echo
echo "REPORT: file://${REPORT}"
echo "CATALOG: file://$(cd out/reports && pwd)/index.html"
command -v xdg-open >/dev/null && xdg-open "$REPORT" || true
command -v open >/dev/null && open "$REPORT" || true
