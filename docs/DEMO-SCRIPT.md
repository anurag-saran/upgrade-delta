# Demo script — OpenShift console + GitHub

**Runs in two browser tabs: GitHub and the OpenShift console.** No terminal.
Total ~8–10 minutes. Setup must already be done — see
[`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md).

**The one-line story:** *A developer opens a PR to bump a dependency. The pipeline
automatically measures how much the library actually changed, intersects that with this
app's bytecode, grades the risk, routes only the tests the change owes, and produces a
scorecard a change board can audit — all before anyone approves the merge.*

### The verified numbers this demo produces
Grade **B** · coverage **61%** (11 drop-in / 3 serviced-elsewhere / 4 uncovered) · **7 of
11 test classes** selected · **8 test methods** executed, **0 failed**. (7 classes but 8
methods is correct — one class holds two methods.)

### Before you present (do NOT do live)
- Two tabs open: your GitHub repo, and the OpenShift console on project
  `upgrade-delta-demo`.
- If you set up the viewer, open **Networking → Routes → `scorecard`** once so you have the
  URL handy. Have a **screenshot of the rendered scorecard** as a backup slide.
- Decide your trigger branch: either open a brand-new PR, or reuse an existing PR branch and
  push one commit.

---

## Beat 1 — The trigger, on GitHub (1 min)

On GitHub, open a small pull request against `main`. The simplest, most legible change is to
bump a version in the sample SBOM the scan reads — e.g. edit
`examples/demo-jars/payments-service.sbom.json` (or just add a line to a README) and open the
PR. Use the GitHub web editor → "Create a new branch and start a pull request."

> "A developer opens a PR to move a dependency. That's the only human action in this whole
> flow. Everything after this is automatic — no Jenkins job to click, no manual test triage."

As the PR opens, a check named **`upgrade-delta-pr`** appears as *pending*. Click **Details**
— it links straight into the OpenShift console. Switch tabs.

## Beat 2 — The pipeline runs, in the console (2 min)

Console → **Pipelines → PipelineRuns**: a run named `upgrade-delta-pr-…` is executing. Open
it and watch the graph fill in left to right:

> "**clone** pulls the PR. **coverage** buckets every dependency against the Lightwell
> catalog. **scan** runs the reachability analysis — it reads the app's bytecode and
> measures which changed members it actually reaches, and grades the risk. **route** selects
> the tests that change requires and runs them. Then **summary** prints the verdict."

> ⚠️ The **Details** graph is just topology — five green pills. The *meaning* lives on three
> other tabs; that's Beat 3. Don't try to read the result off the graph.

It finishes in about a minute (the fixtures are small).

## Beat 3 — The verdict: three places it lives (2 min)

The graph is deliberately plain; the data is one click away, in increasing richness:

1. **Logs tab → the `summary` task** — a single VERDICT banner, the fastest read:
   > `Project grade : B  (would be F without the best remediation paths)`
   > `Coverage : 61% drop-in (11 / 3 / 4 of 18)` · `Tests routed : 7 of 11` · per-dependency
   > grades + lanes + the codec `D→B (signed off)` line + open deploy obligations.
   Open this first — it *is* the executive summary, printed for you.
2. **Output tab** — the same numbers as machine-readable PipelineRun **Results** (the audit
   trail): `PROJECT_GRADE`, `GRADE_WITHOUT_REMEDIATION`, `COVERAGE_PCT`, `COVERED/NEAR/
   UNCOVERED`, `TESTS_SELECTED/PASSED/FAILED`, `SUITE_SIZE`.
3. **Logs tab → the `scan` task** — the full narrative if someone wants to see the working:
   per-dependency reasons, the two-hop reachability chain, the config/reflection heuristic.

Walk the Results table:

| Result | Value | Say |
|---|---|---|
| `PROJECT_GRADE` | **B** | the worst pending grade across the best remediation path |
| `COVERAGE_PCT` / `COVERED` / `NEAR` / `UNCOVERED` | **61 / 11 / 3 / 4** | 11 deps have a drop-in remediated build; 4 have none |
| `TESTS_SELECTED` / `SUITE_SIZE` | **7 / 11** | ran 7 of 11 test classes… |
| `TESTS_PASSED` / `TESTS_FAILED` | **8 / 0** | …which is 8 test methods, all green |

> "Land this line: **without reachability analysis this project grades F.** Most
> dependencies look scary until you prove which code paths the app actually reaches. The
> tool didn't lower the bar — it measured the app and found the fear was unearned on the
> paths that matter."

## Beat 4 — The scorecard reveal (3 min)

*(Skip to Beat 5 if you didn't deploy the viewer — the Results tab already carried the
story.)*

Open the viewer Route: `https://<route>/out/reports/scorecard.html`. Walk the rendered
report:

- **Per-dependency grades** — `acme-http-client` → B, `acme-logging` takes the A "fast-lane"
  backport over the F forward-upgrade, `acme-json` → B.
- **The de-escalation story — the money slide.** `acme-codec` is a transitive that grades
  **D**. But method-level reachability proves no changed member is reachable through this
  app's call paths, so it's de-escalated to **B with sign-off**:
  > "This is class-level vs method-level precision. Class-granular analysis would flag the
  > codec's removed `Hex.encode` and block the upgrade. Method-granular proves the app never
  > reaches it — the one path to it is a `debugDump()` this app never calls. So the scan
  > offers a scope shrink, a human signs off, and it's recorded `D → B`. Precision that
  > avoids blocking a safe upgrade — without ever hiding the risk."
- **Lane routing** — fast lane vs targeted tests: the pipeline runs only the tests the change
  requires, not the whole suite.
- **"What this report cannot see"** — reflection and config-driven paths. Point at it:
  > "That's why the canary stays in the plan for every grade, including A. The honesty is
  > the credibility."

## Beat 5 — The close: the CAB summary lands on the PR (1 min)

Switch back to the GitHub tab. The `pr-comment` step has posted a **change-board comment**
right on the pull request: the project grade, the per-library before→after table with lanes,
the "**would be F** without the backports" gap, and the **named test plan** with a reason for
every RUN and skip.

> "So a developer opened a PR, and the change board got back — *on the PR itself* — a graded,
> evidence-backed upgrade analysis: which Lightwell libraries to adopt and at what risk, which
> tests it owes and why, the results of running them, and a one-click merge gate. No manual
> triage, no six-week 'run everything.' The reviewer reads this comment and approves by merging;
> branch protection blocks the merge until the check is green."

That comment posts on **red** runs too — when the gate trips (grade ≥ D, or a missing mandatory
test), the PR gets a comment saying the tool blocked it and why. The audit trail writes itself.

---

## Two live "make it go red" levers

Both are real gates. A red PipelineRun here is the product working, not a failure — say so.

### Lever A — remove the sign-off, watch the gate bite
In a PR, edit `integration/tekton/pipeline-demo.yaml`, in the `scan` task change
`accept-transitive-scope` from `"true"` to `"false"`, and open/push the PR.

> "I'm revoking the human sign-off on that codec de-escalation. Without it, the transitive
> counts at its raw grade **D**, which breaches the pipeline's `fail-on: D`."

The run goes **red** at the `scan` step. The cluster enforced that a de-escalation requires
an explicit human decision — it isn't a suggestion the tool can grant itself.

### Lever B — untag the mandatory gate test
In a PR, open `samples/tests/BootSmokeIT.java` and remove its `@Tag("upgrade-gate")` line.

> "Someone quietly untags the mandatory boot test. A naive router would just select fewer
> tests and stay green — silently dropping a required gate."

The `route` step fails **loudly with exit 3**: a declared mandatory obligation resolved to
zero tests → hard build failure. *"Wrong answers here are always loud — a failed build, a
blocked deploy — never a silently skipped gate."*

Reset either by closing the PR or reverting the line.

---

## If something misbehaves on the day

- **Check stays pending, no run appears** → the PaC GitHub App webhook didn't fire. On the
  GitHub App page → **Advanced**, check recent deliveries for a green ✓. Re-deliver, or
  confirm the `pipelines-as-code-secret` (INSTALL 4d) matches the App.
- **Run is red at `clone`** → the Repository CR `spec.url` doesn't match the PR's repo, or
  the App isn't installed on this repo.
- **Scorecard Route 403 / can't reach it** on the demo network → skip Beat 4 and stay on the
  Results tab (Beat 3), or use your screenshot. The numbers are the same either way.
- **`TESTS_PASSED` (8) looks bigger than `TESTS_SELECTED` (7)** → expected: selected counts
  test *classes*, passed counts test *methods*. Say it before anyone asks.
