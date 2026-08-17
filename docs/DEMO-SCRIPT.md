# Demo script — OpenShift console + GitHub (presenter)

> **New here?** Start with [`DEMO-101.md`](DEMO-101.md), then the follow-along checklist
> [`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md). This page is the ~10-minute *presenter* run-of-show.

**Runs in two browser tabs: GitHub and the OpenShift console.** No terminal.
Total ~8–10 minutes. Setup must already be done — see
[`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md).

**The one-line story:** *A developer opens a PR to bump a dependency. The pipeline
automatically measures how much the library actually changed, intersects that with this
app's bytecode, grades the risk, routes only the tests the change owes, and produces a
scorecard a change board can audit — all before anyone approves the merge.*

### The verified numbers this demo produces
Grade **F** · coverage **59%** (16 drop-in / 1 serviced-elsewhere / 10 uncovered) ·
scorecard rows: **spring-core B**, **json-path C**, **snakeyaml F** (reachable removed
`Constructor(TypeDescription, Collection)` — the gate fires). Coverage and scan both read
`examples/demo-jars/payments-service.sbom.json`.

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
> catalog. **scan** runs the reachability analysis — it grades risk but does **not**
> fail the run yet. **select-tests** picks which tests this change owes, and **run-tests**
> executes them in a real JVM. **grade-gate** then fails the PipelineRun if the project
> grade is ≥ D (so the scorecard still carries pass/fail). **summary** prints the verdict."

> Two jobs, one sentence: static grade = early signal; tests that pass or fail = the real
> gate. Don't pitch coverage maps as fixing reflection for the grade.

> ⚠️ The **Details** graph is just topology — green pills. The *meaning* lives on three
> other tabs; that's Beat 3. Don't try to read the result off the graph.

It finishes in about a minute (the fixtures are small).

## Beat 3 — The verdict: three places it lives (2 min)

The graph is deliberately plain; the data is one click away, in increasing richness:

1. **Logs tab → the `summary` task** — a single VERDICT banner, the fastest read:
   > `Project grade : F  (snakeyaml reachable breaking Constructor)`
   > `Coverage : 59% drop-in (16 / 1 / 10 of 27)` · scorecard rows spring-core B /
   > json-path C / snakeyaml F.
   Open this first — it *is* the executive summary, printed for you.
2. **Output tab** — the same numbers as machine-readable PipelineRun **Results** (the audit
   trail): `PROJECT_GRADE`, `GRADE_WITHOUT_REMEDIATION`, `COVERAGE_PCT`, `COVERED/NEAR/
   UNCOVERED`, `TESTS_SELECTED/PASSED/FAILED`, `SUITE_SIZE`.
3. **Logs tab → the `scan` task** — the full narrative if someone wants to see the working:
   per-dependency reasons, reachability, the config/reflection heuristic.

Walk the Results table:

| Result | Value | Say |
|---|---|---|
| `PROJECT_GRADE` | **F** | snakeyaml will break — migrate `Constructor(TypeDescription, Collection)` first |
| `COVERAGE_PCT` / `COVERED` / `NEAR` / `UNCOVERED` | **59 / 16 / 1 / 10** | 16 deps have a drop-in remediated build; snakeyaml is uncovered |
| `TESTS_SELECTED` / `SUITE_SIZE` | **6 / 6** | F/C lanes force full-suite fallback |
| `TESTS_PASSED` / `TESTS_FAILED` | **9 / 0** | MiniRunner with `demo-jars/lib` — real outcomes, not CP noise |

> "Land this line: **reachability turns a library-wide F into an app-specific call site.**
> snakeyaml's removed Constructor is not theoretical — `ConfigLoader` invokes it. json-path
> is C (you call it, nothing you touch changed shape). spring-core is B (Lightwell z-stream)."

## Beat 4 — The scorecard reveal (3 min)

*(Skip to Beat 5 if you didn't deploy the viewer — the Results tab already carried the
story.)*

Open the viewer Route: `https://scorecard.apps.EXAMPLE.com/out/reports/scorecard.html`
(or your cluster’s `scorecard` Route). Offline snapshot: `examples/scorecard.html`.
Durable callouts: [`CONSULTING-WALKTHROUGH.md`](CONSULTING-WALKTHROUGH.md). Walk the rendered
report:

- **Two jobs on the page** — eyebrow says static grade early / tests decide the gate.
  Banner: **6 classes selected · 9 methods run, 9 passed, 0 failed**.
- **Per-dependency grades** — `snakeyaml` **F** (blocks: reachable removed
  `Constructor(TypeDescription, Collection)`), `json-path` **C**, `spring-core` **B**
  (Lightwell z-stream backport).
- **Do: rows** — per-library selected tests attributed via the coverage map even in
  full-suite mode (snakeyaml 1 / json-path 2 / spring-core 2).
- **Honesty** — F / transitive rows note reflection/DI is invisible to static analysis;
  sign-off still required to de-escalate a transitive.
- **"Limitations — what this scan cannot see"** — reflection and config-driven paths.
  Point at it:
  > "That's why the canary stays in the plan for every grade, including A. The honesty is
  > the credibility."

## Beat 5 — The close: the CAB summary lands on the PR (1 min)

Switch back to the GitHub tab. The `pr-comment` step has posted a **change-board comment**
right on the pull request: the project grade, the per-library before→after table with lanes,
the catalog coverage bridge, the **named test plan**, and **test results** (9 methods, all
passed) — even when the grade-gate keeps the check red.

> "So a developer opened a PR, and the change board got back — *on the PR itself* — a graded,
> evidence-backed upgrade analysis: which Lightwell libraries to adopt and at what risk, which
> tests it owes and why, the results of running them, and a one-click merge gate. No manual
> triage, no six-week 'run everything.' The reviewer reads this comment and approves by merging;
> branch protection blocks the merge until the check is green."

That comment posts on **red** runs too — when the gate trips (grade ≥ D, or a missing mandatory
test), the PR gets a comment saying the tool blocked it and why. The audit trail writes itself.

### Live path add-on (payments-service) — CAB auto vs pause vs canary

On the **live** pipeline ([`DEMO-LIVE-POM.md`](DEMO-LIVE-POM.md)), after grade-gate:

- **A/B:** call out the PR comment line **CAB: auto-approved** and `out/cab-signoff.json` —
  no ConfigMap wait. Then show `canary-rollout` shifting Route weights in OpenShift.
- **C:** leave the run paused on `cab-decision`; create ConfigMap `upgrade-delta-cab-approved`
  live so the audience sees human CAB unlock canary.
- **D/F:** stop at grade-gate (red check) — no CAB, no canary.

---

## Two live "make it go red" levers

Both are real gates. A red PipelineRun here is the product working, not a failure — say so.

### Lever A — remove the sign-off (when a transitive D is on the board)
In a PR that grades a **transitive** dependency, edit `integration/tekton/pipeline-demo.yaml`,
in the `scan` task change `accept-transitive-scope` from `"true"` to `"false"`.

> "Without human sign-off, a transitive whose changed members are unreachable stays at its
> raw grade **D**, which breaches `fail-on: D`."

The run goes **red at `grade-gate`** (after tests). On the default fixture corpus today
the blocker is direct **snakeyaml F**, so Lever B is the clearer live demo.

### Lever B — untag the mandatory gate test
In a PR, open `examples/tests/BootSmokeIT.java` and remove its `@Tag("upgrade-gate")` line.

> "Someone quietly untags the mandatory boot test. A naive router would just select fewer
> tests and stay green — silently dropping a required gate."

The `select-tests` step fails **loudly with exit 3**: a declared mandatory obligation resolved to
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
- **`TESTS_PASSED` looks bigger than `TESTS_SELECTED`** → expected: selected counts
  test *classes*, passed counts test *methods* (currently **9** methods / **6** classes).
  Say it before anyone asks.
