#!/usr/bin/env bash
# ============================================================================
#  upgrade-delta — OpenShift teardown / cleanup
#
#  Removes the demo's resources from the cluster so you can re-install cleanly
#  over a previous version. Scoped to the 'upgrade-delta-demo' namespace.
#
#  Modes:
#    ./cleanup-openshift.sh              remove app resources; KEEP namespace + credential secrets
#    ./cleanup-openshift.sh --purge      also delete the Lightwell/registry secrets
#    ./cleanup-openshift.sh --namespace  delete the WHOLE namespace (everything, incl. data)
#    ./cleanup-openshift.sh --keep-pvc   keep the reports PVC and its data
#    ./cleanup-openshift.sh --yes        don't prompt for confirmation
#  Flags combine, e.g.:  ./cleanup-openshift.sh --purge --keep-pvc
# ============================================================================
set -uo pipefail

BOLD=$'\e[1m'; GREEN=$'\e[32m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; DIM=$'\e[2m'; RESET=$'\e[0m'
NS="upgrade-delta-demo"
PAC_NS="openshift-pipelines"   # where PaC's GitHub App secret lives (left alone by default)

PURGE=0; NUKE_NS=0; KEEP_PVC=0; ASSUME_YES=0
for a in "$@"; do case "$a" in
  --purge) PURGE=1;;
  --namespace|--all) NUKE_NS=1;;
  --keep-pvc) KEEP_PVC=1;;
  --yes|-y) ASSUME_YES=1;;
  -h|--help) sed -n '2,20p' "$0"; exit 0;;
  *) echo "unknown flag: $a (see --help)"; exit 1;;
esac; done

hr(){ printf '%s\n' "────────────────────────────────────────────────────────────────"; }
ok(){ printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
warn(){ printf "  ${YELLOW}!${RESET} %s\n" "$1"; }
del(){ # del <args...>  — delete, ignore-not-found, report
  local what="$*"
  if oc delete "$@" -n "$NS" --ignore-not-found >/dev/null 2>&1; then ok "removed: $what"
  else warn "skip (not present or no perms): $what"; fi
}

# ---- preflight -------------------------------------------------------------
command -v oc >/dev/null 2>&1 || { echo "${RED}oc not found${RESET}"; exit 1; }
oc whoami >/dev/null 2>&1 || { echo "${RED}not logged in — run 'oc login ...'${RESET}"; exit 1; }
if ! oc get project "$NS" >/dev/null 2>&1; then
  echo "Namespace '$NS' does not exist — nothing to clean."; exit 0
fi

# ---- confirm ---------------------------------------------------------------
hr; echo "${BOLD}upgrade-delta cleanup${RESET}  (namespace: ${NS}, user: $(oc whoami))"
if [ "$NUKE_NS" = 1 ]; then
  echo "  ${RED}${BOLD}This will DELETE THE ENTIRE NAMESPACE '${NS}'${RESET} — all pipelines, runs,"
  echo "  the reports PVC and its data, and ALL secrets in it."
else
  echo "  This will remove the pipeline, tasks, Repository CR, viewer, approval gate,"
  echo "  and all prior PipelineRuns in '${NS}'."
  [ "$KEEP_PVC" = 1 ] && echo "  ${DIM}Keeping the reports PVC and its data (--keep-pvc).${RESET}" \
                      || echo "  ${YELLOW}Also deleting the reports PVC and its data.${RESET} (use --keep-pvc to keep)"
  [ "$PURGE" = 1 ] && echo "  ${YELLOW}Also deleting the Lightwell/registry secrets (--purge) — you'll re-enter tokens.${RESET}" \
                   || echo "  ${DIM}Keeping credential secrets (lightwell-maven-settings, redhat-registry).${RESET}"
fi
echo "  ${DIM}The OpenShift Pipelines operator and the PaC GitHub App secret in '${PAC_NS}' are left untouched.${RESET}"
if [ "$ASSUME_YES" != 1 ]; then
  printf "Proceed? type 'yes' to continue: "; read -r reply
  [ "$reply" = "yes" ] || { echo "aborted."; exit 0; }
fi

# ---- nuke-namespace path ---------------------------------------------------
hr
if [ "$NUKE_NS" = 1 ]; then
  echo "${BOLD}Deleting namespace ${NS}${RESET}"
  oc delete project "$NS" --ignore-not-found >/dev/null 2>&1 && ok "namespace ${NS} deletion requested"
  warn "namespace deletion is async — 'oc get project ${NS}' until it's gone."
  hr; echo "${GREEN}Done.${RESET}"; exit 0
fi

# ---- targeted removal ------------------------------------------------------
echo "${BOLD}PipelineRuns${RESET}"
oc delete pipelinerun --all -n "$NS" --ignore-not-found >/dev/null 2>&1 && ok "all PipelineRuns" || warn "no PipelineRuns"

echo "${BOLD}Pipeline + tasks${RESET}"
del pipeline upgrade-delta-demo
del pipeline upgrade-delta                     # alternate pipeline, if applied
for t in upgrade-delta upgrade-delta-coverage upgrade-delta-scan upgrade-delta-route \
         upgrade-delta-select-tests upgrade-delta-run-tests \
         upgrade-delta-summary upgrade-delta-pr-comment cab-approval-manual \
         sign-evidence verify-evidence git-clone; do
  del task "$t"
done

echo "${BOLD}Pipelines-as-Code Repository CR${RESET}"
del repository.pipelinesascode.tekton.dev upgrade-delta
del repository.pipelinesascode.tekton.dev payments-service
del repository.pipelinesascode.tekton.dev payments-service-notests

echo "${BOLD}CAB approval gate + RBAC${RESET}"
del approvaltask.openshift-pipelines.org upgrade-delta-cab
del role upgrade-delta-approval
del rolebinding upgrade-delta-approval
del configmap upgrade-delta-approved            # stray approval signal, if any

echo "${BOLD}Scorecard viewer${RESET}"
del route scorecard
del service scorecard-viewer
del deployment scorecard-viewer
del configmap scorecard-viewer-nginx
del route scorecard-notests
del service scorecard-viewer-notests
del deployment scorecard-viewer-notests
del configmap scorecard-viewer-notests-nginx

echo "${BOLD}Label sweep (anything else tagged part-of=upgrade-delta)${RESET}"
oc delete all,cm,role,rolebinding -l app.kubernetes.io/part-of=upgrade-delta -n "$NS" \
  --ignore-not-found >/dev/null 2>&1 && ok "label-tagged leftovers" || warn "nothing tagged"

if [ "$KEEP_PVC" != 1 ]; then
  echo "${BOLD}Reports PVC (+ data)${RESET}"
  del pvc upgrade-delta-reports
  del pvc upgrade-delta-live-reports
  del pvc upgrade-delta-live-reports-notests
  del pvc upgrade-delta-live-reports-gradec
  del pvc upgrade-delta-live-reports-gradef
fi

if [ "$PURGE" = 1 ]; then
  echo "${BOLD}Credential secrets${RESET}"
  del secret lightwell-maven-settings
  del secret redhat-registry
fi

hr
echo "${GREEN}${BOLD}Cleanup complete.${RESET} Namespace '${NS}' kept."
echo "  Re-install with:  ./setup-openshift.sh   (or console: docs/INSTALL-OPENSHIFT.md)"
[ "$KEEP_PVC" = 1 ] && echo "  ${DIM}Reports PVC kept — delete later with: oc delete pvc upgrade-delta-reports -n ${NS}${RESET}"
[ "$PURGE" != 1 ] && echo "  ${DIM}Credential secrets kept — re-run with --purge to remove them.${RESET}"
hr
