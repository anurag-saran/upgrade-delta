# Tekton / OpenShift Pipelines integration

Object-by-object enablement guide (Pipeline, Tasks, PVC, PaC, Results, live path):
[`docs/TEKTON-ENABLEMENT.md`](../../docs/TEKTON-ENABLEMENT.md).

## Layout

| Path | Role |
|---|---|
| `pipeline-demo.yaml` + `task-upgrade-delta-*.yaml` | Console **fixture** demo (committed `examples/`) |
| `real-pipeline/` | **Live** pom-diff pipeline (vendor into the app repo as `.upgrade-delta/`) |
| `pac/` | Pipelines-as-Code repository / approval notes |
| `rhtas/` | Optional Sigstore / RHTAS signing |

Legacy monolithic manifests (`task-upgrade-delta.yaml`, `pipeline-upgrade-delta.yaml`) remain
for older enablement paths; prefer `pipeline-demo.yaml` for the console demo.

## Demo runbook (self-contained — one Python image, no JDK, no fetches)

The demo pipeline uses only committed fixtures (`examples/evidence/` —
json-path, snakeyaml, spring-core — plus `examples/demo-jars/payments-service*`,
`examples/tests/`, `catalogs/`), so a fresh clone is enough.
Push this repo to your git, then:

```bash
oc new-project upgrade-delta-demo
oc apply -f integration/tekton/pipeline-demo.yaml \
  -f integration/tekton/task-upgrade-delta-coverage.yaml \
  -f integration/tekton/task-upgrade-delta-scan.yaml \
  -f integration/tekton/task-upgrade-delta-select-tests.yaml \
  -f integration/tekton/task-upgrade-delta-run-tests.yaml \
  -f integration/tekton/task-upgrade-delta-summary.yaml \
  -f integration/tekton/task-upgrade-delta-pr-comment.yaml
# Prefer PaC (.tekton/pull-request.yaml) or:
# oc create -f integration/tekton/pipelinerun-demo.yaml
tkn pipelinerun logs --last -f
tkn pipelinerun describe --last
```

Expected results on the run (real-library corpus):
`PROJECT_GRADE=F · COVERAGE_PCT=59 · COVERED=16 NEAR=1 UNCOVERED=10` ·
`TEST_METHODS_PASSED=9 · FAILED=0` —
snakeyaml grades F (reachable removed API). Scan uses an empty `fail-on`; the
PipelineRun goes red at **grade-gate** after tests (`fail-on: D`) so scorecard.html
and the PR comment still carry pass/fail.

## Live path (payments-service)

See [`docs/DEMO-LIVE-POM.md`](../../docs/DEMO-LIVE-POM.md) and `real-pipeline/README.md`.
The live app is the sibling **payments-service** repo (`.upgrade-delta/` + `.tekton/pull-request-live.yaml`).
