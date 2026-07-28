# upgrade-delta — User Guide

## What this tool answers

When a dependency upgrade lands — usually because a CVE forced it — every engineering
organization faces the same unanswerable question: *how much testing does this upgrade
actually owe, and can we prove that number to whoever approves the release?* The honest
answer today in most shops is "we don't know, so we run everything," and "everything" is
where the six weeks go. upgrade-delta replaces that unknown with a measured, evidence-backed,
independently verifiable answer.

The pipeline runs in five stages, each producing a machine-readable artifact that the next
stage consumes. You can adopt them incrementally — each stage is useful without the ones
after it.

```
analyze ──► delta report (+rating)          publisher side, once per version pair
publish ──► rated catalog (HTML)            publisher side
scan    ──► project scorecard + routing     consumer side, in YOUR CI, code never leaves
router  ──► surefire includes + deploy gate consumer side
cd-gate ──► promotion decision              deployment side
```

## Core concepts

**The rating (A–F) measures change, not vulnerability.** A is a disciplined patch (no API
movement, minimal semantic churn, no shipped-default changes); F means the upgrade will
break *your* application because it provably calls something that no longer exists. Each
grade maps to a test lane, from "smoke + canary" to "migration first, then full regression."
The tool deliberately knows nothing about CVEs — see the design-decisions document for why.

**Semantic churn, not byte churn.** The % of shared classes whose implementation changed is
computed on a normalized fingerprint: debug attributes stripped, members sorted, bytecode
walked instruction-by-instruction with constant-pool indices resolved to values. Two
functionally identical builds from different toolchains score 0.0%; a one-method edit still
registers. The excluded "build noise" count is printed beside the churn figure so you can
see the normalization working.

**Evidence flows down, code never flows up.** `analyze` runs once at publish time and is
app-agnostic. `scan` runs in your CI and performs only the intersection with your bytecode
locally. Nothing about your application is needed to produce the published reports, and
nothing about your application leaves your machine to consume them.

**Every de-escalation requires a name on it.** The tool escalates automatically on evidence
(a "patch" with 50% churn does not get the fast lane) but never de-escalates silently.
Direct-dependency scope shrinks are suggested with a sign-off note; transitive-dependency
shrinks require an explicit `--accept-transitive-scope` flag, and the flag's use is recorded
on the report.

**Fail closed, loudly.** A test absent from the coverage map runs. A stale coverage map
means the full suite runs. A mandatory-test declaration that resolves to zero tests fails
the build. A missing deploy gate blocks promotion. The permitted failure modes are "too
many tests," "a failed build," and "a blocked deploy" — never a silently skipped gate.

## Command reference

### analyze — publisher side

```bash
python3 upgrade_delta.py analyze old.jar new.jar \
    --old-version 2.13.4 --new-version 2.13.4.rhlw-00001 --library jackson-databind \
    --json evidence/backport.json --html report.html
```

Diffs two versions of a library across four signals: public-API delta (removed / added /
modified, with binary-incompatible changes isolated), semantic implementation churn,
behavior surface (bundled defaults, resources, `META-INF/services` SPI registrations),
and stream class (z/y/x from the version numbers). Emits the human report card and the
evidence JSON whose `machine` section later powers consumer-side scans. An optional
`--app` flag intersects with one application directly, but the recommended architecture
keeps `analyze` app-agnostic and moves intersection to `scan`.

### publish — publisher side

```bash
python3 upgrade_delta.py publish evidence/*.json --out site/
```

Builds the static rated catalog: an index of every analyzed upgrade with its grade chip,
linking to certificate-style report cards. This is what ships alongside each remediated
artifact.

### scan — consumer side

```bash
python3 upgrade_delta.py scan app.jar [module2.jar ...] \
    --evidence evidence/ \
    --sbom bom.json --lib-jars target/dependency \
    [--accept-transitive-scope] \
    --json scorecard.json --html scorecard.html \
    --routing-payload routing.json --fail-on D
```

Scores the whole project. Multiple jars merge (Maven reactors); fat jars are inventoried
(`META-INF/maven/*/pom.properties` fingerprints vs the SBOM), bundled dependency classes
are excluded from the application view, and relocated shaded copies are flagged as hazards.
The SBOM (CycloneDX JSON) supplies the declared graph — who brought in whom — enabling
transitive analysis; `--lib-jars` supplies the resolved classpath for two-hop, method-level
reachability. The scanner never invokes Maven or Gradle itself.

The scorecard is deliberately not an average: the headline is the worst pending grade
across the best available remediation path per library. When a backport path beats the
forward path, both project grades are shown — the gap is the backport's measured value.
The lane histogram is the test-effort budget to get current, with transitive dependencies
counted at full weight (hatched segments) but nested under their parent in the work-plan
table with the actual fix lever printed.

`--fail-on <grade>` exits 2 when the project grade breaches the threshold, making the
scan a CI gate.

### The router — consumer side

```bash
python3 test_router.py routing.json \
    --coverage coverage.json --tests-dir src/test/java \
    --head-sha $(git rev-parse HEAD) \
    [--changed-since-map com.acme.Foo,com.acme.Bar] \
    --out-dir target/upgrade-delta
```

Joins the routing payload (affected code, never test names) with your per-test coverage
map, and emits: `surefire-includes.txt` (Surefire's native `<includesFile>`), a selection
report where every RUN and every skip carries a printed reason tracing back to a changed
library member, and `deploy-gate.json` carrying the obligations this build could not close
(canary, rollback verification) as OPEN items for the CD pipeline.

Mandatory tests are declared with `@Tag("upgrade-gate")` in the test source, resolved at
run time, and appended unconditionally — the report shows them separately from the
coverage-selected set so an auditor can see they would have run even if the join selected
nothing. Coverage provenance (SHA, build id, age in commits) is checked before any
selection; tests covering app code modified since the map's SHA are widened in.

Produce `coverage.json` from real JaCoCo data with `integration/jacoco/jacoco2coverage.py`
(see that directory's README for the per-test-class Maven profile and its costs).

### seal / verify

```bash
python3 upgrade_delta.py seal scorecard.json routing.json --key keys/signing.pem
python3 upgrade_delta.py verify scorecard.json routing.json --pub keys/signing.pem.pub
```

Detached Ed25519 signatures over canonical JSON (sorted keys, tight separators):
reformatting a document doesn't break verification, editing a value does — verified in the
demo by editing a grade after sealing and watching verification fail with exit 5. The
production path is Sigstore keyless signing in CI (`integration/signing.md`); local keys
exist for air-gapped environments.

## Typical workflows

**Renovate/Dependabot PR gate.** The GitHub Action (`integration/github-action/`) runs
`scan` on the PR branch, posts the scorecard as a PR comment (grade badges, rolled-up
transitives, hazards, the with/without-backport gap), uploads the artifacts, and fails the
check on the configured grade threshold. The Jenkins snippet does the same for
declarative pipelines.

**CAB submission.** Attach the sealed scorecard, the selection report, and the relevant
delta report cards. The chain reads: what changed → what your app reaches → what tests ran
and why → who signed which de-escalations → which obligations transferred to deployment.
Each link is a file; each file is verifiable.

**Nightly coverage refresh.** Run the per-test JaCoCo profile on your existing nightly
full build, convert with `jacoco2coverage.py` (embedding the git SHA), publish where the
router can fetch it. The router refuses maps older than `--max-drift-commits` — staleness
produces a loud full-suite fallback, which is the intended incentive to keep the nightly
healthy.

## Reading a report honestly

Every report ends with a "what this cannot see" section, and it is not boilerplate.
Static analysis cannot see reflection or config-driven instantiation (the heuristics
convert the cheap slice — FQCN literals in resources and string constants — into visible
rows, but the blind spot remains); two-hop evidence carries lower confidence than direct
analysis because that blindness compounds across hops (hence the sign-off requirement);
and a behavior change with zero structural fingerprint is invisible (hence the canary and
rollback stay in every lane, including A). A report that claimed omniscience would be a
worse report. The credibility of the fast lane is purchased by the honesty of the caveats.

## Exit codes

| Code | Emitted by | Meaning |
|---|---|---|
| 2 | scan | project grade breached `--fail-on` |
| 3 | router | a declared mandatory obligation resolved to zero tests |
| 4 | cd-gate | no deploy-gate file from the build stage |
| 5 | verify | a sealed document was edited after sealing |

## Current limitations

Semantic churn can still over-report (never under-report) on annotation-heavy libraries,
because annotation attribute bodies are hash-compared rather than value-resolved. Method
level reachability uses conservative dispatch (all overrides/implementors), so closures on
highly polymorphic code remain wider than a true points-to analysis would produce.
`dependency:tree` text is a planned second graph input; today the declared graph must be a
CycloneDX SBOM. For real, credentialed numbers, build `sample-app/` against the Lightwell
remediated repo (see `sample-app/README.md`) — its jackson-databind path is the measured
hero: grade B, 0.3% churn, 0 incompatible on the real `2.13.4 → 2.13.4.rhlw-00001` rebuild.
