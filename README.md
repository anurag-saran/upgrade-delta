# upgrade-delta

**How much testing does this dependency upgrade actually owe you — and can you prove that
number to your change board?**

When a CVE forces an upgrade, the rebuild takes minutes; the weeks go to the regression run
nobody can justify shrinking and the approval that waits on proof nobody has. upgrade-delta
measures how much a library *actually changed*, intersects that change with *your*
application's bytecode (method-level, locally — your code never leaves your CI), turns the
result into a rated test lane, routes the exact tests with a printed reason for each, and
hands the open obligations to your deploy gate. Every artifact in the chain is
machine-readable JSON, and the chain can be cryptographically sealed.

The core tool is one dependency-free Python file (`upgrade_delta.py`) that parses `.class`
files directly — no JVM, no pip installs.

---

## Demo it on OpenShift — console + GitHub only

> **New to upgrade-delta?** Read [`docs/DEMO-101.md`](docs/DEMO-101.md) first, then
> [`docs/DEMO-HANDS-ON.md`](docs/DEMO-HANDS-ON.md) (`./demo.sh` + optional cluster walk).

> **Want it grading your team's real repo instead of this fixture?** See
> [`integration/tekton/real-pipeline/README.md`](integration/tekton/real-pipeline/README.md) —
> a separate pipeline that diffs a PR's real `pom.xml`, downloads the real old/new jars, and
> grades the real impact. This section below is the fixture-based demo.


The headline path: open a pull request on GitHub, and an OpenShift pipeline automatically
scores the upgrade and shows the verdict in the console. **No terminal on your side.** The
base demo runs on fixtures committed to this repo, so it needs **no credentials, no JDK, no
network beyond the clone.**

1. **Install** (once): [`docs/INSTALL-OPENSHIFT.md`](docs/INSTALL-OPENSHIFT.md) — install the
   OpenShift Pipelines Operator from OperatorHub, apply the resources in [`deploy/`](deploy/),
   and connect GitHub with a Pipelines-as-Code GitHub App. All in the console + github.com.
2. **Learn + try:** [`docs/DEMO-101.md`](docs/DEMO-101.md) ·
   [`docs/DEMO-HANDS-ON.md`](docs/DEMO-HANDS-ON.md) · presenter script
   [`docs/DEMO-SCRIPT.md`](docs/DEMO-SCRIPT.md). Scorecard callouts:
   [`docs/TREVOR-WALKTHROUGH.md`](docs/TREVOR-WALKTHROUGH.md).
   **Tekton object catalog (enablement):**
   [`docs/TEKTON-ENABLEMENT.md`](docs/TEKTON-ENABLEMENT.md).

**Two jobs:** the **static grade** is an early signal (reachability ∩ delta). **Selected
tests that pass or fail** are the real merge gate. Reflection/DI stays invisible to static
analysis — transitive de-escalation needs explicit sign-off; we do not treat JaCoCo as a
second grade.

**What a run produces** (verified on `upgrade-delta-demo-real-w4hdx`): grade **F** ·
coverage **59%** (16 drop-in / 1 serviced elsewhere / 10 uncovered) · scorecard rows
**spring-core B / json-path C / snakeyaml F** · tests **9 passed / 0 failed** (6 classes
selected). The PipelineRun goes red at **grade-gate** (F ≥ D) *after* tests so the
scorecard and PR comment still carry pass/fail. Artifacts:
[`examples/scorecard.html`](examples/scorecard.html),
[`examples/coverage.html`](examples/coverage.html),
[`examples/pr-comment.md`](examples/pr-comment.md). Live Route:
https://scorecard-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html.

How the pieces fit:

```
GitHub PR  ──(Pipelines-as-Code webhook)──►  OpenShift Pipelines
   │                                              │
   │   .tekton/pull-request.yaml                  ├─ clone    (git-clone)
   │   → pipeline: upgrade-delta-demo             ├─ coverage (upgrade_delta.py coverage)
   │                                              ├─ scan     (upgrade_delta.py scan → grade; fail-on empty)
   │                                              ├─ select-tests (test_router.py — pick which tests are owed)
   │                                              ├─ run-tests    (execute them for real, JVM)
   │                                              ├─ grade-gate   (fail when project grade ≥ D)
   │                                              ├─ summary  (finally: prints the VERDICT banner)
   │                                              └─ pr-comment (finally: posts the CAB summary on the PR)
   │                                              │
   ▼                                              ▼
 required check ◄──── CAB comment on the PR ◄──── PipelineRun Results + summary log + nginx viewer Route
```

---

## What the tool measures (per upgrade)

1. **API delta** — public members removed / added / modified, binary-incompatible changes
   called out separately.
2. **Implementation churn** — % of shared classes whose bytecode changed *semantically*. Raw
   byte-hashing lies on real jars: different `javac` versions and `-g` flags change every byte
   with zero behavior change. Churn here is a semantic fingerprint — debug attributes
   stripped, members sorted, bytecode walked instruction-by-instruction with every
   constant-pool index resolved to its value. Unparseable classes fall back to the raw hash,
   so the fingerprint can over-report but never under-report.
3. **Behavior surface** — bundled defaults/resources and `META-INF/services` SPI entries that
   changed. Catches the deserialization/config class of change: zero API movement, big
   behavior shift.
4. **Stream class** — z / y / x (patch / minor / major), the prior on intent.
5. **Your app, specifically** — walks the app's own constant pools and intersects its call
   sites with the changed-member set: *"this library changed 214 members; you touch 4 — here
   they are."*

## The rating (printed on every report)

| Grade | Meaning | Test lane |
|---|---|---|
| **A** | z-stream, no API change, minimal churn, no default/SPI changes | Fast lane: smoke + canary |
| **B** | z-stream but with added surface, heavy churn, or shipped-default changes | Targeted tests on the calling packages + canary |
| **C** | y-stream, no incompatibilities | Partial regression + production-like boot test |
| **D** | Binary-incompatible changes, or x-stream | Full regression |
| **F** | Incompatible changes **your app provably calls** | Migration first, then full regression |

Escalation is evidence-based (a "patch" with 50% churn does not get the fast lane), and
de-escalation is only ever *suggested*, never silent: a C/D upgrade whose changed members the
app never touches is flagged as a *scope-shrink candidate with sign-off*, canary retained.
Every report ends with **"What this report cannot see"** — reflection, config-driven
instantiation, behavior changes with no structural fingerprint — which is why the canary and
rollback stay in the plan for every grade, including A. The honesty is the credibility.

---

## Explore locally (optional, no cluster)

Everything above runs without OpenShift too. Needs Python 3; the demo builds a small Java
corpus on first run (any JDK 11+ on `PATH` or `JAVA_HOME`).

```bash
./demo.sh                                              # narrated end-to-end demo, offline
python3 upgrade_delta.py coverage \
    --sbom examples/demo-jars/payments-service.sbom.json \
    --catalog catalogs/lightwell-remediated-java-sbom.json   # the coverage meter
python3 upgrade_delta.py scan examples/demo-jars/payments-service-1.0.0.jar \
    --evidence examples/evidence --sbom examples/demo-jars/payments-service.sbom.json \
    --lib-jars examples/demo-jars --accept-transitive-scope \
    --json scorecard.json --html scorecard.html --fail-on D
```

The three commands the OpenShift pipeline runs are exactly these (`coverage`, `scan`,
`test_router.py`). Browsable without running anything: see `examples/` and `docs/`.

### The credentialed "real app" path
`sample-app/` is a real Spring Boot service whose dependencies are genuine Lightwell
*remediated* artifacts (`…redhat-NNNNN`). Building it needs a `console.redhat.com` service
account (`sample-app/settings.xml`, from the template) or `./fetch-lightwell-app-jars.sh`. On
OpenShift this becomes the credentialed pipeline variant — see the add-ons in
[`docs/INSTALL-OPENSHIFT.md`](docs/INSTALL-OPENSHIFT.md) and `integration/tekton/pac/README.md`.

---

## Repository layout

```
upgrade_delta.py        the tool: analyze | publish | scan | seal | verify
test_router.py          consumer-side test router (executable spec for the Maven plugin)
demo.sh                 narrated offline demo, incl. the deliberate failure modes
setup-openshift.sh      scripted cluster setup (namespace, tasks, deploy/, git-clone)
cleanup-openshift.sh    scripted teardown — run before re-installing over a previous version
deploy/                 cluster resources for the console demo: reports PVC + scorecard viewer
.tekton/                Pipelines-as-Code PR trigger (fires the demo pipeline on every PR)
integration/tekton/     the pipeline + tasks, PaC runbook, CAB approval, RHTAS signing
integration/            jacoco converter · GitHub Action · Jenkins · Maven-plugin scaffold
samples/                realworld SBOM mirror + helper scripts
catalogs/               the real Lightwell remediated-catalog SBOM (drives `coverage`)
examples/               real-library evidence, demo jars, tests, and browsable outputs
docs/                   INSTALL-OPENSHIFT · DEMO-SCRIPT · USER-GUIDE · DESIGN-DECISIONS ·
                        COMPARISON · pivot doc · the deck (pptx)
```

Generated dirs (`out/`, `site/`, `samples/jars/`, `real-jars/`) are gitignored and reproduced
by the pipeline / `demo.sh`.

## Documentation

| Doc | What it covers |
|---|---|
| [`docs/INSTALL-OPENSHIFT.md`](docs/INSTALL-OPENSHIFT.md) | Console + GitHub setup, start to finish |
| [`docs/DEMO-SCRIPT.md`](docs/DEMO-SCRIPT.md) | The two-tab presenter run-of-show |
| `docs/USER-GUIDE.md` | Concepts, command reference, workflows, exit codes, limitations |
| `docs/DESIGN-DECISIONS.md` | The decisions, with rationale and honest costs |
| `docs/COMPARISON.md` | Endor Labs, Develocity PTS, Launchable, SCA incumbents — and the seam |
| `integration/tekton/pac/README.md` | PR trigger + CAB approval detail |
| `integration/tekton/rhtas/README.md` | Sigstore / RHTAS evidence signing |

## Security — what is *not* in this repo

Secrets never belong in git. The `.gitignore` blocks them, and this tree ships none:

- **No credentials.** Lightwell/registry tokens live only in cluster Secrets and a local
  `.env.local` (gitignored). Use service-account tokens, never account passwords.
- **No private keys.** `*.pem` is gitignored; only `*.pem.pub` public keys are committed. The
  production signing path is Sigstore keyless (no key to custody).
- If a token ever passed through a chat, a screen-share, or a commit, **rotate it.**

## Status & scope

Verified prototype, JVM ecosystem. The console pipeline runs end-to-end on the committed
real-library corpus (grade F / 59% / spring-core B · json-path C · snakeyaml F /
9 tests passed · grade-gate after tests), with the snakeyaml grade gate demonstrated.
Re-sync committed snapshots anytime with `./demo.sh`. The
live-cluster PaC + signing paths are YAML-valid and documented; budget one shakedown for the
GitHub App webhook and any RWX StorageClass wiring. The Maven plugin is an honest scaffold
(`test_router.py` is its executable behavior spec). Internal Red Hat material — do not
distribute externally; licensing to be settled before any external release.
