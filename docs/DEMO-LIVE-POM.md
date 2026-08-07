# Live demo — open a PR that bumps `pom.xml`

End-to-end walkthrough for the **live** pipeline: a real dependency version change
in `pom.xml` → fetch old/new jars → grade → select/run tests → grade-gate → PR comment
→ **reset** so the next demo can bump again.

This is **not** the fixture demo (SBOM / README PR). That path is
[`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md). Concepts: [`DEMO-101.md`](DEMO-101.md).  
Full engineering detail: [`../integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md).

| | Fixture demo | Live pom demo |
|---|---|---|
| Trigger file | `.tekton/pull-request.yaml` | `.tekton/pull-request-live.yaml` |
| Pipeline | `upgrade-delta-demo` | `upgrade-delta-live` |
| What you change | SBOM / README (any small PR) | A **dependency version** in `pom.xml` |
| What gets graded | Committed `examples/` fixtures | The app jar built from the PR + real Central/Lightwell jars |
| PVC | `upgrade-delta-reports` | `upgrade-delta-live-reports` (separate on purpose) |
| Reset for next time | n/a (fixtures always grade) | **Close PR without merge** — main stays on community jackson |

---

## Recommended demo cycle (repeatable)

`sample-app/pom.xml` on **main** keeps community jackson **`2.13.4`**. Each demo opens a
PR that adopts Lightwell, then closes that PR so main never stays on `.rhlw-…`.

```bash
# 1) One-time cluster setup (PVC, Tasks, Maven secret) — see below.

# 2) Start a demo — bumps jackson → 2.13.4.rhlw-00001, pushes branch, opens PR
./scripts/demo-live-cycle.sh start

# 3) Watch OpenShift → upgrade-delta-live-pr-… (and optionally the fixture run)

# 4) After the run — close PR(s) without merge; restore community jackson if needed
./scripts/demo-live-cycle.sh finish

# Optional
./scripts/demo-live-cycle.sh status
```

**Never merge** the demo PR. Merging would leave main on Lightwell and the next
`start` would have nothing to bump. `finish` also repairs main if someone merged by
mistake.

Reference after-state (do not commit as baseline): `sample-app/pom-demo-trigger.xml`.

Optional automation: set `auto-close-pr: "true"` on the live PipelineRun when this
repo runs **only** the live pipeline. In this monorepo leave it **false** — fixture and
live both fire on one PR; auto-close would cancel the other. Always use `finish` here.

---

## One-time setup (do this once)

### A. Cluster pieces

1. Fixture demo already installed? Keep it. Live is additive.
2. Apply the live reports PVC:
   ```bash
   oc apply -f deploy/11-live-reports-pvc.yaml -n upgrade-delta-demo
   ```
3. Apply live Pipeline + Tasks:
   ```bash
   oc apply -n upgrade-delta-demo \
     -f integration/tekton/real-pipeline/pipeline-real.yaml \
     -f integration/tekton/real-pipeline/task-detect-pom-changes.yaml \
     -f integration/tekton/real-pipeline/task-live-coverage.yaml \
     -f integration/tekton/real-pipeline/task-generate-evidence.yaml \
     -f integration/tekton/real-pipeline/task-resolve-and-grade-transitive.yaml \
     -f integration/tekton/real-pipeline/task-run-tests-maven.yaml \
     -f integration/tekton/task-upgrade-delta-select-tests.yaml \
     -f integration/tekton/task-upgrade-delta-summary.yaml \
     -f integration/tekton/task-upgrade-delta-pr-comment.yaml
   ```
4. **Maven settings Secret** `lightwell-maven-settings` in the namespace — `settings.xml`
   with server id `lightwell-remediated` and your console.redhat.com token.

### B. Wire the application repo

This monorepo already has `.tekton/pull-request-live.yaml` pointed at `sample-app/`.  
For a **different** app repo: copy `.upgrade-delta/`, add `.tekton/pull-request-live.yaml`,
edit params, set up PaC ([`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md)), commit to main
before the first bump PR. Keep `auto-close-pr: false` unless live is the only pipeline.

---

## Manual PR (without the script)

On a branch from main, edit `sample-app/pom.xml`:

```xml
<jackson.version>2.13.4.rhlw-00001</jackson.version>
```

Open a PR into `main`, watch `upgrade-delta-live-pr-…`, then **close without merging**
(or run `./scripts/demo-live-cycle.sh finish`).

---

## What to watch on the cluster

PipelineRun name pattern: **`upgrade-delta-live-pr-…`** (not `upgrade-delta-pr`).

| Step | What it means |
|---|---|
| `detect-pom-changes` | Sees the jackson version delta → `HAS_CHANGE=true` |
| `live-coverage` | Catalog meter on the PR pom |
| `generate-evidence` | Fetch jars, analyze, scan (fail-on empty) |
| `grade-transitive` | Transitive version shifts |
| `select-tests` / `run-tests` | Router + Maven Surefire |
| `grade-gate` | Fail if grade ≥ D |
| `summary` / `pr-comment` | VERDICT + CAB comment |

Offline fixture numbers (F / 59% / 9 tests) are **unrelated** to this live PR.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No live PipelineRun | Missing `.tekton/pull-request-live.yaml` on PR head; bad Repository URL |
| Next `start` says jackson already Lightwell | You merged the demo PR — run `finish` |
| Maven / Lightwell 401 | Secret `lightwell-maven-settings` |
| Fixture vs live confused | Fixture = `upgrade-delta-pr`; live = `upgrade-delta-live-pr` |

---

## Related docs

| Doc | Use |
|---|---|
| [`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md) | Fixture demo |
| [`../integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md) | Full live setup |
| [`TEKTON-ENABLEMENT.md`](TEKTON-ENABLEMENT.md) | Object catalog |
| [`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md) | PaC once |
