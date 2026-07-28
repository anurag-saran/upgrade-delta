#!/usr/bin/env bash
[ -f "$(dirname "$0")/.env.local" ] && . "$(dirname "$0")/.env.local"  # auto-load creds if setup-openshift.sh was run
# Pull the exact Lightwell remediated jars the sample app depends on, so you can build
# and analyze locally without Maven resolving them. Community versions come from Central;
# remediated versions come from Lightwell with your credentials.
#
#   export RHLN_USER='orgID|service-account'  RHLN_TOKEN='...'
#   ./fetch-lightwell-app-jars.sh
set -euo pipefail
RHLN_REPO="${RHLN_REPO:-https://packages.redhat.com/lightwell/java/remediated}"
OUT="sample-app/lib"; mkdir -p "$OUT"
[[ -n "${RHLN_USER:-}" && -n "${RHLN_TOKEN:-}" ]] || { echo "set RHLN_USER and RHLN_TOKEN" >&2; exit 1; }

# group|artifact|remediated-version
DEPS="
com.fasterxml.jackson.core|jackson-databind|2.13.4.rhlw-00001
org.springframework|spring-web|5.3.18.rhlw-00010
org.springframework|spring-webmvc|5.3.18.rhlw-00010
org.springframework|spring-core|5.3.18.rhlw-00010
org.springframework.boot|spring-boot|2.7.18.rhlw-00004
org.springframework.boot|spring-boot-autoconfigure|2.7.18.rhlw-00004
org.springframework.security|spring-security-core|5.7.11.rhlw-00006
org.springframework.security|spring-security-web|5.7.11.rhlw-00006
commons-io|commons-io|2.11.0.rhlw-00001
org.apache.httpcomponents|httpclient|4.5.12.rhlw-00001
net.minidev|json-smart|2.5.0.rhlw-00001
"
echo "$DEPS" | while IFS='|' read -r g a v; do
  [[ -n "$a" ]] || continue
  gp="${g//.//}"
  url="${RHLN_REPO}/${gp}/${a}/${v}/${a}-${v}.jar"
  echo "-> ${a}-${v}.jar"
  curl -fSL -u "${RHLN_USER}:${RHLN_TOKEN}" "$url" -o "${OUT}/${a}-${v}.jar" \
    || echo "   ! failed: $url (check version/suffix — some are .rhlw- not .redhat-)"
done
echo "done -> ${OUT}/"
echo "Note: build numbers advance over time -- these versions were verified current"
echo "as of this script's last update. If a download 404s, re-run"
echo "./fetch-lightwell-catalog-metadata.sh to check the real current build number,"
echo "and update the DEPS list above + pom.xml to match."
