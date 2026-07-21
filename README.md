# upgrade-delta

**How much testing does this dependency upgrade actually owe you — and can you prove
that number to your change board?**

## Quick start on OpenShift

Run the interactive setup — it prints the full credential list, then prompts for each and
stores them (cluster Secrets + a local `.env.local`):

```bash
./setup-openshift.sh
```

Then follow the "remaining setup" steps it prints (enable PaC, apply the gate + tasks,
`opc pac bootstrap`, open a PR). Credential reference: `CREDENTIALS.md`.

## Real app on Red Hat Lightwell + OpenShift PR pipeline

`sample-app/` is a **real Spring Boot service** whose every dependency is a genuine
Lightwell *remediated* artifact at the exact serviced version (jackson-databind,
spring-web/webmvc/core, spring-boot, spring-security, commons-io, httpclient, json-smart —
all `…redhat-NNNNN`). No mock libraries. It calls `ObjectMapper.readValue` and Apache
HttpClient directly, so upgrade-delta's app-intersection measures against the real rebuilds.

- Build it (needs Lightwell creds): `cd sample-app && cp settings.xml.template settings.xml && mvn -s settings.xml clean package`
- Pull the raw jars instead: `./fetch-lightwell-app-jars.sh`
- **OpenShift, PR-triggered, with CAB approval + Sigstore sealing**: every pull request
  builds the app against Lightwell, runs upgrade-delta, **pauses for a human CAB approval**
  (`opc approvaltask approve`), then **keyless-signs the approved scorecard against Red Hat
  Trusted Artifact Signer** (Sigstore: Fulcio + Rekor) and reports back onto the PR.
  Runbooks: `integration/tekton/pac/README.md` (PR + approval) and
  `integration/tekton/rhtas/README.md` (Sigstore sealing).

The `samples/` corpus (compiled mini-libraries) still exists for the offline `./demo.sh`
walkthrough, which needs no credentials or network. The real app is the credentialed,
production-shaped path; the corpus is the zero-dependency teaching path.

---

When a CVE forces an upgrade, the rebuild takes minutes; the weeks go to the regression
run nobody can justify shrinking and the approval that waits on proof nobody has.
upgrade-delta measures how much a library *actually changed*, intersects that change with
*your* application's bytecode (method-level, locally — your code never leaves your CI),
turns the result into a rated test lane, routes the exact tests with a printed reason for
each, and hands explicit open obligations to your deploy gate. Every artifact in the chain
is machine-readable JSON, and the chain can be cryptographically sealed.

Zero runtime dependencies for the core tool: `upgrade_delta.py` is one Python file that
parses `.class` files directly — no JVM, no pip installs.

## Quickstart

```bash
./demo.sh                 # full narrated demo, offline; builds the sample corpus
                          #   on first run (needs any JDK 11+ on PATH or JAVA_HOME)
python3 samples/verify_churn.py                       # churn-normalization proofs
python3 integration/jacoco/jacoco2coverage.py --selftest   # JaCoCo parser round-trip
python3 upgrade_delta.py coverage \
    --sbom samples/realworld-springboot-sbom.json \
    --catalog catalogs/lightwell-remediated-java-sbom.json   # the coverage meter
```

**The coverage meter** matches an application's CycloneDX SBOM against the real Lightwell
remediated catalog and buckets every dependency three ways: an exact-version remediated
build exists (drop-in: same version + `.redhat`/`.rhlw` suffix, no code changes), the
artifact is serviced at another version (the FSI-tier request path), or uncovered (an
upgrade tested blind today). Generate your own SBOM with the `cyclonedx-maven-plugin` and
point `--sbom` at it; `lightwell-report.sh` then produces the full delta report for any
covered pair.

Browsable without running anything: see `examples/` and `docs/`.

## Repository layout

```
upgrade_delta.py        the tool: analyze | publish | scan | seal | verify
test_router.py          consumer-side test router (executable spec for the Maven plugin)
demo.sh                 narrated end-to-end demo, incl. the deliberate failure modes
mock-cd-gate.sh         deploy-stage consumer of deploy-gate.json
samples/                sample corpus generator + test sources + coverage maps
catalogs/               the real Lightwell remediated-catalog SBOM (drives `coverage`)
integration/            jacoco converter · GitHub Action · Jenkins · Tekton/OpenShift
                        Pipelines (demo runbook) · Maven-plugin scaffold · signing notes
docs/                   user guide · design decisions · competitive comparison ·
                        presenter demo script · original pivot doc · the deck (pptx)
examples/               committed, sealed sample outputs (see examples/README.md)
```

Generated directories (`out/`, `samples/jars/`, `real-jars/`) are gitignored and
reproduced by `demo.sh`. Private signing keys are gitignored; never commit a `.pem`.

## Documentation

| Doc | What it covers |
|---|---|
| `docs/USER-GUIDE.md` | Concepts, command reference, workflows, exit codes, limitations |
| `docs/DESIGN-DECISIONS.md` | Thirteen decisions with rationale and honest costs |
| `docs/COMPARISON.md` | Endor Labs, Develocity PTS, Launchable, SCA incumbents — and the unoccupied seam |
| `docs/DEMO-SCRIPT.md` | Presenter talk track, timings, objection handling |
| `docs/PIVOT-upgrade-delta-to-test-scope.md` | Where this came from and why |
| `docs/deck/upgrade-delta-deck.pptx` | The customer deck (Red Hat Lightwell template) |

## Status & scope

Verified prototype, JVM ecosystem. All pipeline stages run end-to-end against the sample
corpus with their failure modes demonstrated; the Maven plugin is an honest scaffold
(`test_router.py` is its executable behavior spec). Internal Red Hat material — do not
distribute externally; licensing to be settled before any external release.

## What the tool measures (per upgrade)

1. **API delta** — public members removed / added / modified, with binary-incompatible
   changes called out separately.
2. **Implementation churn** — % of shared classes whose bytecode changed *semantically*.
   Raw byte-hashing lies on real-world jars: different javac versions and `-g` flags change
   every byte with zero behavior change. Churn here is a semantic fingerprint: debug attributes
   (LineNumberTable, LocalVariableTable, SourceFile, StackMapTable, MethodParameters...) are
   stripped, members sorted, and bytecode is walked instruction-by-instruction with every
   constant-pool index resolved to its value — including inside `BootstrapMethods`, whose
   raw body shifts with unrelated pool changes. Verified by `samples/verify_churn.py`:
   identical source built with different toolchain flags = 100% raw diff, **0.0% semantic
   churn**; a single real method edit still reads as churn; unparseable classes fall back
   to the raw hash, so the fingerprint can over-report but never under-report. Reports show
   the excluded build-noise count alongside the churn figure.
3. **Behavior surface** — bundled defaults/resources and `META-INF/services` SPI entries
   that changed. Catches the deserialization/config class of change: zero API movement, big behavior shift.
4. **Stream class** — z / y / x (patch / minor / major), the prior on intent.
5. **Your app, specifically** — walks the application's own constant pools and intersects
   its call sites with the changed-member set: *"this library changed 214 members;
   you touch 4 — here they are."*

## The rating (printed on every report)

| Grade | Meaning | Test lane |
|---|---|---|
| **A** | z-stream, no API change, minimal churn, no default/SPI changes | Fast lane: smoke + canary |
| **B** | z-stream but with added surface, heavy churn, or shipped-default changes | Targeted tests on the calling packages + canary |
| **C** | y-stream, no incompatibilities | Partial regression + production-like boot test |
| **D** | Binary-incompatible changes, or x-stream | Full regression |
| **F** | Incompatible changes **your app provably calls** | Migration first, then full regression |

Escalation is evidence-based (a "patch" with 50% churn does not get the fast lane), and
de-escalation is only ever suggested, never silent: a C/D upgrade whose changed members the
app never touches is flagged as a *scope-shrink candidate with sign-off*, canary retained.

Every report ends with **"What this report cannot see"** — reflection, config-driven
instantiation, and behavior changes with no structural fingerprint. That's why the canary
and rollback stay in the plan for every grade, including A. The honesty is the credibility.

## Run it

```bash
./demo.sh                          # narrated demo, fully offline
python3 upgrade_delta.py analyze old.jar new.jar --app yourapp.jar \
    --old-version 1.2.3 --new-version 1.2.4 --library mylib \
    --json evidence.json --html report.html
python3 upgrade_delta.py publish evidence/*.json --out site/
python3 upgrade_delta.py scan yourapp.jar --evidence evidence/ \
    --html scorecard.html --json scorecard.json --fail-on D   # CI gate
```

## The project scorecard (`scan`)

Publisher/consumer split, on purpose: `analyze` runs **once, at publish time, app-agnostic** —
its evidence JSON now carries a machine-readable section. `scan` runs **in the customer's CI**:
it re-runs only the app-intersection locally (their bytecode never leaves the machine), scores
every rated dependency, and emits a project scorecard that is deliberately *not* an average:

- **Headline = worst pending grade** across the best available remediation path per library.
- **With/without comparison** — when a backport path beats the forward path, the scorecard
  shows both project grades; the gap is the backport's value, measured.
- **Lane histogram** — the actual test-effort budget to get current.
- **Unrated whitespace** — third-party packages the app calls with no published report.
- **`--fail-on <grade>`** — exit 2 for CI gating (verified: F-only evidence fails the gate).

### Transitives: flattened in the score, rolled up in the work plan

Pass `--sbom` (CycloneDX JSON — the declared graph: who brought in whom) and `--lib-jars`
(the resolved classpath) and the scan handles transitive dependencies with a deliberate split:

- **Score/histogram: flattened.** A transitive counts at full weight (hatched bar segment).
  Risk never rolls up under its parent — that would be risk laundering.
- **Table: rolled up.** Transitives nest under the parent that brought them in, with the
  actual fix lever printed: bump the parent, or pin an override.
- **Two-hop reachability.** The app rarely references a transitive directly, so the scan
  BFS-walks the parent's class graph from the classes the app references, then intersects
  the closure's outbound calls with the transitive's changed members — and prints the
  chain (`HttpClient → Retry → Base64Codec.encode`).
- **De-escalation requires sign-off.** Reflection blindness compounds across hops, so a
  transitive whose changed members are unreachable is *offered* a scope shrink but only
  gets it under `--accept-transitive-scope`, and the report records that it was signed off
  (`D → B`). Verified both ways: the same project fails `--fail-on D` without the flag and
  passes with it.
- **Stream switches are labeled.** A remediation path whose starting version differs from
  the installed version (per SBOM) is tagged `stream switch` rather than silently recommended.

The scanner never invokes Maven/Gradle itself: the graph arrives as a static artifact
(SBOM now; `dependency:tree` text output is a planned alternate input). Reasons: air-gapped
CI, determinism, and a security scanner should not execute the build it is auditing.

## The test router (`test_router.py` + `mock-cd-gate.sh`)

The bridge to "run these 37 tests, here's why", as a three-stage pipeline with two contracts:

1. **`scan --routing-payload routing.json`** emits *affected code*, never test names:
   changed members, the app classes owning call sites into them, lanes, a confidence block
   (direct vs two-hop, sign-offs), and obligations split into **in-scope** (boot test,
   declared via `@Tag("upgrade-gate")` in the test source) and **downstream** (canary,
   rollback — deployment-stage activities a build plugin must never claim to have run).
2. **The router** (stand-in for the Maven plugin) joins the payload with the customer's
   per-test coverage map — with provenance (SHA, build, age) — and emits a Surefire
   `includesFile`, a selection report where every RUN and skip has a printed reason, and
   `deploy-gate.json` for the CD pipeline.
3. **The CD gate** is a separate process that consumes the gate file and refuses to promote
   until the open obligations are closed at its own stage.

Fail-closed rules, all demonstrated in `demo.sh`: unknown test → runs; stale/unreadable
coverage → full suite, loudly; Partial/Full lanes → no shrinking; a declared mandatory
obligation resolving to zero tests → hard build failure (someone untagged the gate test);
missing gate file → promotion blocked. Wrong answers are always loud — too many tests, a
failed build, a blocked deploy — never a silently skipped gate.

## Phase 2 — enterprise reality (implemented)

- **Method-level call graphs**: two-hop reachability now walks caller→callee edges
  extracted per-method from bytecode, with conservative virtual/interface dispatch
  (super-chain + overrides + implementors). The scorecard prints the precision delta:
  on the corpus, class-granular analysis would flag the codec's removed `Hex.encode`
  (reachable only via `debugDump()`, which the app never calls); method-granular proves
  the path unreached and the sign-off survives. Class-level numbers are kept as the
  comparison figure, never the verdict.
- **Config/reflection heuristics**: resources and string constants are combed for rated
  libraries' FQCNs (`Class.forName` literals, DI/XML, properties, SPI files). Hits that
  intersect changed/removed classes on the *recommended* path are marked "treat as
  reachable" — the cheap slice of the reflection blind spot, surfaced instead of disclaimed.
- **Reactor + fat jars**: `scan` accepts multiple module jars and merges them. Fat jars
  get an inventory pass: `META-INF/maven/*/pom.properties` fingerprints vs the SBOM
  (declared-not-shipped / shipped-not-declared / version-drift), bundled dependency
  classes are excluded from the application view, and **relocated shaded copies** are
  detected via zip entry paths (relocation without bytecode rewriting keeps internal
  class names — the path is the only witness).

## Phase 3 — productization (implemented / scaffolded)

- **JaCoCo ingestion** (`integration/jacoco/`): a real `.exec` binary parser
  (header/session/execution-data blocks, varint, LSB-first bit packing) with a
  round-trip selftest, a converter to the router's `coverage.json` (provenance
  embedded), and the Maven per-test-class collection profile with its trade-offs
  stated plainly.
- **Sealing** (`seal` / `verify`): detached Ed25519 signatures over canonical JSON —
  reformat-safe, edit-fatal (verified: a grade edited after sealing fails with exit 5).
  Production path is Sigstore keyless in CI (`integration/signing.md`); local keys stay
  for air-gapped shops.
- **Delivery** (`integration/github-action/`, `integration/jenkins/`): a composite
  Action that scans, comments the scorecard markdown on the PR, uploads artifacts, and
  enforces the gate; `pr_comment.py` is tested against the real scorecard JSON.
- **Maven plugin** (`integration/maven-plugin/`): honest scaffold — not compiled here —
  whose one fully-written part is the piece the mock faked: mandatory-test resolution
  via genuine JUnit Platform `TagFilter` discovery, failing the build on zero
  resolutions. `test_router.py` remains the executable behavior spec.

## Where this goes next (from the pivot doc)

- Validate with 5 customer calls before investing further (regression vs. rebuild vs.
  approval — which is the long pole?).
- Phase 3: JaCoCo per-test coverage → "run these 37 of your 4,000 tests, named."
  Only build it if customers confirm they keep per-test coverage data.
- CI delivery: attach the JSON + report card to every Renovate PR; publish the catalog
  per Lightwell artifact.
- Prior art: Endor Labs' Upgrade Impact Analysis stops at *risk*; nothing on the market
  continues from **dependency delta → concrete test scope**. That gap is this tool's claim.
