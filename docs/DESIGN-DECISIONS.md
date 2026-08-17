# Design Decisions — why the tool is shaped this way

Every decision below was forced by a customer objection, a failure mode we watched fire,
or a trust requirement. Each entry states the decision, the alternative we rejected, and
the honest cost of the choice.

---

## 1. Measure change, not vulnerability

**Decision.** The rating grades *how much a library changed*, and deliberately knows
nothing about CVEs. No vulnerability database, no CVSS scores.

**Why.** The vulnerability question is answered by a crowded, well-funded market (Snyk,
Sonatype, Endor Labs, OWASP Dependency-Check). The question nobody answers is what
happens *after* you decide to upgrade: how much testing the upgrade owes. Adding CVE data
would have dragged the tool into competing on someone else's home turf, required a
database subscription, and diluted the one claim nobody else makes: delta → test scope.

**Pros.** A sharp, defensible niche; zero data-feed dependencies; composes with whatever
scanner the customer already runs (their scanner says "upgrade," we say "here's the bill").
**Cons.** The tool cannot prioritize *which* upgrades matter most on its own; it needs a
vulnerability signal from elsewhere to drive urgency. Buyers conditioned to expect CVE
dashboards need the scoping explained.

---

## 2. Rules, not machine learning

**Decision.** The rating is a small set of explainable rules (stream class as prior,
escalation on incompatibilities/churn/SPI/default changes, de-escalation only with
evidence and sign-off). Test selection is a deterministic coverage join, not a prediction.

**Why.** The primary consumer is a change advisory board. Every tier must be explainable
to an auditor in one sentence, and every selected/skipped test must carry a reason that
traces to a changed member. An ML model — however accurate — produces "the model scored
it 0.83," which is not an audit answer. This is the deepest philosophical difference from
Develocity Predictive Test Selection and Launchable, which are ML-based and optimized for
a different goal (developer feedback speed on every commit).

**Pros.** Deterministic, reproducible from inputs, auditable, works from day one with no
training data, behaves identically in air-gapped environments.
**Cons.** Rules are cruder than a trained model at estimating *likelihood*; a model can
learn that a particular library's patches historically break things. We recover some of
this via evidence-based escalation, but a mature ML system will beat rules at raw
prediction accuracy. We are trading a few percent of precision for one hundred percent of
explainability, and for this audience that trade is correct.

---

## 3. Publisher/consumer split with a strict trust boundary

**Decision.** `analyze` runs once at publish time, app-agnostic; `scan` runs in the
customer's CI and performs only the intersection locally. Evidence flows down; code never
flows up.

**Why.** The customers who killed the original demo are the same customers who run
disconnected builds and will not ship source or bytecode to a SaaS. "Your code never
leaves the building" is not a feature for a bank; it is the entry ticket. The split also
avoids recomputing expensive pair-math per consumer.

**Pros.** Air-gap compatible; the published report is identical for every consumer and
therefore publishable/cacheable/signable once; the customer-specific part is cheap.
**Cons.** The published evidence must carry enough machine-readable detail for local
rescoring (the `machine` section), which couples the schema between stages; schema
versioning becomes a real obligation. SaaS-style cross-customer learning is impossible by
construction.

---

## 4. Ratings never averaged; risk never rolls up

**Decision.** The project headline is the worst pending grade across best available
remediation paths. Transitives count at full weight in the score and histogram, and only
*nest* under their parent in the remediation table.

**Why.** A project with nineteen A-grade upgrades and one F is not a B+ project; it is a
project with a migration problem. Averaging invites gaming, and rolling transitive risk
up under a green parent is risk laundering — a deserialization bug in a transitive
Jackson is exactly as exploitable as one you declared yourself. Meanwhile the *fix lever*
genuinely lives at the parent (bump it, or pin an override), so the work plan rolls up
even though the risk does not.

**Pros.** Un-gameable headline; the CAB and the engineer each get the view shaped for
their question; the lane histogram doubles as a literal test-effort budget.
**Cons.** One stubborn F dominates the headline forever, which can demoralize; the
mitigation is the with/without comparison and the per-row detail, not a softer aggregate.

---

## 5. Escalate automatically, de-escalate only with a human's name on it

**Decision.** Evidence escalates a grade with no ceremony (a z-stream with 50% semantic
churn gets B, not A). De-escalation is only ever *suggested* for direct dependencies and
requires an explicit `--accept-transitive-scope` flag for transitives, recorded on the
report.

**Why.** The asymmetry mirrors the asymmetry of the failure modes: over-testing wastes
hours; under-testing ships an outage with an audit trail saying a tool approved it.
Two-hop reachability evidence is genuinely weaker (reflection blindness compounds across
hops), so it must not silently shrink anything. The flag also creates the governance
artifact the CAB actually wants: *who* accepted the evidence.

**Pros.** The fast lane stays credible precisely because it is hard to reach; the sign-off
appears in the sealed record; CI enforces the conversation (the same project fails
`--fail-on D` without the flag and passes with it).
**Cons.** Friction. Teams with excellent judgment will find the flag bureaucratic; the
counter is that the flag is one token in a CI config, set once, reviewed via CODEOWNERS.

---

## 6. Semantic churn instead of byte-hash churn

**Decision.** Implementation churn is computed on a normalized class fingerprint: debug
attributes stripped, members sorted, bytecode walked with constant-pool indices resolved
to values (including inside `BootstrapMethods`).

**Why.** Raw byte-hashing lies on real jars — different javac versions and `-g` flags
change every byte with zero behavior change, and the first skeptical engineer to hash two
identical builds would have discredited the metric permanently. The verification harness
proves the property in both directions: identical source under different toolchain flags
= 100% raw diff, 0.0% semantic churn; a single real method edit still registers.

**Pros.** The churn number survives hostile scrutiny; the excluded-noise count printed
beside it makes the normalization visible rather than magical.
**Cons.** Real cost and real residual: the fingerprint required a full JVM instruction
walker, and annotation attributes are still hash-compared (annotation-heavy libraries
over-report). The fail-safe direction is fixed — unparseable input falls back to the raw
hash, so the metric can over-report but structurally cannot under-report.

---

## 7. Method-level reachability with conservative dispatch

**Decision.** Two-hop reachability walks per-method caller→callee edges with
super-chain resolution plus all overrides and implementors, keeping the class-level
number only as a printed comparison.

**Why.** Class-granular closures are safely conservative but practically useless on real
frameworks — one touch of a god-class and the closure swallows the library, evaporating
every scope-shrink. The corpus demonstrates the stakes: a debug method the app never
calls reaches the transitive's removed member; class-level would have flagged it and
killed a legitimate de-escalation, method-level proves the path unreached.

**Pros.** De-escalation actually fires in practice; the precision delta is printed on the
report ("class-level would have flagged N members"), which is itself persuasive evidence.
**Cons.** Conservative dispatch still over-approximates polymorphic code relative to a
true points-to analysis; and the sharper the closure, the more weight rests on the
reflection heuristics catching what the call graph cannot. Both push toward the same
future work, not toward a different design.

---

## 8. Emit affected code, not selected tests

**Decision.** The scanner's routing payload names changed members and affected app
classes — never tests. A separate router joins with the customer's coverage map.

**Why.** Which tests exercise which classes is a dynamic fact that exists only in the
customer's coverage data. Mixing it into the scanner would breach the trust boundary
(decision 3) and couple the publisher to every consumer's test topology. The contract at
"affected code" also lets both sides improve independently: sharper reachability shortens
the payload; per-method coverage sharpens the join; the schema moves for neither.

**Pros.** Clean layering; three small, versionable schemas (routing / selection-report /
deploy-gate) that are the actual product; mockable ends for demos and pilots.
**Cons.** Two moving parts instead of one, and the join's quality is hostage to the
customer's coverage hygiene — which is why staleness is first-class (below).

---

## 9. Coverage staleness is first-class; unknown means run

**Decision.** The coverage map carries provenance (SHA, build, age); the router widens
in any test covering code modified since the map's SHA, refuses maps beyond a drift
threshold, and unconditionally runs tests absent from the map. The plugin never
re-collects coverage itself.

**Why.** A coverage map is a cache of a dynamic fact and decays with every commit.
Selection from a stale map is precisely the "silently skipped the test that would have
caught it" catastrophe. Refusing loudly creates the correct incentive (keep the nightly
healthy) without turning the plugin into a build orchestrator that doubles test time.

**Pros.** The failure mode is always "ran too many tests," never "skipped the wrong one";
provenance printed in the selection report answers the auditor's freshness question.
**Cons.** Shops without a nightly full run get no selection benefit at all — by design,
but it narrows the addressable audience for stage 4 (which is why the customer-validation
question "do you keep per-test coverage data" gates that phase's investment).

---

## 10. Mandatory tests are declared in test source, resolved at run time

**Decision.** `@Tag("upgrade-gate")` on the boot test, resolved via JUnit Platform
discovery, with zero-resolution a hard build failure. Config-block class lists are the
fallback; regexes are allowed but re-verified and warned.

**Why.** A regex-identified mandatory suite fails *open and silently* when someone
renames the test. A tag travels with the class, survives renames, shows up in PR diffs on
the test file itself, and puts the mandatory set under normal code review and CODEOWNERS.
"Declared vs resolved" turns configuration into a checked contract.

**Pros.** The gate cannot silently vanish; governance rides existing review machinery.
**Cons.** Requires JUnit 5 for the first-class path; legacy suites fall back to explicit
lists, which are auditable but manual.

**Empty suite exception.** When `tests-dir` contains **zero** `*.java` test classes, the
router does **not** exit 3. It emits `mode: REACHABILITY_ONLY`, waives in-scope mandatory
obligations, skips Surefire, and names **canary** as the compensating control in
`deploy-gate.json` / the PR comment. Grades are unchanged (still static reachability). If
the suite is non-empty but `@Tag("upgrade-gate")` is missing, exit 3 still applies.

---

## 11. The canary is not a test, and the build must not claim it

**Decision.** Obligations split into in-scope (boot test — resolved and run by Surefire)
and downstream (canary, rollback verification — emitted OPEN in `deploy-gate.json` for a
separate CD-stage process to close).

**Why.** A Maven plugin claiming to have "run the canary" is false assurance of exactly
the kind this system exists to eliminate. The honest mechanics — a build-stage attestation
plus explicitly open obligations consumed by a different process at a different stage —
give the CAB one unbroken, truthful chain. The mock CD gate exists to prove the handoff is
a contract, not a log line: it blocks when the gate file is missing.

**Pros.** Release managers trust it because it refuses to overclaim; the gate file
physically bridges CI and CD.
**Cons.** Requires the CD pipeline to participate; an org whose deploy tooling ignores
the gate file gets attestation without enforcement at the last hop.

**Live demo CD.** On the OpenShift live pipeline, after CAB signoff the `canary-rollout`
Task *is* that CD stage: progressive Route weights (1→5→10→25→50→75→100) gated on Ready
pods plus synthetic HTTP probes (`/health`, `/api/smoke`). Success marks canary/rollback
**CLOSED** in `deploy-gate.json`; failure marks canary **FAILED** and rolls traffic back
to stable. That closes the contract with evidence — it still does **not** claim full
production KPI / user-journey canaries.

---

## 11b. Grade-based CAB: A/B auto-signoff, C human, D/F hard stop

**Decision.** After `grade-gate` (default `fail-on: D`), `cab-decision` branches on
`project.headline_grade`:

| Grade | CAB | Canary |
|---|---|---|
| **A**, **B** | Auto-approve; write `out/cab-signoff.json` (`mode: auto`) with scorecard digest + timestamp | Proceed |
| **C** | Pause until human creates ConfigMap `upgrade-delta-cab-approved`; then `mode: human` signoff | Proceed only if approved |
| **D**, **F** | Never reach CAB by default — `grade-gate` fails the run | No |

**Why.** Low-risk Lightwell adoptions should not wait on a human; mid-risk (C) must.
Keeping `fail-on: D` as a hard stop avoids “rubber-stamp CAB for failing grades” unless an
org deliberately softens the gate later.

**Pros.** Audit trail for every auto path; human path reuses the existing ConfigMap poll
pattern (`approval-gate-manual`).
**Cons.** ConfigMap approval is cluster-local (not GitHub-native); demo-friendly, not the
only production UX.

---

## 12. Static graph inputs; the scanner never invokes the build

**Decision.** The declared dependency graph arrives as a CycloneDX SBOM (dependency:tree
text planned), never by the scanner shelling out to Maven/Gradle.

**Why.** Air-gapped CI must work; a scan result should be reproducible from its inputs
rather than dependent on repo state and plugin versions at scan time; and a security
scanner executing the build it audits is itself a supply-chain surface. Customers already
produce SBOMs for compliance.

**Pros.** Determinism, air-gap compatibility, minimal attack surface, zero build-tool
coupling.
**Cons.** Garbage in, garbage out: a wrong SBOM misleads the transitive analysis — which
is exactly why the artifact-vs-SBOM inventory (drift, shipped-not-declared, relocated
copies) exists as a hazard check rather than trusting either source alone.

---

## 13. Seal the evidence

**Decision.** Detached Ed25519 signatures over canonical JSON, with Sigstore keyless as
the documented production path.

**Why.** To a change board, an unsigned JSON file is a text document anyone could have
edited. Canonicalization means reformatting is harmless but a single value edit is fatal
(demonstrated: a grade edited from B to A after sealing fails verification). Signing at
two points — publisher seals delta reports, consumer CI seals scorecard/selection/gate —
puts two identities on the chain.

**Pros.** Converts reports into audit artifacts; trivial to verify; air-gap friendly.
**Cons.** Local key custody is on the customer until Sigstore is wired; a signature
proves integrity and origin, not correctness — a sealed wrong answer is still wrong,
which is why the analysis honesty (blind-spot sections) matters independently.

---

## The meta-decision: wrong answers must be loud

Threaded through everything above is one asymmetry: every failure mode is tuned to
produce *visible* cost (too many tests, a failed build, a blocked promotion) and never
*invisible* risk (a silently skipped gate, a silently shrunk scope, a silently stale
map). Tools in this category die the first time they are caught silently wrong; they
merely annoy when caught loudly conservative. Annoyance is recoverable. Lost trust is not.
