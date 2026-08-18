#!/usr/bin/env bash
# ============================================================================
#  upgrade-delta — OpenShift demo setup
#
#  Gathers every credential/URL once, verifies each, then writes them where
#  they belong: cluster Secrets (via oc) and a local env file for the scripts.
#  Run from the repo root:  ./setup-openshift.sh
# ============================================================================
set -uo pipefail

BOLD=$'\e[1m'; GREEN=$'\e[32m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; DIM=$'\e[2m'; RESET=$'\e[0m'
NS="upgrade-delta-demo"
ENVFILE=".env.local"

# Reuse anything you've already saved locally so re-runs don't re-prompt.
# .env.local vars: RHLN_USER RHLN_TOKEN REG_USER REG_TOKEN UPGRADE_DELTA_REPO_URL
if [ -f "$ENVFILE" ]; then
  # shellcheck disable=SC1090
  . "$ENVFILE"
  : "${REPO_URL:=${UPGRADE_DELTA_REPO_URL:-}}"
  LOADED_ENV=1
fi

hr(){ printf '%s\n' "────────────────────────────────────────────────────────────────"; }
ok(){ printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
bad(){ printf "  ${RED}✗${RESET} %s\n" "$1"; }
warn(){ printf "  ${YELLOW}!${RESET} %s\n" "$1"; }

# ---- ask helpers ----------------------------------------------------------
ask() {  # ask "Prompt" VARNAME  -> visible input; skipped if already set
  local prompt="$1" var="$2" val="" cur="${!2:-}"
  if [ -n "$cur" ]; then ok "$prompt — using '${cur}' from ${ENVFILE}"; return; fi
  printf "${BOLD}%s${RESET}\n  > " "$prompt"; read -r val
  printf -v "$var" '%s' "$val"
}
ask_secret() {  # hidden input (tokens/passwords); skipped if already set
  local prompt="$1" var="$2" val="" cur="${!2:-}"
  if [ -n "$cur" ]; then ok "$prompt — using token from ${ENVFILE}"; return; fi
  printf "${BOLD}%s${RESET}\n  ${DIM}(input hidden)${RESET} > " "$prompt"
  read -rs val; echo
  printf -v "$var" '%s' "$val"
}

# ---- 0. the shopping list -------------------------------------------------
clear 2>/dev/null || true
cat <<BANNER
${BOLD}upgrade-delta — OpenShift demo setup${RESET}

Before we start, gather these. Nothing is stored until you type it in, and
tokens are entered hidden. Use ${BOLD}service-account tokens, never account passwords${RESET}.

$(hr)
${BOLD}1. Red Hat console service account${RESET}  — pulls the Lightwell remediated jars
     • username in the form  orgID|service-account-name
     • token
     get it at: https://console.redhat.com  → Service Accounts

${BOLD}2. Red Hat registry service account${RESET}  — pulls the RHTAS cosign image
     • username in the form  NNNNNNN|name   (DIFFERENT from #1)
     • token
     get it at: https://registry.redhat.io  → Service Accounts
     (or access.redhat.com/terms-based-registry)

${BOLD}3. Your Git repository URL${RESET}  — what the pipeline clones
     • e.g. https://github.com/anurag-saran/upgrade-delta

${BOLD}4. OpenShift login${RESET}  — you must already be logged in with 'oc'
     • this script checks; if not, run 'oc login ...' first

${BOLD}5. (nothing to gather)${RESET} the Sigstore OIDC token is minted at runtime.
$(hr)

This script will:
  • read '${ENVFILE}' if present and ONLY prompt for what's missing
  • create namespace '${NS}'
  • create Secret 'lightwell-maven-settings'  (from #1)
  • create Secret 'redhat-registry' + link to the pipeline SA  (from #2)
  • (re)write '${ENVFILE}'  with all creds + repo URL  (chmod 600, gitignored)
  • verify #1 and #2 actually work before writing them

BANNER
if [ "${LOADED_ENV:-0}" = 1 ]; then
  printf "${GREEN}Loaded ${ENVFILE}${RESET} — filled values below will be reused; you'll only be asked for blanks.\n\n"
fi
if oc get project "$NS" >/dev/null 2>&1; then
  printf "${YELLOW}Note:${RESET} project '%s' already exists (a previous install?).\n" "$NS"
  printf "      To re-install cleanly, run ${BOLD}./cleanup-openshift.sh${RESET} first, then this script.\n\n"
fi
printf "Ready? Press Enter to begin, or Ctrl-C to go gather them first. "
read -r _

# ---- 1. preflight: oc + login --------------------------------------------
hr; echo "${BOLD}Preflight${RESET}"
if ! command -v oc >/dev/null 2>&1; then bad "oc not found — install the OpenShift CLI"; exit 1; fi
ok "oc present"
if ! oc whoami >/dev/null 2>&1; then
  bad "not logged in. Run:  oc login <api-url>"; exit 1
fi
ok "logged in as $(oc whoami)"
command -v curl >/dev/null 2>&1 && ok "curl present" || warn "curl missing — will skip credential pre-checks"

# ---- 2. gather everything up front ---------------------------------------
hr; echo "${BOLD}Now enter each value${RESET} (tokens are hidden)"; echo
ask        "1a. Console service-account username (orgID|name)"      RHLN_USER
ask_secret "1b. Console service-account token"                       RHLN_TOKEN
echo
ask        "2a. Registry service-account username (NNNNNNN|name)"    REG_USER
ask_secret "2b. Registry service-account token"                      REG_TOKEN
echo
ask        "3.  Git repository URL [https://github.com/anurag-saran/upgrade-delta]" REPO_URL
[ -z "$REPO_URL" ] && REPO_URL="https://github.com/anurag-saran/upgrade-delta"

# The base demo runs on committed fixtures — it needs NEITHER credential.
# #1 (Lightwell) is only for the real-Maven-build add-on; #2 (registry) only for signing.
HAVE_LW=0;  [ -n "${RHLN_USER:-}" ] && [ -n "${RHLN_TOKEN:-}" ] && HAVE_LW=1
HAVE_REG=0; [ -n "${REG_USER:-}" ]  && [ -n "${REG_TOKEN:-}" ]  && HAVE_REG=1

# ---- 3. verify credentials BEFORE writing --------------------------------
hr; echo "${BOLD}Verifying credentials${RESET}"
if [ "$HAVE_LW" = 1 ] && command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -u "${RHLN_USER}:${RHLN_TOKEN}" \
    'https://packages.redhat.com/lightwell/java/remediated/com/fasterxml/jackson/core/jackson-databind/2.13.4.rhlw-00001/jackson-databind-2.13.4.rhlw-00001.jar' 2>/dev/null || echo 000)
  case "$code" in
    200|302) ok "Lightwell console creds work (HTTP $code)";;
    401|403) bad "Lightwell creds rejected (HTTP $code) — check #1 username/token"; FAIL=1;;
    *)       warn "Lightwell check inconclusive (HTTP $code) — continuing";;
  esac
elif [ "$HAVE_LW" = 0 ]; then
  warn "No console creds — skipping the Lightwell secret. Base demo runs on fixtures; add #1 later for the real-jar build."
fi
if [ "$HAVE_REG" = 1 ]; then
  warn "Registry creds are stored now; verify locally with Podman if you want:"
  printf "      ${DIM}podman login registry.redhat.io --username '%s' --password <token>${RESET}\n" "$REG_USER"
else
  warn "No registry creds — skipping the pull secret. Only the signing add-on needs it."
fi

if [ "${FAIL:-0}" = "1" ]; then
  echo; bad "Fix the failed credential(s) above and re-run. Nothing was written."; exit 1
fi

# ---- 4. write cluster + local state --------------------------------------
hr; echo "${BOLD}Applying to cluster '${NS}'${RESET}"
oc get project "$NS" >/dev/null 2>&1 || oc new-project "$NS" >/dev/null
oc project "$NS" >/dev/null; ok "namespace ${NS}"

# 4a. Lightwell Maven settings secret (only if console creds provided)
if [ "$HAVE_LW" = 1 ]; then
  TMP_SETTINGS=$(mktemp)
  cat > "$TMP_SETTINGS" <<XML
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <servers><server>
    <id>lightwell-remediated</id>
    <username>${RHLN_USER}</username>
    <password>${RHLN_TOKEN}</password>
  </server></servers>
</settings>
XML
  oc delete secret lightwell-maven-settings -n "$NS" >/dev/null 2>&1 || true
  oc create secret generic lightwell-maven-settings --from-file=settings.xml="$TMP_SETTINGS" -n "$NS" >/dev/null
  rm -f "$TMP_SETTINGS"; ok "Secret lightwell-maven-settings"
else
  warn "skipped Secret lightwell-maven-settings (no console creds)"
fi

# 4b. Red Hat registry pull secret + link to pipeline SA (only if registry creds provided)
if [ "$HAVE_REG" = 1 ]; then
  oc delete secret redhat-registry -n "$NS" >/dev/null 2>&1 || true
  oc create secret docker-registry redhat-registry \
    --docker-server=registry.redhat.io \
    --docker-username="$REG_USER" --docker-password="$REG_TOKEN" -n "$NS" >/dev/null
  ok "Secret redhat-registry"
  oc secrets link pipeline redhat-registry --for=pull -n "$NS" >/dev/null 2>&1 \
    && ok "linked redhat-registry to 'pipeline' SA" \
    || warn "could not link to 'pipeline' SA yet (created after first PipelineRun) — re-run: oc secrets link pipeline redhat-registry --for=pull -n ${NS}"
else
  warn "skipped Secret redhat-registry (no registry creds)"
fi

# 4c. local env file for the shell scripts
cat > "$ENVFILE" <<ENV
# generated by setup-openshift.sh — DO NOT COMMIT (already in .gitignore)
# Re-running setup reads these back, so you won't be re-prompted.
export RHLN_USER='${RHLN_USER}'
export RHLN_TOKEN='${RHLN_TOKEN}'
export REG_USER='${REG_USER}'
export REG_TOKEN='${REG_TOKEN}'
export RHLN_REPO='https://packages.redhat.com/lightwell/java/remediated'
export UPGRADE_DELTA_REPO_URL='${REPO_URL}'
ENV
chmod 600 "$ENVFILE"; ok "wrote ${ENVFILE} (chmod 600) — 'source ${ENVFILE}' for local scripts"

# ensure it's gitignored
grep -qxF "$ENVFILE" .gitignore 2>/dev/null || echo "$ENVFILE" >> .gitignore

# 4d. patch the Repository CR url if it differs
if [ -f integration/tekton/pac/repository.yaml ] && [ "$REPO_URL" != "https://github.com/anurag-saran/upgrade-delta" ]; then
  sed -i.bak "s|url: \".*\"|url: \"${REPO_URL}\"|" integration/tekton/pac/repository.yaml && rm -f integration/tekton/pac/repository.yaml.bak
  ok "updated repository.yaml url"
fi

# ---- 5. apply gate + tasks (no creds, safe to automate) ------------------
hr; echo "${BOLD}Applying pipeline resources${RESET}"

apply_if(){ # apply a file, report, don't abort the whole script on one failure
  local f="$1" desc="$2"
  if [ -f "$f" ]; then
    if oc apply -f "$f" -n "$NS" >/dev/null 2>&1; then ok "$desc"
    else bad "$desc — 'oc apply -f $f' failed (see: oc apply -f $f -n $NS)"; fi
  else warn "$desc — file missing: $f (extract the latest zip over your repo)"; fi
}

apply_if integration/tekton/pac/approval-rbac.yaml        "approval RBAC (Role + binding)"
apply_if integration/tekton/pac/approval-gate-manual.yaml "CAB approval gate (manual/portable)"
apply_if integration/tekton/task-upgrade-delta.yaml          "task: upgrade-delta (combined, legacy)"
apply_if integration/tekton/task-upgrade-delta-coverage.yaml "task: upgrade-delta coverage"
apply_if integration/tekton/task-upgrade-delta-scan.yaml     "task: upgrade-delta scan"
apply_if integration/tekton/task-upgrade-delta-select-tests.yaml "task: upgrade-delta select-tests"
apply_if integration/tekton/task-upgrade-delta-run-tests.yaml    "task: upgrade-delta run-tests"
apply_if integration/tekton/task-upgrade-delta-summary.yaml  "task: upgrade-delta summary"
apply_if integration/tekton/task-upgrade-delta-pr-comment.yaml "task: upgrade-delta PR comment (CAB)"
apply_if integration/tekton/real-pipeline/task-cab-decision.yaml "task: cab-decision (A/B auto · C human)"
apply_if integration/tekton/real-pipeline/task-build-payments-image.yaml "task: build-payments-image"
apply_if integration/tekton/real-pipeline/task-canary-rollout.yaml "task: canary-rollout"
apply_if integration/tekton/real-pipeline/pipeline-real.yaml "pipeline: upgrade-delta-live"
apply_if integration/tekton/rhtas/task-sign-evidence.yaml   "task: cosign sign (RHTAS)"
apply_if integration/tekton/rhtas/task-verify-evidence.yaml "task: cosign verify (RHTAS)"

# reports PVC + scorecard viewer (the PR pipeline's workspace + the HTML viewer).
# NOTE: the PVC needs an RWX StorageClass for the viewer to share it — see deploy/README.md.
apply_if deploy/10-reports-pvc.yaml                         "reports PVC (upgrade-delta-reports)"
apply_if deploy/11-live-reports-pvc.yaml                    "live reports PVC (payments-service)"
apply_if deploy/12-live-reports-pvc-notests.yaml            "live reports PVC (payments-service-notests)"
apply_if deploy/20-scorecard-viewer-deployment.yaml        "scorecard viewer (nginx)"
apply_if deploy/21-scorecard-viewer-notests-deployment.yaml "scorecard viewer notests (nginx)"
apply_if deploy/22-scorecard-route.yaml                    "scorecard route"
apply_if deploy/23-scorecard-route-notests.yaml            "scorecard route notests"
apply_if deploy/40-canary-cab-rbac.yaml                    "CAB + canary RBAC (Role + binding)"

# git-clone from the Tekton catalog (needs network egress from your machine)
printf "  ${DIM}fetching git-clone task...${RESET}\n"
if oc apply -f https://raw.githubusercontent.com/tektoncd/catalog/main/task/git-clone/0.9/git-clone.yaml -n "$NS" >/dev/null 2>&1; then
  ok "task: git-clone"
else
  warn "git-clone apply failed — apply it manually:"
  printf "      ${DIM}oc apply -f https://raw.githubusercontent.com/tektoncd/catalog/main/task/git-clone/0.9/git-clone.yaml -n %s${RESET}\n" "$NS"
fi

# ---- 6. detect Pipelines-as-Code (can't hardcode enable across versions) --
hr; echo "${BOLD}Checking Pipelines-as-Code${RESET}"
PAC_PODS=$(oc get pods -A 2>/dev/null | grep -i "pipelines-as-code" | grep -i running | wc -l | tr -d ' ')
if [ "${PAC_PODS:-0}" -gt 0 ]; then
  ok "Pipelines-as-Code is running (${PAC_PODS} pod(s))"
  PAC_READY=1
else
  bad "Pipelines-as-Code is NOT running — PR triggers won't work until it is"
  echo "     Find whether it exists and how to enable it on your version:"
  printf "       ${DIM}oc get pods -A | grep -i pipelines-as-code${RESET}\n"
  printf "       ${DIM}oc get namespace | grep -i pipelines${RESET}\n"
  printf "       ${DIM}oc explain tektonconfig.spec.platforms.openshift${RESET}\n"
  PAC_READY=0
fi

# ---- 7. the only genuinely-manual steps left -----------------------------
hr; echo "${BOLD}${GREEN}Automated setup complete.${RESET} Two manual steps remain:"
cat <<NEXT

  ${BOLD}A. Connect GitHub${RESET}  ${DIM}(interactive OAuth — no script can click through it)${RESET}
       opc pac bootstrap
       oc apply -f integration/tekton/pac/repository.yaml
       ${YELLOW}Then also do docs/INSTALL-OPENSHIFT.md step 5${RESET} (give the Repository a provider
       token). The App above lets GitHub *send* events in; without step 5 every event fails
       with "cannot get secret from repository" even though the App looks fine.
NEXT
if [ "${PAC_READY:-0}" = "0" ]; then
  printf "     ${YELLOW}Note:${RESET} enable Pipelines-as-Code first (see the check above), or
"
  printf "     'opc pac bootstrap' will have nothing to wire the webhook into.
"
fi
cat <<NEXT

  ${BOLD}B. Open a PR against main${RESET}  → the run starts automatically. Watch it in the
     console (Pipelines → PipelineRuns); the grade/coverage/tests show on the Results tab.

  ${DIM}Everything else (namespace, secrets, tasks, git-clone, reports PVC, viewer) is applied.${RESET}
  Prefer the fully-console setup? See docs/INSTALL-OPENSHIFT.md.
  Optional CAB approval / signing: integration/tekton/pac/README.md · rhtas/README.md · CREDENTIALS.md

  ${DIM}Reminder: rotate any token that previously passed through a chat, and set the reports${RESET}
  ${DIM}PVC's storageClassName to an RWX class if the viewer pod stays Pending.${RESET}
NEXT
hr
