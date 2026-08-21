# Live demo — open a PR that bumps `pom.xml`

End-to-end walkthrough for the **live** pipeline: a real dependency version change
in `pom.xml` → fetch old/new jars → grade → select/run tests → grade-gate → **CAB
decision** (A/B auto-signoff, C human) → optional **progressive canary** → PR comment
→ **reset** so the next demo can bump again.

There are **four** sibling live apps (not vendored inside this tool repo):

| | **With tests (B)** | **REACHABILITY_ONLY** | **Grade C / human CAB** | **Grade F / gate fail** |
|---|---|---|---|---|
| Repo | [payments-service](https://github.com/anurag-saran/payments-service) | [payments-service-notests](https://github.com/anurag-saran/payments-service-notests) | [payments-service-grade-c](https://github.com/anurag-saran/payments-service-grade-c) | [payments-service-grade-f](https://github.com/anurag-saran/payments-service-grade-f) |
| Hero bump | jackson `2.13.4` → `.rhlw` (validated drop-in) | Same jackson bump; empty tests | json-path `2.7.0` → `2.8.0.rhlw-00001` (base-version) | snakeyaml `1.30` → `1.33` (community) |
| Expected headline | **B** (auto CAB) | **REACHABILITY_ONLY** honesty | **C** (human CAB wait) | **F** (grade-gate fails) |
| PipelineRun name | `upgrade-delta-live-pr` | `upgrade-delta-live-pr-notests` | `upgrade-delta-live-pr-gradec` | `upgrade-delta-live-pr-gradef` |
| PVC | `upgrade-delta-live-reports` | `upgrade-delta-live-reports-notests` | `upgrade-delta-live-reports-gradec` | `upgrade-delta-live-reports-gradef` |
| Scorecard Route | `scorecard` | `scorecard-notests` | `scorecard-gradec` | `scorecard-gradef` |
| Typical host | `scorecard-upgrade-delta-demo.apps…` | `scorecard-notests-upgrade-delta-demo.apps…` | `scorecard-gradec-upgrade-delta-demo.apps…` | `scorecard-gradef-upgrade-delta-demo.apps…` |
| Demo cycle | `./scripts/demo-live-cycle.sh` | `./scripts/demo-live-cycle.sh` | `./scripts/demo-live-cycle.sh` | `./scripts/demo-live-cycle.sh` |

**Slide-only A:** json-path same-base remidiation (`2.8.0` → `2.8.0.rhlw-00001`) grades **A** in
jar evidence (`.e2e-grade-scan/SPEAKER-CHEATSHEET-REMEDIATED.md`). It is **not** a fifth
live app — the soft live lane with tests remains jackson → **B** (validated).

Offline fixture demos still use `examples/demo-jars/`.

This is **not** the fixture demo (SBOM / README PR). That path is
[`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md). Concepts: [`DEMO-101.md`](DEMO-101.md).  
Full engineering detail: [`../integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md).

| | Fixture demo (this repo) | Live pom (with tests) | Live pom (no tests) | Live pom (grade C) | Live pom (grade F) |
|---|---|---|---|---|---|
| Trigger file | `.tekton/pull-request.yaml` | `payments-service/.tekton/pull-request-live.yaml` | `payments-service-notests/.tekton/pull-request-live.yaml` | `payments-service-grade-c/.tekton/pull-request-live.yaml` | `payments-service-grade-f/.tekton/pull-request-live.yaml` |
| Pipeline | `upgrade-delta-demo` | `upgrade-delta-live` | `upgrade-delta-live` | `upgrade-delta-live` | `upgrade-delta-live` |
| What you change | SBOM / README (any small PR) | A **dependency version** in `pom.xml` | Same | json-path **only** (never snakeyaml) | snakeyaml **only** (never json-path) |
| What gets graded | Committed `examples/` fixtures | App jar + Central/Lightwell jars + Surefire | App jar + Central/Lightwell jars; **no Surefire** | App jar + jars + Surefire; headline **C** | App jar + jars; headline **F** |
| PVC | `upgrade-delta-reports` | `upgrade-delta-live-reports` | `upgrade-delta-live-reports-notests` | `upgrade-delta-live-reports-gradec` | `upgrade-delta-live-reports-gradef` |
| Reset for next time | n/a | **Close PR without merge** | **Close PR without merge** | **Close PR without merge** | **Close PR without merge** |

---

## Four live demos — how the presenter switches

Use **separate PRs in separate repos** so scorecards never race on one PVC.

**A. With tests (normal Surefire + grade B)**

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

**C. Grade C / human CAB (json-path base-version bump)**

```bash
cd ../payments-service-grade-c
./scripts/demo-live-cycle.sh start
# Watch: PipelineRun upgrade-delta-live-pr-gradec-…
# Scorecard: https://scorecard-gradec-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html
# When cab-decision waits:
oc create configmap upgrade-delta-cab-approved -n upgrade-delta-demo \
  --from-literal=approved=true
./scripts/demo-live-cycle.sh finish
```

Talking points for C: json-path `2.7.0` → `2.8.0.rhlw-00001` is a **base-version** move
(not a same-base Lightwell rebuild), so the headline is **C**. Grade-gate still passes
(`fail-on: D`); auto CAB does **not** apply — the run pauses until the ConfigMap exists.
Do **not** bump snakeyaml in this lane (that headlines **F** and fails the gate).

**D. Grade F / gate fail (community snakeyaml reachable break)**

```bash
cd ../payments-service-grade-f
./scripts/demo-live-cycle.sh start
# Watch: PipelineRun upgrade-delta-live-pr-gradef-…
# Scorecard: https://scorecard-gradef-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html
# Expect: headline F → grade-gate fails (fail-on D)
./scripts/demo-live-cycle.sh finish
```

Talking points for D: snakeyaml `1.30` → `1.33` (community, no `.rhlw`) removes
`Constructor(TypeDescription, Collection)`; `ConfigLoader` reaches it → **F**. Same
library on the grade-C lane stays at `1.30` so C and F never collide.

All four scorecard viewers stay up at the same time — open four browser tabs.

---

## Recommended demo cycle (repeatable)

Each live app keeps community pins on **main**. Each demo opens a PR that bumps the
hero dependency, then closes that PR so main never stays on the demo target.

```bash
# From the chosen app repo:
./scripts/demo-live-cycle.sh start
# …watch upgrade-delta-live-pr-… / -notests-… / -gradec-… / -gradef-… on the cluster…
./scripts/demo-live-cycle.sh finish
```

**Never merge** the demo PR. Merging would leave main on the demo target and the next
`start` would have nothing to bump.

Reference after-state (do not commit as baseline): `payments-service/pom-demo-trigger.xml`.

`auto-close-pr` stays `false` on all live apps so CAB reports can be reviewed before
`finish` closes the demo PR.

---

## One-time setup (do this once)

### A. Cluster pieces

1. Fixture demo already installed? Keep it. Live is additive.
2. Apply the live reports PVCs **and** all scorecard viewers (isolation is required):
   ```bash
   oc apply -f deploy/11-live-reports-pvc.yaml \
            -f deploy/12-live-reports-pvc-notests.yaml \
            -f deploy/13-live-reports-pvc-gradec.yaml \
            -f deploy/14-live-reports-pvc-gradef.yaml \
            -f deploy/20-scorecard-viewer-deployment.yaml \
            -f deploy/21-scorecard-viewer-notests-deployment.yaml \
            -f deploy/26-scorecard-viewer-gradec-deployment.yaml \
            -f deploy/28-scorecard-viewer-gradef-deployment.yaml \
            -f deploy/22-scorecard-route.yaml \
            -f deploy/23-scorecard-route-notests.yaml \
            -f deploy/27-scorecard-route-gradec.yaml \
            -f deploy/29-scorecard-route-gradef.yaml \
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

### B. Wire payments-service (+ notests + grade-c + grade-f)

All four apps vendor `.upgrade-delta/` and `.tekton/pull-request-live.yaml`
(app-module-dir `.`, pom-path `pom.xml`). Refresh the bundle anytime:

```bash
# from any live app repo
./scripts/pull-upgrade-delta-bundle.sh
```

Register **all four** repos with Pipelines-as-Code in the same namespace
([`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md)):

```bash
oc apply -f integration/tekton/pac/repository-payments-service.yaml \
         -f integration/tekton/pac/repository-payments-service-notests.yaml \
         -f integration/tekton/pac/repository-payments-service-grade-c.yaml \
         -f integration/tekton/pac/repository-payments-service-grade-f.yaml \
         -n upgrade-delta-demo
```

Also install the GitHub App / webhook on **payments-service-notests**,
**payments-service-grade-c**, and **payments-service-grade-f** the same way as
payments-service (or `opc pac create repository` / console PaC wizard). The Repository
CR alone is not enough until the webhook delivers events for that repo URL. Reuse secret
`upgrade-delta-provider-token` (`provider.token` + `webhook.secret`).

---

## Manual PR (without the script)

In the chosen app repo, on a branch from main, edit `pom.xml`:

- **With tests / notests:** bump jackson to `2.13.4.rhlw-00001`
- **Grade C:** bump **only** json-path to `2.8.0.rhlw-00001` (leave snakeyaml alone)
- **Grade F:** bump **only** snakeyaml to `1.33` (leave json-path alone)

Open a PR into `main`, watch the matching `upgrade-delta-live-pr-…` PipelineRun,
then **close without merging** (or run `./scripts/demo-live-cycle.sh finish`).

---

## What “good” looks like

- Scorecard grades the adoption (typically **B** for jackson drop-in; **C** for
  json-path base-version on the grade-c lane; **F** for snakeyaml on the grade-f lane).
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
  obligation is **CLOSED**. All live triggers keep `enable-canary=false` while this
  cluster's Image Registry operator is Removed.
- PR comment posted (includes auto/human CAB line when signoff exists); optional auto-close
  when configured.

## Troubleshooting

| Symptom | Check |
|---|---|
| Live PipelineRun never starts | PaC Repository CR for the **correct** app repo; `.tekton/pull-request-live.yaml` on the PR branch; GitHub App / webhook installed on that repo |
| Scorecard wiped / wrong demo's HTML | Confirm PVC + Route: with-tests → `upgrade-delta-live-reports` / `scorecard`; notests → `…-notests` / `scorecard-notests`; grade-c → `…-gradec` / `scorecard-gradec`; grade-f → `…-gradef` / `scorecard-gradef` |
| Maven resolve failures | `lightwell-maven-settings` secret; public demo repos in `pom.xml` |
| Wrong app graded | `app-name`, `app-module-dir: '.'`, `pom-path: pom.xml` on the live trigger |
| `demo-live-cycle.sh` missing app | Clone the sibling app or run the script inside that repo |
| Stuck at `cab-decision` | Grade is C (or override); create `upgrade-delta-cab-approved` ConfigMap |
| Grade-c headlines F | Ensure snakeyaml was **not** bumped; only json-path |
| Grade-f does not fail | Ensure snakeyaml was bumped to `1.33` and `ConfigLoader` is in the app jar |
| Canary fails / skipped | Deployments + Route from `deploy/30-payments-canary.yaml`; SA RBAC; or set `enable-canary=false` |
| PaC “cannot find referenced task” | Annotations `task-9`…`task-11` for cab / build / canary in `.tekton/pull-request-live.yaml` |
