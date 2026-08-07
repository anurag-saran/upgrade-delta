# Live demo — open a PR that bumps `pom.xml`

End-to-end walkthrough for the **live** pipeline: a real dependency version change
in `pom.xml` → fetch old/new jars → grade → select/run tests → grade-gate → PR comment.

This is **not** the fixture demo (SBOM / README PR). That path is
[`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md). Concepts: [`DEMO-101.md`](DEMO-101.md).  
Full engineering detail: [`../integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md).

| | Fixture demo | Live pom demo |
|---|---|---|
| Trigger file | `.tekton/pull-request.yaml` | `.tekton/pull-request-live.yaml` (in the **app** repo) |
| Pipeline | `upgrade-delta-demo` | `upgrade-delta-live` |
| What you change | SBOM / README (any small PR) | A **dependency version** in `pom.xml` |
| What gets graded | Committed `examples/` fixtures | The app jar built from the PR + real Central/Lightwell jars |
| PVC | `upgrade-delta-reports` | `upgrade-delta-live-reports` (separate on purpose) |

---

## One-time setup (do this once)

### A. Cluster pieces

1. Fixture demo already installed? Keep it. Live is additive.
2. Apply the live reports PVC:
   ```bash
   oc apply -f deploy/11-live-reports-pvc.yaml -n upgrade-delta-demo
   ```
3. Apply live Pipeline + Tasks (from this tool repo, or after you copy `.upgrade-delta/`):
   ```bash
   oc apply -n upgrade-delta-demo \
     -f integration/tekton/real-pipeline/pipeline-real.yaml \
     -f integration/tekton/real-pipeline/task-detect-pom-changes.yaml \
     -f integration/tekton/real-pipeline/task-live-coverage.yaml \
     -f integration/tekton/real-pipeline/task-generate-evidence.yaml \
     -f integration/tekton/real-pipeline/task-resolve-and-grade-transitive.yaml \
     -f integration/tekton/real-pipeline/task-run-tests-maven.yaml \
     -f integration/tekton/real-pipeline/task-upgrade-delta-select-tests.yaml \
     -f integration/tekton/real-pipeline/task-upgrade-delta-summary.yaml \
     -f integration/tekton/real-pipeline/task-upgrade-delta-pr-comment.yaml
   ```
4. **Maven settings Secret** `lightwell-maven-settings` in the namespace — `settings.xml`
   with a server id `lightwell-remediated` and your console.redhat.com token (same pattern
   as `sample-app`). Without it, jar fetch from Lightwell fails.

### B. Wire the **application** repo (or this repo’s `sample-app`)

**Recommended hero path for enablement:** use this monorepo’s [`sample-app/`](../sample-app/)
(payments-service). Jackson is left on community **2.13.4** on purpose so a Lightwell
adoption PR is one property edit.

1. Copy the vendored bundle to the **root of the repo that owns the pom** (for the
   upgrade-delta monorepo itself, that is still the repo root):
   ```bash
   # From the upgrade-delta clone — .upgrade-delta/ is already present at repo root.
   # For a *different* app repo:
   cp -R .upgrade-delta /path/to/your-app/
   mkdir -p /path/to/your-app/.tekton
   cp .upgrade-delta/real-pipeline/pull-request-live.yaml \
      /path/to/your-app/.tekton/pull-request-live.yaml
   ```
2. Edit `.tekton/pull-request-live.yaml` params to match the app:
   | Param | `sample-app` in this repo | Your app |
   |---|---|---|
   | `app-name` | `payments-service` | your name |
   | `app-module-dir` | `sample-app` | `.` or module path |
   | `pom-path` | `sample-app/pom.xml` | `pom.xml` |
   | `coverage-map` | `sample-app/coverage-map.json` (or leave; falls open to full suite) | your map or default |
   | `tests-dir` | `sample-app/src/test/java` | `src/test/java` |
   | `scorecard-route-host` | your Route host (optional) | optional |
3. PaC **Repository** CR must point at the GitHub repo that contains
   `.tekton/pull-request-live.yaml` (same App install pattern as
   [`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md) steps 4–6).
4. Commit the `.upgrade-delta/` + `.tekton/pull-request-live.yaml` to that repo’s `main`
   **before** you open the bump PR (so PaC can resolve Task YAMLs from the PR head).

> **Both pipelines on one PR:** If this monorepo has *both* `.tekton/pull-request.yaml`
> and `.tekton/pull-request-live.yaml`, a single PR can start **fixture** and **live**
> runs. That is OK — they use different PVCs. Expect two checks / two PipelineRuns.

---

## The PR (the whole point)

### Hero edit (`sample-app`)

On GitHub (or locally), create a branch and change **one** property in
`sample-app/pom.xml`:

```xml
<!-- before (baseline on main) -->
<jackson.version>2.13.4</jackson.version>

<!-- after (Lightwell adoption) -->
<jackson.version>2.13.4.rhlw-00001</jackson.version>
```

Reference copy of the after-state (do not merge as baseline): `sample-app/pom-demo-trigger.xml`
already has `<jackson.version>2.13.4.rhlw-00001</jackson.version>` — useful to diff against
`pom.xml` when preparing the PR.

Open a pull request into `main`.

> Say: *“Developer bumps jackson-databind to the remediated build. That’s the only human
> action — the live pipeline diffs real jars and grades this app.”*

### Any other app

Bump any `<version>` (or property that resolves to one) under `<dependencies>` /
`<dependencyManagement>` that you want graded. Lightwell adoptions
(`…rhlw-NNNNN` / `…redhat-NNNNN`) are first-class; plain Central bumps work too.

---

## What to watch on the cluster

PipelineRun name pattern: **`upgrade-delta-live-pr-…`** (not `upgrade-delta-pr`).

| Step | What it means |
|---|---|
| `detect-pom-changes` | Sees the jackson (or other) version delta → `HAS_CHANGE=true` |
| `live-coverage` | Catalog meter on the **PR’s** pom |
| `generate-evidence` | Downloads old+new jars, `analyze` → `out/evidence/`, `scan` (fail-on empty) |
| `grade-transitive` | Grades transitive version shifts the bump pulled in |
| `select-tests` / `run-tests` | Router + **Maven Surefire** (not MiniRunner) |
| `grade-gate` | Fails the run if project grade ≥ `fail-on` (default **D**) |
| `summary` / `pr-comment` | VERDICT banner + CAB comment with test plan/results |

**Results tab:** `VERSION_CHANGES_COUNT`, `PROJECT_GRADE_RECOMMENDED_PATH`,
`EVIDENCE_COUNT`, `TRANSITIVE_CHANGES_COUNT`, plus test counts when selection ran.

**If the PR does not change any dependency version:** live pipeline passes through with
an empty scorecard (`HAS_CHANGE=false` skips generate/tests/gate).

---

## Expected outcomes (jackson Lightwell adoption)

Exact grade depends on reachability in `sample-app` and the published delta for that
pair — read the scorecard, don’t memorize a letter. You should see:

1. `detect-pom-changes` reporting a Lightwell adoption for jackson-databind.
2. At least one evidence JSON under `out/evidence/` on the live PVC.
3. A scorecard + PR comment for **this** bump (not the fixture snakeyaml F story).
4. Pipeline red only if grade ≥ D **or** Surefire failed — same “gate after tests” shape
   as the fixture demo.

Offline fixture numbers (F / 59% / 9 tests) are **unrelated** to this live PR.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No live PipelineRun | `.tekton/pull-request-live.yaml` missing on the PR head; Repository URL wrong; App not installed on this repo |
| `cannot find referenced task` | Every Task path must appear in PaC `task-N` annotations (already set in shipped `pull-request-live.yaml`) |
| Maven / Lightwell 401 | Secret `lightwell-maven-settings` missing or bad token |
| PVC multi-attach / wiped workspace | Do **not** share `upgrade-delta-reports` with live — use `upgrade-delta-live-reports` |
| Fixture check green/red, confused | You’re looking at `upgrade-delta-pr` (fixtures). Open the **live** run |
| `HAS_CHANGE=false` | Diff didn’t touch a resolvable dependency version (property-only noise, parent BOM, etc.) |

---

## Related docs

| Doc | Use |
|---|---|
| [`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md) | Fixture demo (`./demo.sh` + SBOM/README PR) |
| [`../integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md) | Full live setup + limits (BOM / parent POM) |
| [`TEKTON-ENABLEMENT.md`](TEKTON-ENABLEMENT.md) | Object catalog for both pipelines |
| [`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md) | PaC GitHub App once |
