# The live pipeline — grades what a developer actually changed

This is the pipeline described in the original ask: a developer bumps a dependency to its
Red Hat Lightwell (`rhlw-`) build in `pom.xml`, opens a PR, and the pipeline diffs the real
old-vs-new jars and grades the real impact on the real app — no fixtures, no committed
sample jars standing in for the real thing.

It's separate from, and does not replace, the fixture demo pipeline (`pipeline-demo.yaml`
at the top of `integration/tekton/`). That one is for presenting the *mechanism* reliably
in a demo. This one is for actually running against your team's real repo.

## What's genuinely new here

| Piece | What it does |
|---|---|
| `scripts/detect_pom_changes.py` | Diffs `pom.xml` between the PR's base branch and head. Finds every dependency whose `<version>` changed, resolves Maven `${property}` indirection, and flags the ones whose new version carries a Lightwell `rhlw-NNNNN` suffix. Pure Python stdlib — no Maven needed for this step. |
| `scripts/pom_to_cyclonedx.py` | Converts the *current* `pom.xml`'s declared dependencies into the CycloneDX shape the coverage meter expects — so the coverage report reflects what's actually in the repo right now, not a static SBOM fixture. |
| `scripts/live_scan.py` | The real grading engine. For every Lightwell adoption the pom diff found: downloads the real old jar (Maven Central) and the real new jar (Lightwell, authenticated), loads the app jar built from this PR's actual source, and calls `upgrade_delta`'s own `diff_jars` / `intersect_app` / `internal_chain_intersect` / `rate` functions directly — the exact same grading logic as the fixture demo, just fed real, live-downloaded data instead of committed evidence files. |
| Fixed in `upgrade_delta.py`'s `coverage()` | A real bug this build surfaced: once a dependency is *already* on its Lightwell version, the old coverage-matching logic didn't recognize it as covered (it never stripped the suffix before comparing). Fixed and regression-tested — this benefits every use of `coverage`, not just this pipeline. |

`task-upgrade-delta-summary.yaml` and `task-upgrade-delta-pr-comment.yaml` are **reused
completely unmodified** — `live_scan.py` writes `out/scorecard.json` in the exact same
shape `scan()` produces, so those two tasks can't tell the difference.

## What's deliberately out of scope for this version

- **Transitive (two-hop) grading.** The demo's `acme-codec via acme-http-client` story
  needs a *published catalog* of transitive delta reports to work from. A live single-PR
  diff doesn't have that — it only knows what changed in *this* `pom.xml`. Direct
  dependencies (including the new internal-call-chain check) are fully live; transitives
  are not, in this version.
- **Test selection/execution.** Needs a real per-test JaCoCo coverage map, which is a
  separate prerequisite documented as Tier 3 in `docs/REAL-LIBRARIES.md` in the main
  upgrade-delta tool repo. `summary`/`pr-comment` already degrade gracefully when
  `out/routing-out/*.json` doesn't exist — they just skip the "tests routed" line.

## What I could verify from this sandbox, and what I could not

I have no network access to Maven Central or your Lightwell endpoint from here, so I
could not run an actual jar download. What I *did* verify, for real:
- `detect_pom_changes.py` against real fixture `pom.xml` files, including Maven property
  (`${spring.version}`) indirection, a non-Lightwell version bump, and a no-op diff.
- `pom_to_cyclonedx.py` feeding straight into the real `upgrade_delta.py coverage` command.
- The coverage-matching bug fix, regression-tested against your actual `customer-sbom.json`
  and the demo fixture — identical results except the one case it was meant to fix.
- `live_scan.py`'s full grading path end-to-end, with its two download functions swapped
  for local fixture jars — every other line ran for real: jar loading, diffing, app
  reachability, the internal-chain check, rating, JSON assembly, and the exit-code gate.
  Fed the result into the real, unmodified `pr_comment.py` and the `summary` task's own
  logic — both consumed it without any error.

The one thing that can only be proven on your real cluster: the actual HTTP calls to
Maven Central and Lightwell inside `fetch_old_jar`/`fetch_new_jar`. Budget your first real
PR run as the point where that gets exercised for the first time.

## Setup — what to do in your application's own repo

1. **Copy `.upgrade-delta/`** (the sibling directory next to this README, at the root of
   the upgrade-delta tool repo) into the **root of your application repo**, as-is.
2. **Copy `.tekton/pull-request-live.yaml`** from `.upgrade-delta/real-pipeline/` into
   your app repo's `.tekton/` directory. Edit the `app-name` param.
3. **Apply the pipeline + new tasks** (once, to your cluster):
   ```bash
   oc apply -f .upgrade-delta/real-pipeline/pipeline-real.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-detect-pom-changes.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-live-coverage.yaml
   oc apply -f .upgrade-delta/real-pipeline/task-live-scan.yaml
   ```
4. **Confirm `upgrade-delta-summary` and `upgrade-delta-pr-comment` already exist** in the
   target namespace (they should, from the demo setup):
   ```bash
   oc get task upgrade-delta-summary upgrade-delta-pr-comment -n <namespace>
   ```
   If they don't, apply them from the main upgrade-delta tool repo first.
5. **Create the Lightwell credentials secret** (new — separate from the demo's
   `lightwell-maven-settings`, which holds a `settings.xml` file rather than raw env vars):
   ```bash
   oc create secret generic lightwell-live-scan-creds -n <namespace> \
     --from-literal=RHLN_USER='<orgID|service-account-name>' \
     --from-literal=RHLN_TOKEN='<your token>'
   ```
6. **Set up Pipelines-as-Code on your app repo** (same pattern as the demo repo's
   `INSTALL-OPENSHIFT.md` steps 4–6): GitHub App, provider-token secret, Repository CR.
7. **Reuse the same reports PVC** the demo already created (`upgrade-delta-reports`), or
   create your own RWX PVC and update `pull-request-live.yaml`'s workspace binding.

Open a PR that bumps a dependency to its `rhlw-` version in `pom.xml`, and this triggers
automatically — same as the demo, but grading your real code.
