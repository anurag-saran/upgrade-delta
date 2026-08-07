# upgrade-delta demo — 101 (for beginners)

New to this repo? Start here. When you want to click through a live run, use
[`DEMO-SCRIPT.md`](DEMO-SCRIPT.md) (presenter) or [`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md)
(follow-along checklist).

## The problem in one sentence

When you bump a library for a CVE, **build is fast; deciding how much to test and proving
it to a change board is slow.**

## What this tool does

**upgrade-delta** answers: *for this app, how risky is this library upgrade, and which
tests does it actually owe?*

It does that by:

1. Looking at **what changed** in the library (API / bytecode / defaults).
2. Looking at **what your app actually calls** (from your jar’s bytecode — your code stays
   in CI).
3. Giving an **A–F grade** and a recommended test scope.
4. **Selecting and running** those tests.
5. Putting the proof on a **scorecard** and a **PR comment**.

The core analyzer is one dependency-free Python file (`upgrade_delta.py`) — no JVM required
for the grade itself.

---

## Two jobs (don’t mix these up)

| Job | Meaning | Analogy |
|---|---|---|
| **Static grade** | Early risk signal from code analysis | Weather forecast |
| **Test gate** | Selected tests pass or fail | Did it actually rain? |

- Forecast = useful before you run everything.
- **Pass/fail after tests = the real merge gate.**
- JaCoCo is *not* a second grade in this demo.

---

## The story the demo tells

A tiny payments app depends on real libraries. The fixture grades:

| Library | Grade | Plain English |
|---|---|---|
| **snakeyaml** | **F** | Your code calls a constructor that was removed/changed. Fix that call before upgrading. |
| **json-path** | **C** | You use it; nothing you call changed shape — test the modules that use it. |
| **spring-core** | **B** | Lightwell remediated backport; smoke-test the parts you use. |

**Project grade = worst of those → F.**

Also expect:

- **Catalog coverage ~59%** (16 drop-in / 1 serviced elsewhere / 10 uncovered) — “is there a
  Lightwell build?” This is *not* the same as the grade table.
- **Tests: 9 methods, all passed** — suite is green; the pipeline can still be **red**
  because grade **F ≥ D** (policy). Red means “blocked for the change board,” not “the tool
  crashed.”

---

## Three places the answer shows up

1. **PipelineRun Results / summary log** — one-line verdict (grade, coverage, tests).
2. **Scorecard HTML** — the readable report  
   Live: https://scorecard-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html  
   Offline: [`examples/scorecard.html`](../examples/scorecard.html)
3. **PR comment** — CAB summary on the pull request ([`examples/pr-comment.md`](../examples/pr-comment.md)).

Companion: **coverage.html** = catalog availability · **scorecard** = upgrade cost for *this* app.

---

## Pipeline shape (demo)

```
clone → coverage → scan (grade, don’t fail yet)
      → select-tests → run-tests
      → grade-gate (fail if grade ≥ D)
      → summary + PR comment
```

Why gate **after** tests? So even a failing grade run still shows **pass/fail on the
scorecard**.

---

## Glossary (tiny)

| Term | Meaning |
|---|---|
| **Delta / evidence** | Published “what changed between old and new jar” for a library |
| **Reachability** | Does *this* app call the changed bits? |
| **Lane** | Recommended test scope (smoke / targeted / full / fix-first) |
| **Lightwell** | Red Hat remediated builds (often a suffix like `.rhlw-…`) |
| **Sign-off** | Human OK to de-escalate a *transitive* risk; never silent |
| **Reflection blind spot** | Static analysis can’t see DI / reflection / service-loader hops |

---

## What this demo is *not*

- Not a full security scanner (OSV is advisory context).
- Not “JaCoCo proves reflection is safe.”
- Not your production app — fixtures live under `examples/`.  
  Real `pom.xml` PRs: [`integration/tekton/real-pipeline/README.md`](../integration/tekton/real-pipeline/README.md).

---

## Next reading

| Doc | When |
|---|---|
| [`DEMO-HANDS-ON.md`](DEMO-HANDS-ON.md) | Follow-along: local `./demo.sh`, then optional OpenShift (fixture) |
| [`DEMO-LIVE-POM.md`](DEMO-LIVE-POM.md) | Live E2E: open a PR that bumps `pom.xml` (jackson Lightwell adoption) |
| [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md) | Full presenter run-of-show (~10 min, two browser tabs) |
| [`TEKTON-ENABLEMENT.md`](TEKTON-ENABLEMENT.md) | Every Pipeline / Task / PVC / PaC object and how they connect |
| [`CONSULTING-WALKTHROUGH.md`](CONSULTING-WALKTHROUGH.md) | What to point at on the scorecard |
| [`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md) | Cluster setup once |
| [`USER-GUIDE.md`](USER-GUIDE.md) | CLI / deeper tool usage |

**Bottom line:** open a PR → pipeline grades *your* risk against *real* library change →
runs the tests that matter → shows a scorecard a human can audit. Static grade warns early;
**tests + grade policy** decide the gate.
