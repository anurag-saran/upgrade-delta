# Live demo — open a PR that bumps `pom.xml`

End-to-end walkthrough for the **live** pipeline: a real dependency version change
in `pom.xml` → fetch old/new jars → grade → select/run tests → grade-gate → PR comment
→ **reset** so the next demo can bump again.

The live app is the sibling repo **[payments-service](https://github.com/anurag-saran/payments-service)**
(not vendored inside this tool repo). Offline fixture demos still use `examples/demo-jars/`.

This is **not** the fixture demo (SBOM / README PR). That path is
[`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md). Concepts: [`DEMO-101.md`](DEMO-101.md).  
Full engineering detail: [`../integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md).

| | Fixture demo (this repo) | Live pom demo (payments-service) |
|---|---|---|
| Trigger file | `.tekton/pull-request.yaml` | `payments-service/.tekton/pull-request-live.yaml` |
| Pipeline | `upgrade-delta-demo` | `upgrade-delta-live` |
| What you change | SBOM / README (any small PR) | A **dependency version** in `pom.xml` |
| What gets graded | Committed `examples/` fixtures | The app jar built from the PR + real Central/Lightwell jars |
| PVC | `upgrade-delta-reports` | `upgrade-delta-live-reports` (separate on purpose) |
| Reset for next time | n/a (fixtures always grade) | **Close PR without merge** — main stays on community jackson |

---

## Recommended demo cycle (repeatable)

In **payments-service**, `pom.xml` on **main** keeps community jackson **`2.13.4`**. Each demo opens a
PR that adopts Lightwell, then closes that PR so main never stays on `.rhlw-…`.

```bash
# From upgrade-delta (wrapper) or from payments-service directly:
./scripts/demo-live-cycle.sh start     # needs sibling ../payments-service
# …watch upgrade-delta-live-pr-… on the cluster…
./scripts/demo-live-cycle.sh finish
```

**Never merge** the demo PR. Merging would leave main on Lightwell and the next
`start` would have nothing to bump.

Reference after-state (do not commit as baseline): `payments-service/pom-demo-trigger.xml`.

`auto-close-pr` may be `true` on payments-service (live-only). Keep it `false` if a repo
also runs the fixture demo on the same PR.

---

## One-time setup (do this once)

### A. Cluster pieces

1. Fixture demo already installed? Keep it. Live is additive.
2. Apply the live reports PVC:
   ```bash
   oc apply -f deploy/11-live-reports-pvc.yaml -n upgrade-delta-demo
   ```
3. Apply live Pipeline + Tasks from this repo (`integration/tekton/real-pipeline/…`).
4. **Maven settings Secret** `lightwell-maven-settings` — server id `lightwell-remediated`.

### B. Wire payments-service

`payments-service` already vendors `.upgrade-delta/` and `.tekton/pull-request-live.yaml`
(app-module-dir `.`, pom-path `pom.xml`). Refresh the bundle anytime:

```bash
# from payments-service
./scripts/pull-upgrade-delta-bundle.sh
```

Register the payments-service repo with Pipelines-as-Code in the same namespace
([`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md)).

---

## Manual PR (without the script)

In **payments-service**, on a branch from main, edit `pom.xml`:

```xml
<jackson.version>2.13.4.rhlw-00001</jackson.version>
```

Open a PR into `main`, watch `upgrade-delta-live-pr-…`, then **close without merging**
(or run `./scripts/demo-live-cycle.sh finish`).

---

## What “good” looks like

- Scorecard grades the jackson adoption (typically B for drop-in Lightwell rebuild).
- Selected Surefire tests run against the built jar.
- PR comment posted; optional auto-close when configured.

## Troubleshooting

| Symptom | Check |
|---|---|
| Live PipelineRun never starts | PaC Repository for **payments-service**; `.tekton/pull-request-live.yaml` on the PR branch |
| Maven resolve failures | `lightwell-maven-settings` secret; public demo repos in `pom.xml` |
| Wrong app graded | `app-module-dir: '.'` and `pom-path: pom.xml` on the live trigger |
| `demo-live-cycle.sh` missing app | Clone payments-service as sibling or set `PAYMENTS_SERVICE_DIR` |
