#!/usr/bin/env bash
# ============================================================================
#  fetch-lightwell-catalog-metadata.sh
#
#  Pulls REAL maven-metadata.xml (tiny -- just version lists, not jars) for
#  every group:artifact in catalogs/lightwell-remediated-java-sbom.json (or a
#  custom list you pass), saves it locally for visual inspection, and prints a
#  diff against what the local catalog currently claims.
#
#  This does NOT and CANNOT mirror "everything" in Lightwell -- the repo is a
#  Pulp content server with no directory listing, and the full catalog is
#  6,500+ packages across Java and Python. This script only ever asks for
#  coordinates it's explicitly given, which keeps it a small, fast, honest
#  request instead of an attempted bulk crawl.
#
#  Usage:
#    source .env.local
#    ./fetch-lightwell-catalog-metadata.sh                 # every GAV in the catalog
#    ./fetch-lightwell-catalog-metadata.sh gav-list.txt     # custom list, one "group:artifact" per line
# ============================================================================
set -uo pipefail

BOLD=$'\e[1m'; GREEN=$'\e[32m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; DIM=$'\e[2m'; RESET=$'\e[0m'
REPO_BASE="https://packages.redhat.com/lightwell/java/remediated"
CATALOG="catalogs/lightwell-remediated-java-sbom.json"
OUT_DIR="lightwell-catalog-metadata"   # gitignored scratch dir -- inspect and delete freely

command -v curl >/dev/null 2>&1 || { echo "${RED}curl not found${RESET}"; exit 1; }
[ -n "${RHLN_USER:-}" ] && [ -n "${RHLN_TOKEN:-}" ] || {
  echo "${RED}RHLN_USER / RHLN_TOKEN not set.${RESET} Run: source .env.local"
  exit 1
}

mkdir -p "$OUT_DIR"

# ---- build the GAV list -----------------------------------------------------
GAV_FILE="${1:-}"
GAVS=()
if [ -n "$GAV_FILE" ]; then
  [ -f "$GAV_FILE" ] || { echo "${RED}not found: $GAV_FILE${RESET}"; exit 1; }
  while IFS= read -r line; do
    [ -n "$line" ] && GAVS+=("$line")
  done < "$GAV_FILE"
  echo "Using custom list: $GAV_FILE (${#GAVS[@]} coordinates)"
else
  echo "No list given -- using every group:artifact already in $CATALOG"
  while IFS= read -r line; do
    [ -n "$line" ] && GAVS+=("$line")
  done < <(python3 -c "
import json
c = json.load(open('$CATALOG'))
pairs = sorted({(x['group'], x['name']) for x in c['components']})
for g, n in pairs: print(f'{g}:{n}')
")
fi
echo "Fetching metadata for ${#GAVS[@]} coordinates -> $OUT_DIR/"
echo

OK=0; MISS=0; FAIL=0
SUMMARY="$OUT_DIR/SUMMARY.tsv"
printf 'group\tartifact\tstatus\tlatest_real\tcatalog_has\tmatch\n' > "$SUMMARY"

for gav in "${GAVS[@]}"; do
  [ -z "$gav" ] && continue
  group="${gav%%:*}"; artifact="${gav##*:}"
  path=$(echo "$group" | tr '.' '/')
  url="$REPO_BASE/$path/$artifact/maven-metadata.xml"
  outfile="$OUT_DIR/${group}_${artifact}.xml"

  code=$(curl -sS -L -o "$outfile" -w '%{http_code}' -u "$RHLN_USER:$RHLN_TOKEN" "$url" 2>/dev/null)

  if [ "$code" = "200" ] && grep -q '<latest>' "$outfile" 2>/dev/null; then
    latest=$(sed -n 's:.*<latest>\(.*\)</latest>.*:\1:p' "$outfile" | head -1)
    catalog_has=$(python3 -c "
import json
c = json.load(open('$CATALOG'))
for x in c['components']:
    if x['group']=='$group' and x['name']=='$artifact':
        print(x['version']); break
" 2>/dev/null)
    match="?"
    if [ -n "$catalog_has" ]; then
      [ "$catalog_has" = "$latest" ] && match="SAME" || match="DIFFERS"
    fi
    printf '%s\t%s\tOK\t%s\t%s\t%s\n' "$group" "$artifact" "$latest" "${catalog_has:--}" "$match" >> "$SUMMARY"
    if [ "$match" = "DIFFERS" ]; then
      printf "  ${YELLOW}DIFFERS${RESET}  %-55s catalog=%-22s live-latest=%s\n" "$group:$artifact" "$catalog_has" "$latest"
    fi
    OK=$((OK+1))
  elif [ "$code" = "404" ]; then
    printf '%s\t%s\tNOT_FOUND\t-\t-\t-\n' "$group" "$artifact" >> "$SUMMARY"
    MISS=$((MISS+1))
  else
    printf '%s\t%s\tHTTP_%s\t-\t-\t-\n' "$group" "$artifact" "$code" >> "$SUMMARY"
    FAIL=$((FAIL+1))
    rm -f "$outfile"
  fi
done

echo
echo "─────────────────────────────────────────────────────────"
echo "${BOLD}Done.${RESET}  OK=$OK  not-in-catalog(404)=$MISS  other-errors=$FAIL"
echo "  Raw XML for each package : $OUT_DIR/<group>_<artifact>.xml"
echo "  One-line-per-package table: $OUT_DIR/SUMMARY.tsv  (open in Excel/Numbers to sort/filter)"
echo "  Anything marked DIFFERS above means the local catalog's pinned version"
echo "  is stale (real, but not the current release) -- worth updating."
echo "─────────────────────────────────────────────────────────"
