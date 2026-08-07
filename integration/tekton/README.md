# Tekton / OpenShift Pipelines integration

Three manifests:
- `task-upgrade-delta.yaml` — coverage meter + project scan; emits Tekton **results**
  (`PROJECT_GRADE`, `COVERAGE_PCT`, `COVERED/NEAR/UNCOVERED`) and fails the run when the
  grade breaches `fail-on` (the scan's exit 2 becomes a red PipelineRun).
- `task-upgrade-delta-route.yaml` — the test router; exit 3 (mandatory test unresolvable)
  fails the run loudly, exactly as designed.
- `pipeline-upgrade-delta.yaml` — chains them and re-exports the numbers as
  **PipelineRun results**, which is where the "summary of libraries and risk score" lives:
  the OpenShift Pipelines console shows results on the run page, and
  `tkn pipelinerun describe <run>` prints them in the Results table. The HTML
  reports (coverage card, scorecard, app-report) land in the workspace — attach the PVC
  or upload them as artifacts in a follow-on task.

## Demo runbook (self-contained — one Python image, no JDK, no fetches)

The demo pipeline uses only committed fixtures (`examples/evidence/` —
json-path, snakeyaml, spring-core — plus `examples/demo-jars/payments-service*`,
`examples/tests/`, `catalogs/`), so a fresh clone is enough.
Push this repo to your git, then:

```bash
oc new-project upgrade-delta-demo
oc apply -f integration/tekton/task-upgrade-delta.yaml          -f integration/tekton/task-upgrade-delta-route.yaml          -f integration/tekton/pipeline-demo.yaml
# edit git-url in pipelinerun-demo.yaml, then:
oc create -f integration/tekton/pipelinerun-demo.yaml
tkn pipelinerun logs --last -f
tkn pipelinerun describe --last     # <- the summary: grade, coverage %, tests
```

Expected results on the run (real-library corpus):
`PROJECT_GRADE=F · COVERAGE_PCT=59 · COVERED=16 NEAR=1 UNCOVERED=10` ·
`TEST_METHODS_PASSED=9 · FAILED=0` —
snakeyaml grades F (reachable removed `Constructor(TypeDescription, Collection)`).
Scan uses an empty `fail-on`; the PipelineRun goes red at **grade-gate** after tests
(`fail-on: D`) so scorecard.html and the PR comment still carry pass/fail.
That red run is the demo: coverage.html and scorecard.html both use
`examples/demo-jars/payments-service.sbom.json`. Also needs `examples/demo-jars/lib/`
on the MiniRunner classpath (wired in `upgrade-delta-run-tests`).

Scorecard rows (when you inspect `out/scorecard.json` / the HTML card):
spring-core → B (1 call site), json-path → C (1 call site), snakeyaml → F (4 call sites, incompatible-reachable).

Two live demo levers: the grade gate above; untag `BootSmokeIT`
in `examples/tests/` and the route task fails with exit 3 (the mandatory-test
contract). A red PipelineRun is part of the demo, not a bug.

If the `git-clone` cluster resolver isn't available on your Pipelines version,
install it once: `tkn hub install task git-clone` and change the taskRef to
`{name: git-clone}`.

Trigger: with Pipelines-as-Code, bind the pipeline to Renovate/Dependabot branches so
every dependency-update PR gets scored automatically.

Sealing: on OpenShift, prefer **Tekton Chains** over the tool's local `seal` — Chains
signs TaskRun results and produces SLSA provenance with cluster-managed keys/Sigstore,
which is the production version of exactly what `upgrade_delta.py seal` does locally.
Note the symmetry with the artifacts themselves: Lightwell ships
`*.provenance.sigstore.json` per package; Chains gives your *scan results* the same
treatment, so both ends of the chain carry Sigstore provenance.


## Cluster shakedown notes
- `git-clone` must be installed first: `oc apply -f https://raw.githubusercontent.com/tektoncd/catalog/main/task/git-clone/0.9/git-clone.yaml`
- set a real `git-url` in `pipelinerun-demo.yaml` (default is a placeholder)
