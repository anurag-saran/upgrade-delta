# Compose SonarQube with upgrade-delta

There is **no native SonarQube / SonarCloud plugin** for upgrade-delta today. Do not hunt
for one in Marketplace. This guide explains how the two products **compose** when you
already gate merges on Sonar and want upgrade-delta for dependency bumps.

Index: [`README.md`](README.md).

---

## Who owns what

| Concern | Owner |
|---|---|
| App code smells, duplication, security hotspots, line/branch coverage *trends* | **SonarQube / SonarCloud** quality gate |
| Dependency upgrade delta ∩ *your* bytecode → which tests this bump owes, with reasons | **upgrade-delta** |
| Per-test coverage map consumed by the test router | Nightly **JaCoCo** → `coverage.json` ([`integration/jacoco/`](../../integration/jacoco/)) |

Sonar answers “is *our* code healthy?” upgrade-delta answers “given *this jar change*,
what testing do we owe, and can we prove it?” Neither replaces the other.

---

## Do not confuse Sonar coverage with upgrade-delta grades

Sonar’s coverage percentage is a project health metric. upgrade-delta’s letter grades
measure how much a *library* changed and whether that change is reachable from your app.
JaCoCo is **not** a second grade for reflection/DI blind spots — see
[`REFLECTION-101.md`](../REFLECTION-101.md) and the consulting walkthrough.

Treat Sonar “Coverage” and an upgrade-delta scorecard as different documents for
different audiences (eng quality vs. change board / upgrade CAB).

---

## Shared nightly pattern (one build, two consumers)

A single nightly (or weekly) `mvn test` with JaCoCo can feed both tools:

1. Run your usual Surefire suite with the JaCoCo agent (or the per-test profile documented
   in [`integration/jacoco/README.md`](../../integration/jacoco/README.md)).
2. **Sonar:** publish the same build’s coverage report via the SonarScanner / Maven
   Sonar plugin as you already do.
3. **upgrade-delta router:** produce `coverage.json` with `jacoco2coverage.py` (per-test
   attribution when you need method-level routing), publish it where the select-tests
   task can fetch it.

You pay the nightly cost once. Sonar keeps trend charts; the router gets a
SHA-stamped map. Do not strip the embedded SHA — the router’s staleness check depends
on it.

---

## Deploy / merge gate composition

Require **both** gates on dependency-upgrade PRs (and on any path that bumps Lightwell
coordinates):

| Gate | Artifact / signal | Fails when |
|---|---|---|
| Sonar quality gate | Sonar project status / webhook | New code smells, coverage drop, security issues per your Sonar policy |
| upgrade-delta grade-gate / `deploy-gate.json` | Pipeline task + sealed JSON | Grade / obligations not met (see live pipeline docs) |

Wiring tip: keep Sonar on the app module’s normal CI job; keep upgrade-delta on the
dependency-delta (or live pom) PipelineRun. A green Sonar run does **not** clear an F/D
upgrade grade, and a green upgrade-delta scorecard does **not** waive Sonar.

Live pom / payments-service path: [`DEMO-LIVE-POM.md`](../DEMO-LIVE-POM.md).
OpenShift install: [`INSTALL-OPENSHIFT.md`](../INSTALL-OPENSHIFT.md).

---

## What is deliberately out of scope

- Publishing upgrade-delta letter grades as custom Sonar metrics or Quality Gate
  conditions (possible later; not shipped).
- Replacing Sonar with upgrade-delta for general code review.
- Using Sonar coverage alone as the router’s `coverage.json` (formats and per-test
  attribution differ — use `jacoco2coverage.py`).

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Looking for “upgrade-delta” in Sonar Marketplace | Expected miss — no plugin; compose gates instead |
| Sonar coverage up, scorecard still F | Different questions — library delta vs. app trends |
| Router “coverage stale” | Nightly map SHA vs. app commit; regenerate `coverage.json` |
| Double CI cost | Share one JaCoCo-bearing nightly; don’t run full per-test forks on every PR |
