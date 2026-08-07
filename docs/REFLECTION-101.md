# 101 — Grades, tests, reflection, and what consulting asked

Read this when the static grade vs test gate vs “reflection gap” conversation
gets muddy. Companion: [`DEMO-101.md`](DEMO-101.md) (product demo). Consulting
callouts: [`CONSULTING-WALKTHROUGH.md`](CONSULTING-WALKTHROUGH.md).

## The one problem

A CVE forces a library bump. Questions:

1. **How bad is this for *our* app?** (static grade)
2. **Did the tests we care about pass?** (test gate)
3. **What if the app uses the library via reflection / DI and static analysis never saw it?** (blind spot)

Those are three different questions. Confusion starts when we mix them.

---

## Job 1 — Static grade (early signal)

**What:** Diff old jar vs new jar → intersect with *your* app’s bytecode (who calls what).

**Output:** A–F per library, project = worst row.

| Grade | Meaning (rough) |
|---|---|
| A/B | Low churn / smoke or targeted tests |
| C | Minor bump — test modules that use it |
| D | Treat as migration / full suite posture |
| F | Your code hits a removed/breaking API — **fix code first** |

**Demo example:** snakeyaml **F** — app calls a `Constructor` that changes in 1.33.

**Also shipped:** *internal call-chain* — you call method 1; inside the library, method 1
reaches changed method 2 you never name. One-hop static would miss it; we follow that chain.

**This job does *not* need tests to run.** It’s the “forecast.”

---

## Job 2 — Select → run → pass/fail (real gate)

**What:** Router picks tests → JVM/Maven runs them → outcomes on the scorecard / PR.

**Consulting point:** Once tests run, **pass/fail is the real gate.** You don’t need a
fancy second “reflection grade” if the suite that matters passed.

**Important fixture caveat:** MiniRunner runs against **current** jars (e.g. snakeyaml
**1.30**). So “tests passed” next to **F** does **not** mean “1.33 is safe.” It means
“today’s app still works.” Grade-gate still fails on F ≥ D. Scorecard copy says so:
*on current jars — does not clear this F; re-test after you migrate.*

---

## The hard problem — reflection / DI

Static analysis only follows **explicit** calls (and our internal chain inside the lib).

Invisible hops:

- `Class.forName` / reflection
- Spring DI / XML / annotations wiring
- `ServiceLoader`

If method 1 only reaches changed method 2 that way, **static is blind**. Across a
**transitive** dependency, blindness compounds → we **never** silently de-escalate; we
require **human sign-off** (`accept-transitive-scope`).

“Prove all reflection” (Graal-style closed world) is a Hard Problem. We are not solving that.

---

## What was proposed (and what confused things)

Proposal floated: **JaCoCo coverage ∩ changed methods** → if runtime hit a changed
class/method that static never explained → flag “likely reflection.”

That join was heard as “already shipped.” It is **not** shipped — and after consulting
feedback we are **not** building it as a second grade.

Consulting, in essence:

1. If you’re running tests, **passing tests is enough** for certainty.
2. JaCoCo-as-second-grade doesn’t earn its keep for the early (no-tests) case.
3. Class-level “look here” is probably fine *later* as diagnostics, not a grade.
4. Prefer a live report over dead sandbox links.
5. If there’s no example of “can’t check because of reflection,” **flag that the report
   can’t know → needs manual check** (D-ish *posture*, not inventing D everywhere).

---

## What we have today (honest inventory)

| Capability | Status |
|---|---|
| Static grade A–F + reachability | **Shipped** |
| Internal call-chain (same lib) | **Shipped** |
| Scorecard + PR comment + test outcomes | **Shipped** |
| Honesty notes on F / transitive rows | **Shipped** |
| “Passed tests don’t clear F/D” caveat | **Shipped** |
| Config/string FQCN heuristics (cheap reflection slice) | **Shipped** when found |
| Transitive de-escalation only with sign-off | **Shipped** |
| JaCoCo × changed-method “reflection gap” grader | **Not built** (by design) |
| Auto-raise every unknown reflection path to D | **Not done** |
| Canned fixture of “reflection-only hop we flagged” | **Not yet** (optional walkthrough aid) |

When someone asks for a reflection/coverage example: you’re not missing a screenshot of a
feature you shipped — **that feature isn’t there.** Show the **honesty / sign-off /
manual-check** posture on the scorecard instead.

**Stable scorecard:**  
https://scorecard-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html

---

## How to hear “flag can’t-know → manual check / maybe D”

**They’re not asking for Graal.** They’re asking for **product honesty**:

- Don’t pretend certainty where reflection might hide risk.
- Prefer visible **“manual check”** over a silent green.
- “Maybe D” = *policy posture* (“treat as needs attention”), **not** “invent a D grade
  for every library we can’t fully see.”

**What we already do that matches the spirit:**

- Transitive: no silent B without sign-off.
- F/D rows: tests on current jars don’t clear the grade.
- Limitations section + honest blurbs.
- Heuristics when FQCNs show up in config/strings.

**What we don’t do (and why that’s OK for now):**

- Don’t auto-D every dependency “because reflection exists somewhere” (over-blocks).
- Don’t run a JaCoCo reflection detective as a second grade.

**Optional later (small):** a **fixture** that *looks* like reflection-only use and shows
a “manual check / can’t fully see” callout — walkthrough aid, not a new engine.

---

## One diagram

```
                    BEFORE / WITHOUT full suite
                    ┌─────────────────────────┐
                    │  Static grade (A–F)     │  ← early certainty
                    │  + internal chain       │
                    │  + honesty / sign-off   │
                    └───────────┬─────────────┘
                                │
                    select → run tests
                                │
                    ┌───────────▼─────────────┐
                    │  Pass / fail            │  ← real gate
                    │  (on jars under test)   │
                    └───────────┬─────────────┘
                                │
              grade-gate (e.g. fail if ≥ D) still policy
                                │
         ✗ JaCoCo×reflection as second grade (not built)
         ✓ "Can't see reflection → manual check / sign-off"
```

---

## Cheat sheet — what to say

| They say | You say |
|---|---|
| Pass/fail is the real gate | Agree — static is early; tests decide after select→run. |
| Class-level “look here” | Fine if we ever add post-test diagnostics; not a second grade. |
| Example of reflection / can’t cover? | Don’t have a reflection-*detection* example; we flag the blind spot + require sign-off / re-test. Can add a small fixture later. |
| Flag can’t-know → manual check / maybe D | Spirit already on the report; we won’t auto-D everything unknown. |
| Report looks awesome | Thanks + stable scorecard link above. |

---

## Bottom line

You’re not behind on a reflection engine. Keep **two jobs** clear: static = early signal;
**tests pass/fail = gate**. Reflection stays a Hard Problem → **honesty + manual check**,
not a second score. What’s optional later is only a **story fixture** for “here’s what
‘we can’t see’ looks like.”
