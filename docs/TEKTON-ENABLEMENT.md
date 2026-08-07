# Technical enablement — Tekton / OpenShift objects

Catalog of every Kubernetes / Tekton object the **fixture demo** and **live**
pipelines use, what it does, and how the pieces connect. For product concepts
see [`DEMO-101.md`](DEMO-101.md). For install order see
[`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md).

**Namespace used throughout:** `upgrade-delta-demo` (unless you vendor the live
pipeline into an application repo’s own project).

---

## 1. Tekton vocabulary (90 seconds)

| Kind | What it is |
|---|---|
| **Task** | Reusable recipe: one or more container steps + params + optional **results**. |
| **Pipeline** | Ordered graph of Tasks (and inline `taskSpec` steps) + shared params/workspaces. |
| **TaskRun** | One execution of a Task (created automatically when a Pipeline runs). |
| **PipelineRun** | One execution of a Pipeline — what you watch in the console. |
| **Workspace** | Shared volume mount (here: a PVC) so Tasks see the same git tree + `out/`. |
| **Result** | Small string a Task writes; Pipeline can re-export them on the PipelineRun **Output** tab. |
| **finally** | Tasks that always run after the graph (success or failure) — summary + PR comment. |

**Pipelines-as-Code (PaC)** watches GitHub events, matches a **Repository** CR, and
creates a PipelineRun from a template under `.tekton/` (or a live-repo equivalent).

---

## 2. Object map — fixture demo (primary enablement path)

```
GitHub PR
   │  webhook
   ▼
PaC controller ──► Repository CR (upgrade-delta)
   │
   ▼
PipelineRun  (.tekton/pull-request.yaml → name upgrade-delta-pr-…)
   │  pipelineRef: upgrade-delta-demo
   │  workspace source → PVC upgrade-delta-reports
   │  workspace basic-auth → Secret {{ git_auth_secret }}
   ▼
Pipeline upgrade-delta-demo
   ├─ TaskRuns: clone, coverage, scan, select-tests, run-tests, grade-gate
   └─ finally: summary, pr-comment
   │
   ▼ writes out/reports/*.html onto PVC
nginx Deployment + Service + Route  →  browsable scorecard
```

### 2.1 Cluster platform (not in this repo)

| Object | Where | Role |
|---|---|---|
| OpenShift Pipelines Operator | `openshift-pipelines` | Installs Tekton + PaC |
| Route `pipelines-as-code-controller` | `openshift-pipelines` | GitHub App webhook target |
| Secret `pipelines-as-code-secret` | `upgrade-delta-demo` (typical) | GitHub App ID, private key, webhook secret |
| Task `git-clone` | cluster / Tekton Hub | Catalog task used by both pipelines |
| ServiceAccount `pipeline` | project | Default runner for PipelineRuns |

### 2.2 `deploy/` — durable cluster resources

| File | Kind(s) | Name | Purpose |
|---|---|---|---|
| `00-namespace.yaml` | Namespace | `upgrade-delta-demo` | Demo project |
| `10-reports-pvc.yaml` | PersistentVolumeClaim | `upgrade-delta-reports` | Shared workspace: git clone + `out/` reports. Prefer **RWX** if the viewer mounts it at the same time as Task pods |
| `20-scorecard-viewer-deployment.yaml` | ConfigMap + Deployment | nginx viewer | Serves HTML from the PVC docroot |
| `22-scorecard-route.yaml` | Service + Route | `scorecard` | Public URL → viewer |
| `11-live-reports-pvc.yaml` | PVC | (live reports) | Optional separate volume for live-pipeline runs |

Apply order: namespace → PVC → viewer → Route. Skip viewer/Route if you only use the
PipelineRun **Results** tab.

### 2.3 Pipelines-as-Code wiring

| File | Kind | Name | Purpose |
|---|---|---|---|
| `integration/tekton/pac/repository.yaml` | `Repository` (PaC) | `upgrade-delta` | Binds `spec.url` (GitHub repo) to this namespace so PR events create runs |
| `.tekton/pull-request.yaml` | PipelineRun **template** | `upgrade-delta-pr` | Annotations tell PaC *when* to run and *which* remote Task YAMLs to fetch |

**Important PaC annotations** on `.tekton/pull-request.yaml`:

| Annotation | Meaning |
|---|---|
| `on-event: [pull_request]` | Fire on PR open/sync |
| `on-target-branch: [main]` | Only PRs into `main` |
| `pipeline: integration/tekton/pipeline-demo.yaml` | Pipeline definition path in the repo |
| `task` … `task-6` | Every Task the Pipeline references (including `git-clone`) must be listed — PaC does **not** silently use Tasks already on the cluster |
| `max-keep-runs: "5"` | Retention |

**Params PaC fills** (mustache-style): `{{ repo_url }}`, `{{ revision }}`,
`{{ repo_owner }}`, `{{ repo_name }}`, `{{ pull_request_number }}`,
`{{ git_auth_secret }}`.

### 2.4 Pipeline — `upgrade-delta-demo`

**Source:** `integration/tekton/pipeline-demo.yaml`  
**Kind:** `Pipeline` · **name:** `upgrade-delta-demo`

| Pipeline task | Task / spec | Image (typical) | What it does | Key outputs |
|---|---|---|---|---|
| `clone` | `git-clone` | catalog | Checks out PR commit onto workspace | working tree |
| `coverage` | `upgrade-delta-coverage` | ubi9/python-311 | `upgrade_delta.py coverage` vs Lightwell catalog | `out/coverage.json`, `out/reports/coverage.html` · Results: `COVERAGE_PCT_*`, `DEPENDENCIES_*` |
| `scan` | `upgrade-delta-scan` | ubi9/python-311 | `upgrade_delta.py scan` with committed evidence; **`fail-on` empty** | `out/scorecard.json`, `out/reports/scorecard.html`, `out/routing.json` · Results: `PROJECT_GRADE_*` |
| `select-tests` | `upgrade-delta-select-tests` | ubi9/python-311 | `test_router.py` + `examples/tests/coverage.json` | `out/routing-out/selection-report.json`, `surefire-includes.txt`, `deploy-gate.json` |
| `run-tests` | `upgrade-delta-run-tests` | ubi9/openjdk-21 | MiniRunner on `demo-jars` + `demo-jars/lib` | `out/test-results.json` · Results: `TEST_METHODS_*`, summary |
| `grade-gate` | **inline `taskSpec`** | ubi9/python-311 | Fails if `headline_grade` ≥ pipeline `fail-on` (default **D**) | exit 2 on breach |
| `summary` *(finally)* | `upgrade-delta-summary` | ubi9/python-311 | Re-renders scorecard with test outcomes; prints VERDICT banner | updated `out/reports/scorecard.html` |
| `pr-comment` *(finally)* | `upgrade-delta-pr-comment` | ubi9/python-311 | Builds CAB markdown; posts to GitHub if token present | `out/pr-comment.md` + PR comment |

**Workspaces**

| Workspace | Bound to | Used by |
|---|---|---|
| `source` | PVC `upgrade-delta-reports` | All tasks (clone writes; others read/write `out/`) |
| `basic-auth` | PaC git-provider Secret (optional) | `pr-comment` only |

**Pipeline params**

| Param | Default | Role |
|---|---|---|
| `git-url` / `git-revision` | from PaC | What to clone |
| `fail-on` | `D` | Enforced only in `grade-gate` |
| `scorecard-route-host` | `""` | Makes summary log print https links |
| `repo-owner` / `repo-name` / `pull-request-number` | from PaC | PR comment target |

### 2.5 Demo Tasks (detail)

| Task YAML | Name | Script / binary | Notes |
|---|---|---|---|
| `task-upgrade-delta-coverage.yaml` | `upgrade-delta-coverage` | `upgrade_delta.py coverage` | Reads SBOM + `catalogs/lightwell-remediated-java-sbom.json` |
| `task-upgrade-delta-scan.yaml` | `upgrade-delta-scan` | `upgrade_delta.py scan` | Evidence under `examples/evidence/`; optional `--accept-transitive-scope` |
| `task-upgrade-delta-select-tests.yaml` | `upgrade-delta-select-tests` | `test_router.py` | Exit 3 if mandatory `@Tag(upgrade-gate)` resolves to zero tests |
| `task-upgrade-delta-run-tests.yaml` | `upgrade-delta-run-tests` | `testing.MiniRunner` | Classpath = `examples/demo-jars/*.jar` + `lib/*.jar`; writes `record-test-results` |
| `task-upgrade-delta-summary.yaml` | `upgrade-delta-summary` | `render-scorecard` + banner | Always in `finally` so red gates still update HTML |
| `task-upgrade-delta-pr-comment.yaml` | `upgrade-delta-pr-comment` | Inline Python (+ optional API post) | Self-contained renderer — does not require `pr_comment.py` on disk |
| `task-upgrade-delta.yaml` | `upgrade-delta` | Combined coverage+scan | Used by older `pipeline-upgrade-delta.yaml`, not the console demo |

### 2.6 Manual PipelineRun (no PaC)

| File | Kind | Purpose |
|---|---|---|
| `integration/tekton/pipelinerun-demo.yaml` | PipelineRun (`generateName: upgrade-delta-demo-`) | Ad-hoc run; set `git-url` then `oc create -f …` |

Cluster operators often create the same shape with `generateName: upgrade-delta-demo-real-`
and pin `git-revision` to a SHA, `scorecard-route-host`, and `fail-on: D`.

### 2.7 Workspace artifacts (after a successful graph)

| Path on PVC | Producer | Consumer |
|---|---|---|
| (repo checkout) | `clone` | everyone |
| `out/coverage.json` / `out/reports/coverage.html` | coverage | scan (optional embed), summary, viewer |
| `out/scorecard.json` / `out/reports/scorecard.html` | scan → summary re-render | grade-gate, summary, pr-comment, viewer |
| `out/routing.json` | scan | select-tests |
| `out/routing-out/*` | select-tests | run-tests, pr-comment |
| `out/test-results.json` | run-tests | summary, pr-comment |

### 2.8 PipelineRun Results (Output tab)

Exported from demo Pipeline (see `pipeline-demo.yaml` `results:`):

- Grades: `PROJECT_GRADE_RECOMMENDED_PATH`, `PROJECT_GRADE_WITHOUT_REMEDIATION`, `GRADE_SCALE_LEGEND`
- Coverage: `COVERAGE_PCT_EXACT_MATCH`, `DEPENDENCIES_COVERED_EXACT`, `NEAR`, `UNCOVERED`
- Selection: `TEST_CLASSES_SELECTED_COUNT`, `TOTAL_SUITE`, `SELECTED_NAMES`
- Execution: `TEST_METHODS_PASSED_COUNT`, `FAILED_COUNT`, `TESTS_ACTUALLY_EXECUTED_SUMMARY`

---

## 3. Object map — live pipeline (real `pom.xml` PRs)

Lives under `integration/tekton/real-pipeline/` and is meant to be **vendored** into an
app repo as `.upgrade-delta/` (see that directory’s README).

**Pipeline:** `upgrade-delta-live` (`pipeline-real.yaml`)

```
clone → detect-pom-changes → live-coverage
      → generate-evidence (when HAS_CHANGE)
      → resolve-and-grade-transitive
      → select-tests → run-tests-maven → grade-gate
      → finally: summary, pr-comment
```

| Pipeline task | Task | Role |
|---|---|---|
| `detect-pom-changes` | `detect-pom-changes` | Diffs pom (+ property resolution) → `out/changed-deps.json` · Result `HAS_CHANGE` |
| `live-coverage` | `live-coverage` | Coverage meter from real pom via `pom_to_cyclonedx.py` |
| `generate-evidence` | `generate-evidence` | Fetch old/new jars (Central vs Lightwell), `analyze` → `out/evidence/`, `scan` with **empty fail-on** |
| `grade-transitive` | `resolve-and-grade-transitive` | Two-hop grade for version shifts pulled in by the bump |
| `select-tests` | `upgrade-delta-select-tests` *(shared)* | Same router Task as demo |
| `run-tests` | `run-tests-maven` | Maven Surefire + includes file (not MiniRunner) |
| `grade-gate` | inline | Same policy as demo — after tests |
| `summary` / `pr-comment` | shared Tasks | Unchanged |

**Extra workspace:** `maven-settings` → Secret with `settings.xml` (Lightwell credentials).

**Trigger template:** `real-pipeline/pull-request-live.yaml` (PaC annotations must list
*every* Task, including the three shared ones copied under `.upgrade-delta/real-pipeline/`).

**Supporting / optional objects**

| Object | Purpose |
|---|---|
| `task-resolve-jars.yaml` / `task-live-diff.yaml` | Older single-bump path; pipeline prefers `generate-evidence` |
| `pipeline-coverage-map` + `task-build-coverage-map` | Nightly/full-suite JaCoCo → router coverage map |
| Scripts in `real-pipeline/scripts/` | `detect_pom_changes.py`, `generate_evidence.sh`, `detect_transitive_changes.py`, `pom_to_cyclonedx.py` |

---

## 4. Optional add-ons

### 4.1 CAB approval gate

| File | Kind | Purpose |
|---|---|---|
| `pac/approval-gate.yaml` | `ApprovalTask` | Human approval step in the flow |
| `pac/approval-gate-manual.yaml` | Task | Manual CAB approval variant |
| `pac/approval-rbac.yaml` | Role + RoleBinding | Who may approve |

### 4.2 RHTAS / Sigstore sealing

| File | Kind | Purpose |
|---|---|---|
| `rhtas/securesign.yaml` | `Securesign` | Cluster signing config |
| `rhtas/task-sign-evidence.yaml` | Task `upgrade-delta-sign` | Cosign keyless sign of scorecard + routing |
| `rhtas/task-verify-evidence.yaml` | Task `upgrade-delta-verify` | Verify signatures |

Not required for the fixture demo enablement path.

### 4.3 Legacy combined pipeline

| File | Kind | Purpose |
|---|---|---|
| `pipeline-upgrade-delta.yaml` | Pipeline `upgrade-delta-pipeline` | Older coverage+scan+route chain via monolithic `upgrade-delta` Task |

Prefer `pipeline-demo.yaml` for demos.

---

## 5. Images and runtime contracts

| Step | Image | Why |
|---|---|---|
| Most Python tasks | `registry.access.redhat.com/ubi9/python-311:latest` | `upgrade_delta.py`, router, summary |
| Demo run-tests | `ubi9/openjdk-21` | MiniRunner JVM |
| Live generate / Maven / transitive | `ubi9/openjdk-21` | `mvn` + analyze fetch |
| git-clone | Tekton catalog image | Standard clone |

**No pip install** for the core tool — stdlib Python only. Live path needs Maven + settings
Secret for Lightwell.

---

## 6. Failure modes enablement engineers should know

| Symptom | Object to inspect | Likely cause |
|---|---|---|
| Check pending, no PipelineRun | PaC controller logs, Repository `spec.url`, App webhook deliveries | Webhook / repo URL mismatch |
| `cannot find referenced task …` | `.tekton/*.yaml` annotations | Missing `task-N` annotation for a Pipeline taskRef |
| Multi-Attach / PVC Pending | PVC + StorageClass | Viewer + Task both need **RWX** |
| Red at `grade-gate`, tests 9/0 | Expected | Project grade F ≥ `fail-on` D |
| Red at `run-tests` with ClassNotFound | `upgrade-delta-run-tests` classpath | Missing `examples/demo-jars/lib` |
| Red at `select-tests` exit 3 | mandatory tag | `@Tag(upgrade-gate)` resolved to zero tests |
| Scorecard HTML without test banner | summary finally / PVC | Open pre-summary artifact, or summary didn’t re-render |
| PR comment only in logs | `basic-auth` workspace | No PaC token on manual PipelineRun |

---

## 7. How to apply / inspect (cheat sheet)

```bash
# Demo Tasks + Pipeline (cluster already has git-clone)
oc apply -n upgrade-delta-demo \
  -f integration/tekton/task-upgrade-delta-coverage.yaml \
  -f integration/tekton/task-upgrade-delta-scan.yaml \
  -f integration/tekton/task-upgrade-delta-select-tests.yaml \
  -f integration/tekton/task-upgrade-delta-run-tests.yaml \
  -f integration/tekton/task-upgrade-delta-summary.yaml \
  -f integration/tekton/task-upgrade-delta-pr-comment.yaml \
  -f integration/tekton/pipeline-demo.yaml

oc get pipeline,task,pvc,route,repository -n upgrade-delta-demo
tkn pipelinerun list -n upgrade-delta-demo
tkn pipelinerun describe <name> -n upgrade-delta-demo
```

Console: **Pipelines → Pipelines / PipelineRuns**, **Networking → Routes → scorecard**,
**Storage → PersistentVolumeClaims**.

---

## 8. Related docs

| Doc | Audience |
|---|---|
| [`DEMO-101.md`](DEMO-101.md) | Product / beginner concepts |
| [`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md) | Follow-along local + cluster |
| [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md) | Presenter beats |
| [`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md) | Console install |
| [`../integration/tekton/README.md`](../integration/tekton/README.md) | Tekton folder overview |
| [`../integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md) | Live pipeline enablement |
| [`../deploy/README.md`](../deploy/README.md) | PVC / viewer notes |

**Bottom line for enablement:** a PR becomes a **PipelineRun** that mounts one **PVC**,
runs a fixed **Task** graph, writes JSON/HTML under `out/`, exposes numbers as **Results**,
optionally serves HTML via **Route**, and posts a CAB comment with the PaC **Secret** —
with **grade-gate after tests** so evidence and policy stay on the same run.
