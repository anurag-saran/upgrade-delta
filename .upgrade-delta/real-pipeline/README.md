# The live pipeline — grades what a developer actually changed

This is the pipeline described in the original ask: a developer bumps a dependency to its
Red Hat Lightwell (`rhlw-`) build in `pom.xml`, opens a PR, and the pipeline diffs the real
old-vs-new jars and grades the real impact on the real app — no fixtures.

It's separate from, and does not replace, the fixture demo pipeline (`pipeline-demo.yaml`
at the top of `integration/tekton/`). That one is for presenting the *mechanism* reliably
in a demo. This one is for actually running against your team's real repo.

## A note on this directory's history

Two independent first attempts at this pipeline were built in the same session and both
ended up committed (`real-pipeline/` and a since-superseded `real-app-integration/`). This
version is the **consolidation** of both — it kept whichever half of each was actually
better, and dropped the rest. If you still have `integration/tekton/real-app-integration/`
in your repo, **delete it** — everything in it that was worth keeping is folded in here.

## What's in the consolidated design, and where each piece came from

| Piece | What it does | Source |
|---|---|---|
| `scripts/detect_pom_changes.py` | Diffs `pom.xml`, resolves Maven `${property}` indirection, emits every version change (+ added/removed notes, Lightwell adoptions). | Extended for analyze-on-PR. |
| `task-detect-pom-changes.yaml` | Runs the script, writes `out/changed-deps.json`, surfaces the primary bump as Tekton results. | Extended — `HAS_CHANGE` is any version change. |
| `scripts/generate_evidence.sh` + `task-generate-evidence.yaml` | Fetches OLD/NEW jars (Central vs Lightwell by version string), `analyze` → `out/evidence/`, then `scan` → scorecard. | New — primary grading path for live PRs. |
| `scripts/pom_to_cyclonedx.py` + `task-live-coverage.yaml` | Whole-project coverage meter against the real, current `pom.xml`. | Unchanged. |
| `task-resolve-jars.yaml` / `task-live-diff.yaml` | Single-bump helpers (still vendored). | Version-routed fetch; optional — pipeline uses generate-evidence. |
| `task-run-tests-maven.yaml` | Runs the selected tests for real via **Maven Surefire**. | Unchanged. |


`upgrade-delta-select-tests`, `upgrade-delta-summary`, and `upgrade-delta-pr-comment` are
reused **completely unmodified** from the fixture demo pipeline. **They must still be
vendored and annotated in the trigger file**, even though they're also applied to the
cluster — PaC's remote-pipeline resolution requires every task the pipeline references to
be explicitly annotated; it does not fall back to whatever's already on the cluster, even
when that's genuinely the same Task object. Confirmed the hard way, in production:
`cannot find referenced task upgrade-delta-select-tests. if it's a remote task make sure to
add it in the annotations` — the fix was copying these three files into
`.upgrade-delta/real-pipeline/` and adding `task-6`/`task-7`/`task-8` annotations. This is
now done in the shipped `pull-request-live.yaml`.

## What's deliberately out of scope for this version

- **Parent-POM / BOM-imported versions.** `detect_pom_changes.py` resolves
  `${property}` from the pom under diff only. Versions inherited from a parent
  POM this script never saw stay as unresolved `${…}` and are skipped with a
  warning.
- **Profiles / pluginManagement.** Only `<dependencies>` and
  `<dependencyManagement><dependencies>` are scanned.

## Multi-dependency PRs

`generate-evidence` grades **every** version change in the pom diff (not just
the first Lightwell adoption). Added dependencies are noted as "new dependency,
nothing to diff"; removals are skipped. Transitive follow-up still keys off the
primary bump (preferring a Lightwell adoption when one exists).


## What I could verify, and what only your cluster can prove

Verified for real, this session:
- `detect_pom_changes.py` and the single-result extraction glue, against real fixture
  `pom.xml` files (including Maven property indirection) — confirmed it correctly identifies
  exactly the intended adoption and nothing else.
- `analyze --scorecard-compat` end-to-end against real local jars — confirmed the grade,
  the internal-call-chain evidence, and full downstream compatibility with the real
  (unmodified) `pr_comment.py` and `select-tests`.
- Every YAML file in this directory, for syntax validity.
- **Caught and fixed a real bug during this verification**: the first draft of
  `task-live-diff.yaml` passed `--accept-transitive-scope` to `analyze`, a flag `analyze`
  doesn't support (it's `scan`-only — transitive de-escalation only makes sense across a
  multi-library project scan, not a single direct-dependency live diff). Removed.

Not verifiable from this sandbox (no network access to Maven Central or your Lightwell
endpoint): the actual `mvn dependency:copy` HTTP calls inside `task-resolve-jars.yaml`, and
the real `mvn test` run inside `task-run-tests-maven.yaml`. Your first real PR run is where
those get exercised for the first time.

## Setup — what to do in your application's own repo

1. **Copy `.upgrade-delta/`** (the sibling directory next to this README, at the root of
   the upgrade-delta tool repo) into the **root of your application repo**, as-is.
2. **Copy `.tekton/pull-request-live.yaml`** from `.upgrade-delta/real-pipeline/` into
   your app repo's `.tekton/` directory. Edit `app-name`, `app-module-dir`, `pom-path` if
   your pom.xml isn't at the repo root.
3. **Apply the pipeline + tasks** (once, to your cluster — safe to re-run even if some of
   these already exist from the demo setup):
   ```bash
   oc apply -f .upgrade-delta/real-pipeline/pipeline-real.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-detect-pom-changes.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-live-coverage.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-generate-evidence.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-resolve-and-grade-transitive.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-run-tests-maven.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-upgrade-delta-select-tests.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-upgrade-delta-summary.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-upgrade-delta-pr-comment.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-cab-decision.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-build-payments-image.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-canary-rollout.yaml
   ```
4. **Confirm the live tasks exist** in the target namespace:
   ```bash
   oc get task detect-pom-changes live-coverage generate-evidence \
     resolve-and-grade-transitive run-tests-maven \
     upgrade-delta-select-tests upgrade-delta-summary upgrade-delta-pr-comment \
     cab-decision build-payments-image canary-rollout -n <namespace>
   ```
5. **Reuse the existing `lightwell-maven-settings` secret** — the same one `payments-service`
   already uses (a `settings.xml` file with your Lightwell console credentials). No new
   secret needed; this consolidation dropped the earlier draft's separate
   `lightwell-live-scan-creds` secret in favor of the one credential pattern the rest of
   the repo already uses.
6. **Set up Pipelines-as-Code on your app repo** (same pattern as the demo repo's
   `INSTALL-OPENSHIFT.md` steps 4–6): GitHub App, provider-token secret, Repository CR.
7. **Reuse the same reports PVC** the demo already created (`upgrade-delta-reports`), or
   create your own RWX PVC and update `pull-request-live.yaml`'s workspace binding.
8. **Canary baseline (payments-service demo):** apply `deploy/30-payments-canary.yaml` and
   ensure the pipeline SA can patch Routes/Deployments and manage Builds. Set
   `enable-canary=false` on the PipelineRun if you only want grade + CAB without deploy.

Open a PR that bumps a dependency to its `rhlw-` version in `pom.xml`, and this triggers
automatically — same as the demo, but grading your real code.

**Step-by-step enablement walkthrough** (jackson hero in `payments-service`, PVC, PaC, what to
watch): [`docs/DEMO-LIVE-POM.md`](../../docs/DEMO-LIVE-POM.md).

**Repeatable demo cycle** (bump → pipeline → close PR without merge so main stays community):

```bash
./scripts/demo-live-cycle.sh start
# …watch upgrade-delta-live-pr-……
./scripts/demo-live-cycle.sh finish
```
