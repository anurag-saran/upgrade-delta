#!/usr/bin/env bash
# mock-cd-gate.sh — stands in for the CD pipeline's promotion step.
# A DIFFERENT process, at a DIFFERENT stage, consuming deploy-gate.json.
# That separation is the point: the build plugin never claims the canary ran;
# the deploy stage refuses to promote until the open obligations are closed here.
set -uo pipefail
GATE="${1:-out/routing-out/deploy-gate.json}"
BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; RESET=$'\e[0m'

echo
echo "${BOLD}== cd-gate :: promotion check ==${RESET}"
if [[ ! -f "${GATE}" ]]; then
  echo "${RED}   BLOCKED: no deploy-gate.json from the build stage."
  echo "   No evidence of the test plan or its open obligations — refusing to promote.${RESET}"
  exit 4
fi

python3 - "$GATE" <<'EOF'
import json, sys, time
g = json.load(open(sys.argv[1]))
B, D, GN, YL, R = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[0m"
bs = g["build_stage"]
print(f"   artifact: {g['app']}   project grade: {g['project_grade']}")
print(f"   build stage attests: mode={bs['mode']}, ran {bs['tests_final']}/{bs['suite']} tests,")
print(f"   mandatory verified: {', '.join(bs['mandatory_verified'])}")
for s in g.get("signoffs", []):
    print(f"   {D}sign-off on record: {s['library']} ({s['evidence']} evidence){R}")
print(f"   open obligations from build stage:")
for ob in g["obligations_downstream"]:
    print(f"     {YL}{ob['id']}: {ob['status']}{R}  {D}{ob.get('note','')}{R}")
print()
print(f"   {B}closing obligations at deployment stage {YL}[SIMULATED — this mock stands in for your CD tooling]{R}")
print(f"     canary: routing 5% of traffic to one instance ...", flush=True)
time.sleep(0.6)
print(f"     canary: {D}[simulated]{R} error rate nominal, p99 within band")
print(f"     {GN}canary: CLOSED{R}")
print(f"     rollback-path: {D}[simulated]{R} previous artifact present, dry-run ok")
print(f"     {GN}rollback-path: CLOSED{R}")
print()
print(f"   {GN}{B}PROMOTED{R} — all obligations closed. The chain the CAB reads:")
print(f"   {D}changed members -> reachability -> sign-off -> selected tests (+mandatory)")
print(f"   -> open obligations -> closed at deploy. One unbroken record.{R}")
EOF
