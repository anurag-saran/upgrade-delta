# Live demo — open a PR that bumps `pom.xml`

End-to-end walkthrough for the **live** pipeline: a real dependency version change
in `pom.xml` → fetch old/new jars → grade → select/run tests → grade-gate → **CAB
decision** (A/B auto-signoff, C human) → optional **progressive canary** → PR comment
→ **reset** so the next demo can bump again.

There are **two** sibling live apps (not vendored inside this tool repo):

| | **With tests** | **REACHABILITY_ONLY (no tests)** |
|---|---|---|
| Repo | [payments-service](https://github.com/anurag-saran/payments-service) | [payments-service-notests](https://github.com/anurag-saran/payments-service-notests) |
| Tests | Surefire under `src/test/java` | Empty `src/test/java` (no `*.java`) |
| PipelineRun name | `upgrade-delta-live-pr` | `upgrade-delta-live-pr-notests` |
| PVC | `upgrade-delta-live-reports` | `upgrade-delta-live-reports-notests` |
| Scorecard Route | `scorecard` | `scorecard-notests` |
| Typical host | `scorecard-upgrade-delta-demo.apps…` | `scorecard-notests-upgrade-delta-demo.apps…` |

Offline fixture demos still use `examples/demo-jars/`.

This is **not** the fixture demo (SBOM / README PR). That path is
[`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md). Concepts: [`DEMO-101.md`](DEMO-101.md).  
Full engineering detail: [`../integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md).

| | Fixture demo (this repo) | Live pom (with tests) | Live pom (no tests) |
|---|---|---|---|
| Trigger file | `.tekton/pull-request.yaml` | `payments-service/.tekton/pull-request-live.yaml` | `payments-service-notests/.tekton/pull-request-live.yaml` |
| Pipeline | `upgrade-delta-demo` | `upgrade-delta-live` | `upgrade-delta-live` |
| What you change | SBOM / README (any small PR) | A **dependency version** in `pom.xml` | Same |
| What gets graded | Committed `examples/` fixtures | App jar + Central/Lightwell jars + Surefire | App jar + Central/Lightwell jars; **no Surefire** |
| PVC | `upgrade-delta-reports` | `upgrade-delta-live-reports` | `upgrade-delta-live-reports-notests` |
| Reset for next time | n/a | **Close PR without merge** | **Close PR without merge** |

---

## Two live demos — how the presenter switches

Use **separate PRs in separate repos** so scorecards never race on one PVC.

**A. With tests (normal Surefire + grades)**

```bash
cd ../payments-service   # or set PAYMENTS_SERVICE_DIR
./scripts/demo-live-cycle.sh start
# Watch: PipelineRun upgrade-delta-live-pr-…
# Scorecard: https://scorecard-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html
./scripts/demo-live-cycle.sh finish
```

**B. REACHABILITY_ONLY (no test sources)**

```bash
cd ../payments-service-notests
./scripts/demo-live-cycle.sh start
# Watch: PipelineRun upgrade-delta-live-pr-notests-…
# Scorecard: https://scorecard-notests-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html
./scripts/demo-live-cycle.sh finish
```

Talking points for B: empty `tests-dir` → honesty path documents that tests were
*not* available; grade still comes from call-site / jar analysis (DESIGN-DECISIONS §10).
Canary remains `enable-canary=false` on this cluster (Image Registry Removed).

Both scorecard viewers stay up at the same time — open two browser tabs.

---

## Recommended demo cycle (repeatable)

In either live app, `pom.xml` on **main** keeps community jackson **`2.13.4`**. Each demo opens a
PR that adopts Lightwell, then closes that PR so main never stays on `.rhlw-…`.

```bash
# From upgrade-delta (wrapper) or from the app repo directly:
./scripts/demo-live-cycle.sh start     # needs sibling ../payments-service (or run inside notests)
# …watch upgrade-delta-live-pr-… or upgrade-delta-live-pr-notests-… on the cluster…
./scripts/demo-live-cycle.sh finish
```

**Never merge** the demo PR. Merging would leave main on Lightwell and the next
`start` would have nothing to bump.

Reference after-state (do not commit as baseline): `payments-service/pom-demo-trigger.xml`.

`auto-close-pr` stays `false` on both live apps so CAB reports can be reviewed before
`finish` closes the demo PR.

---

## One-time setup (do this once)

### A. Cluster pieces

1. Fixture demo already installed? Keep it. Live is additive.
2. Apply the live reports PVCs **and** both scorecard viewers (isolation is required):
   ```bash
   oc apply -f deploy/11-live-reports-pvc.yaml \
            -f deploy/12-live-reports-pvc-notests.yaml \
            -f deploy/20-scorecard-viewer-deployment.yaml \
            -f deploy/21-scorecard-viewer-notests-deployment.yaml \
            -f deploy/22-scorecard-route.yaml \
            -f deploy/23-scorecard-route-notests.yaml \
            -n upgrade-delta-demo
   ```
3. Apply live Pipeline + Tasks from this repo (`integration/tekton/real-pipeline/…`),
   including the new CD tasks:
   ```bash
   oc apply -f integration/tekton/real-pipeline/task-cab-decision.yaml \
            -f integration/tekton/real-pipeline/task-build-payments-image.yaml \
            -f integration/tekton/real-pipeline/task-canary-rollout.yaml \
            -f integration/tekton/real-pipeline/pipeline-real.yaml \
            -n upgrade-delta-demo
   ```
4. **Maven settings Secret** `lightwell-maven-settings` — server id `lightwell-remediated`.
5. **Baseline app packaging** (once) so canary has something to shift traffic between
   (optional while `enable-canary=false`):
   ```bash
   # from payments-service
   oc apply -f deploy/30-payments-canary.yaml -n upgrade-delta-demo
   # First image: create BuildConfig via binary build, or let the pipeline's
   # build-payments-image Task create it on the first canary run.
   ```
   Grant the pipeline ServiceAccount rights to patch Routes/Deployments, start Builds,
   and create/delete ConfigMap `upgrade-delta-cab-approved` in the demo namespace
   (`oc apply -f deploy/40-canary-cab-rbac.yaml -n upgrade-delta-demo` from upgrade-delta).

### B. Wire payments-service (+ optional notests)

Both apps vendor `.upgrade-delta/` and `.tekton/pull-request-live.yaml`
(app-module-dir `.`, pom-path `pom.xml`). Refresh the bundle anytime:

```bash
# from payments-service or payments-service-notests
./scripts/pull-upgrade-delta-bundle.sh
```

Register **both** repos with Pipelines-as-Code in the same namespace
([`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md)):

```bash
oc apply -f integration/tekton/pac/repository-payments-service.yaml \
         -f integration/tekton/pac/repository-payments-service-notests.yaml \
         -n upgrade-delta-demo
```

Also install the GitHub App / webhook on **payments-service-notests** the same way as
payments-service (or `opc pac create repository` / console PaC wizard). The Repository CR
alone is not enough until the webhook delivers events for that repo URL.

---

## Manual PR (without the script)

In **payments-service** or **payments-service-notests**, on a branch from main, edit `pom.xml`:

```xml
<jackson.version>2.13.4.rhlw-00001</jackson.version>
```

Open a PR into `main`, watch `upgrade-delta-live-pr-…` or `upgrade-delta-live-pr-notests-…`,
then **close without merging** (or run `./scripts/demo-live-cycle.sh finish`).

---

## What “good” looks like

- Scorecard grades the jackson adoption (typically B for drop-in Lightwell rebuild).
- **With tests:** selected Surefire tests run against the built jar.
- **No tests (`payments-service-notests`):** empty `tests-dir` → **REACHABILITY_ONLY** —
  grade from call-site analysis, no Surefire (see DESIGN-DECISIONS §10). Canary would be
  the compensating control when registry allows `enable-canary=true`.
- **CAB:** grade **A/B** → `out/cab-signoff.json` with `mode: auto` (no pause). Grade **C**
  → PipelineRun waits; approve with:
  ```bash
  oc create configmap upgrade-delta-cab-approved -n upgrade-delta-demo \
    --from-literal=approved=true
  # optional: oc annotate cm/upgrade-delta-cab-approved cab.approver=you@example.com
  ```
  Grade **D/F** → red at `grade-gate` (default `fail-on: D`); no CAB, no canary.
- **Canary** (when `enable-canary=true`): Route weights 1→5→10→25→50→75→100 with Ready +
  synthetic `/health` and `/api/smoke` probes; on success `deploy-gate.json` canary
  obligation is **CLOSED**. Both live triggers keep `enable-canary=false` while this
  cluster's Image Registry operator is Removed.
- PR comment posted (includes auto/human CAB line when signoff exists); optional auto-close
  when configured.

## Troubleshooting

| Symptom | Check |
|---|---|
| Live PipelineRun never starts | PaC Repository CR for the **correct** app repo; `.tekton/pull-request-live.yaml` on the PR branch; GitHub App installed on that repo |
| Scorecard wiped / wrong demo's HTML | Confirm PVC + Route: with-tests → `upgrade-delta-live-reports` / `scorecard`; notests → `…-notests` / `scorecard-notests` |
| Maven resolve failures | `lightwell-maven-settings` secret; public demo repos in `pom.xml` |
| Wrong app graded | `app-name`, `app-module-dir: '.'`, `pom-path: pom.xml` on the live trigger |
| `demo-live-cycle.sh` missing app | Clone the sibling app or run the script inside that repo |
| Stuck at `cab-decision` | Grade is C (or override); create `upgrade-delta-cab-approved` ConfigMap |
| Canary fails / skipped | Deployments + Route from `deploy/30-payments-canary.yaml`; SA RBAC; or set `enable-canary=false` |
| PaC “cannot find referenced task” | Annotations `task-9`…`task-11` for cab / build / canary in `.tekton/pull-request-live.yaml` |
