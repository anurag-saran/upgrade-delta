# Pivot: from "patch without rebuilding" to "how much testing does this upgrade actually owe?"

> **Note (current demo):** This design doc is a historical record of the pivot. The live
> demo no longer uses Log4j — Red Hat Lightwell does not service log4j-core, so using it as
> a hero example was misleading. The demo now uses **jackson-databind** and the Spring/commons
> set, which Lightwell genuinely rebuilds. Log4Shell references below are kept only as the
> historical industry event that motivated the problem framing.


Working note on what to do with `decoupled-patching-demo` now that the thin-jar premise is dead
in front of customers, and a concrete build plan for the replacement.

---

## 1. Be honest about what died

The demo answers a question nobody in the room is asking:

> *"How do I patch a library without rebuilding the application?"*

To get that answer, a customer must re-architect packaging (thin WAR + server module, or a shared
image layer). That's a multi-quarter migration with no independent business case. So the answer is
worthless to them, no matter how well the demo runs. That's not a delivery problem — you can't
narrate your way out of it. The premise is the problem.

**What died:** `build_thin`, the module swap, the identical-checksum reveal, the whole
thin-vs-fat scoreboard, `jboss-deployment-structure.xml`, the OpenShift layer-split story.

**What survives, and is worth more than the rest of the repo put together:**

| Asset | Where | Why it survives |
|---|---|---|
| `compatibility_gate()` | `scripts/lib/demo-fx.sh:146` | Real japicmp run on two real JARs. **Completely packaging-agnostic** — it compares library artifacts, and does not care whether the app is a fat WAR, a Spring Boot uber-jar, or a container image. |
| `classify_stream()` + the verdict routing | `scripts/lib/demo-fx.sh:132` | z/y/x-stream → test-lane decision. This is the seed of the whole new product. |
| Canary / promote / rollback | `scripts/demo-openshift.sh` | Still true for anyone on OpenShift, any packaging. |
| `check_drift()` | `scripts/lib/demo-fx.sh:214` | Packaging-agnostic. Good closing beat. |
| The Log4Shell story | `docs/DEMO-STORY.md` | Still lands — but the moral changes (see §2). |
| Renovate PR step | `scripts/demo-vm.sh github_pr` | Delivery vehicle for the new output. |

Roughly 80 lines of shell in `demo-fx.sh` are the only part of this repo that was ever going to
survive contact with a customer who won't change their build. Everything else is scaffolding
around a premise they rejected.

---

## 2. The new question — and why it's the right one

Reframe the Log4Shell story. Your current version says *the tragedy was the rebuild*. It wasn't.
Rebuilding is cheap; Maven takes four minutes. What actually consumed those six weeks in every
bank in December 2021 was:

1. the regression suite you must run because nobody can say what changed,
2. the change advisory board that won't approve until you can,
3. and the fact that both of those cost the same whether the library changed 4 lines or 40,000.

So the new question — the one your audience genuinely can't answer today:

> **"This upgrade fixes the CVE. How much of my test suite do I actually owe it, and can I prove
> that number to my change board?"**

Every customer has this problem *right now*, with their existing fat jars, with no migration, on
Monday. And the honest answer today is *"we don't know, so run everything, so it takes six weeks."*

This also reframes Red Hat's actual product in a way that helps rather than sounds like marketing.
Red Hat's value proposition is **backports** — z-stream fixes that change almost nothing. Today
that's an assertion. A delta analyzer turns it into a **measured number**: same CVE closed,
backport delta ≈ near-zero, community forward-upgrade delta = hundreds of changed members. The
tool doesn't sell the subscription; the tool *proves* the subscription's whole claim, and it's
honest because it would report the same number if the answer were unflattering.

---

## 3. What to build: `upgrade-delta` — blast radius → test scope

A CLI + CI check. Input: old version, new version, and the customer's application artifact.
Output: a risk tier, a *specific* recommended test scope, and an evidence report.

Five stages. Only stages 1–3 exist as prior art; stage 4 is the wedge (see §5).

### S1 — Measure the change in the library

Not one number. A vector of signals, each independently defensible:

| Signal | How | Catches |
|---|---|---|
| **API delta** — added / removed / modified public members | japicmp (already in the repo) or Revapi | Source & binary incompatibility |
| **Implementation churn** — % of classes whose bytecode differs | class-by-class hash of the two JARs | The z-stream that quietly rewrote its internals — *the case your own docs admit japicmp misses* |
| **Behavior surface** — default configs, `META-INF/services` SPI entries, bundled resources | resource diff inside the JARs | Log4Shell's actual class: no API change, behavior change |
| **Transitive delta** — deps added / removed / version-shifted | `mvn dependency:tree` diff, or CycloneDX SBOM diff | The upgrade that drags in a new Jackson |
| **Stream class** — z / y / x | `classify_stream()`, already written | The prior on intent |

### S2 — Intersect with *this* application

This is what turns a fact about Log4j into a fact about *their* system, and it's the beat the
demo lives or dies on:

- Walk the app's own classes with **ASM** and build an index of every call site into the library
  (`owner/name/descriptor`).
- Intersect that index with S1's changed-member set.
- Also grep app resources for library FQCNs — `log4j2.xml`, Spring XML, DI config. Reflection and
  config-driven instantiation are the known blind spot; be loud about it rather than pretending
  the call graph is complete.

The headline number: **"Log4j 2.14.1 → 2.17.1 changed 214 public members. Your application touches
4 of them."**

### S3 — Score to a tier

Rules, not ML. Every tier must be explainable to an auditor in one sentence.

- Start from stream class (z → fast lane, y/x → full regression) — the rule you already wrote.
- **Escalate** on: incompatible API change touched by the app; transitive version shift; SPI or
  default-config change; impl churn above a threshold in a class the app reaches.
- **De-escalate** (carefully, and never below smoke+canary): z-stream, zero incompatibilities,
  zero touched changed-members, no transitive movement.

### S4 — Convert the tier into an actual test list

Two modes, because customer maturity varies wildly:

**Generic mode** (no coverage data): tier → a test *recipe*. Not "run more tests" but a named
matrix: contract tests on the changed path, one production-like boot test if classpath scanning or
DI wiring is affected, serialization round-trip on old+new payloads if the library touches
persistence or the wire, timeout/retry paths if it's a client. This alone is worth a workshop —
most teams have no such matrix and default to "everything".

**Precise mode** (JaCoCo per-test `.exec` data, which many enterprise Java shops already produce
and throw away): map changed library classes → the tests that actually executed those classes →
**"run these 37 of your 4,000 tests, here's the list, here's why each one is on it."** Fall back to
full regression whenever coverage is missing or stale — safe default, always.

### S5 — Emit evidence, not just a verdict

A JSON + PDF report: what changed, what the app touches, what tier, what tests were selected and
why, what the tool *cannot* see. Signed, attached to the Renovate PR, handed to the CAB.

In an FSI shop the bottleneck isn't the engineer's confidence, it's the approval. **The report is
the product.** The analysis is how you produce it.

---

## 4. Build plan

| Phase | Scope | Effort | Demo-able output |
|---|---|---|---|
| **0** | Lift `compatibility_gate` + `classify_stream` out of the demo into a standalone CLI. Two GAVs in, JSON out. Add impl-churn hashing + resource diff (S1). | ~1 week | "Here is what actually changed between any two versions of any Java library." |
| **1** | ASM call-site index + intersection (S2). Run it against a **fat-jar Spring Boot app** — the customer's world, not yours. | 2–3 weeks | The "214 changed, you touch 4" number. **This is the beat that sells it.** |
| **2** | Rule engine + tier report (S3) and the generic test-recipe matrix (S4a). | 1–2 weeks | The verdict with a real recommendation attached. |
| **3** | JaCoCo per-test mapping (S4b). | 3–4 weeks | "Run these 37 tests." |
| **4** | Evidence report + Renovate/GH Action/Jenkins integration (S5). | 2 weeks | PR comment + CAB attachment. |
| **5** | Reflection/config heuristics, transitive diff, multi-module. | ongoing | — |

Phases 0–2 are ~4–6 weeks and are enough for a full customer demo. **Don't build phase 3 until a
customer confirms they have per-test coverage data.** Ask before you build.

**Tools to lean on, not rebuild:** japicmp / Revapi (API diff), ASM (call sites), JaCoCo
(test→code map), CycloneDX (SBOM diff), OpenRewrite (auto-fix call sites — a phase-6 upsell),
Renovate (delivery). The only original code is the intersection, the rules, and the report.

---

## 5. Prior art — read this before you commit budget

**Endor Labs already ships this**, as "Upgrade Impact Analysis": program analysis at build time,
reachability-based noise reduction, breaking-change prediction, remediation risk tiers (high /
medium / low), plus backported "Endor Patches" for when the upgrade is too expensive. Launched
2024. Their pitch is nearly word-for-word the one above.

Don't pretend otherwise — someone in the room will know. Read it as validation: a funded company
built exactly this because customers pay for it. Then be specific about where you differ:

1. **They stop at risk; you continue to test scope.** Endor tells you an upgrade is risky. Nobody
   — not Endor, not Develocity Predictive Test Selection, not Azure DevOps TIA, not Launchable —
   goes from *dependency delta* to *which of your tests must run*. Every TIA product on the market
   keys off **your git diff**, and a dependency bump is a one-line git diff. **That is a real,
   unoccupied gap**, and it's the gap where the six weeks actually live.
2. **No code egress.** On-prem, air-gapped, runs in their CI. For a bank, "your source never
   leaves" isn't a feature, it's the entry ticket.
3. **It proves the backport thesis.** Endor's patches are Endor's. Yours makes Red Hat's z-stream
   discipline *measurable* — which is a subscription argument no third-party tool will ever make
   for you.
4. **It's an artifact, not a dashboard.** The CAB report.

If you can't hold those four lines under questioning, don't build it — resell Endor and spend the
engineering somewhere else. That's a legitimate outcome of this analysis.

---

## 6. The new demo (≈12 minutes, fat jar throughout, zero re-architecture asked)

1. **Frame.** "You're going to rebuild and retest. I'm not going to argue with that. The question
   is how much." Open a real Renovate PR on a fat-jar Spring Boot app. *No thin jars anywhere.*
2. **Run the analyzer on 2.14.1 → 2.17.1** (the community forward-upgrade everyone did that
   December): hundreds of changed members, minor bump, transitive movement → FULL REGRESSION. That
   verdict *is* the six weeks. Nothing scripted — it's japicmp on the real JARs.
3. **Run it on 2.12.1 → 2.12.2** — Log4j's own real emergency backport of the same CVE. Tiny
   delta, no incompatibilities, app touches zero changed members → smoke + canary + this short
   test list.
4. **Land it.** Same CVE closed. Same fat jar. The six-week difference wasn't the code — it was
   *which artifact you sourced*, and until now nobody could measure that in advance.
5. **Show the report** you hand the change board.
6. **Keep the caveat.** Structural analysis can't see every behavior change (your existing
   `demo-fx.sh` already says this out loud — keep that; it's the most credible thing in the repo).
   That's why canary and rollback stay in the story. The tool sizes the risk, it doesn't abolish it.

Both version pairs already run today in `compatibility_gate`. Phase 0 + a fat-jar sample app gets
you to a demo of beats 1–4 in about a week.

---

## 7. Validate before you build

Five customer calls, three questions. Cheap, and it kills or funds the whole thing:

1. *"When a critical CVE lands, what's your longest pole — the rebuild, the regression run, or the
   approval?"* If they say rebuild, this pivot is also wrong and you need to know that now.
2. *"Today, how do you decide how much to retest a dependency bump?"* If the answer is "run
   everything, it's cheap and fast" — no market. If it's "run everything, it takes three weeks" —
   market.
3. *"Do you keep per-test coverage data?"* Determines whether phase 3 is a product or a fantasy.

Ask these before writing phase 1. The last demo was built on an assumption that was never tested
against a customer; the fix isn't a better demo, it's testing the assumption first.
