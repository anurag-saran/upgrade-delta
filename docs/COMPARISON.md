# Competitive Landscape — where upgrade-delta sits, honestly

Accurate as of mid-2026 to the best of available public documentation; verify current
competitor capabilities before quoting this in front of a customer — this market moves.

## The one-sentence positioning

Every tool below answers either "*should* I upgrade?" (the SCA world) or "which tests
should run for *my code change*?" (the test-selection world). Nobody occupies the seam
between them: **given a dependency delta, which of my tests does this upgrade owe, with
evidence an auditor can verify?** A dependency bump is a one-line git diff, which is
exactly why change-based test selectors under-serve it, and SCA tools stop at risk labels
before the testing question begins.

## The map

| | Measures library delta | Intersects YOUR app | Continues to test scope | Audit-grade evidence | Air-gap / no code egress | CVE data |
|---|---|---|---|---|---|---|
| **upgrade-delta** | yes (API + semantic churn + behavior surface) | yes, method-level | yes — named tests with reasons | sealed JSON chain, sign-offs recorded | yes, by construction | no (deliberate) |
| Endor Labs UIA | yes (breaking-change prediction) | yes (reachability) | no — stops at risk tier | dashboard/findings | SaaS-centric | yes (core business) |
| Snyk / Sonatype / OWASP DC | version + vuln metadata | limited/none | no | findings/reports | varies / DC yes | yes (core business) |
| Develocity PTS | no (keys off build-input fingerprints) | n/a | yes — ML-selected tests | Build Scan explanations | self-hosted option | no |
| Launchable | no (keys off code changes) | n/a | yes — ML-selected tests | selection reasons | SaaS | no |
| Renovate / Dependabot | changelog surfacing | no | no | PR metadata | Renovate self-hosted | advisory feeds |
| japicmp / Revapi | yes (API only) | no | no | textual reports | yes (CLI) | no |

## The comparisons that matter

### Endor Labs Upgrade Impact Analysis — the closest neighbor

Endor Labs is the validation case: a well-funded company built program-analysis-based
upgrade assessment because customers pay for it. Their Upgrade Impact Analysis uses
program analysis at build time to identify breaking changes and assigns each upgrade a
High/Medium/Low remediation risk; Endor Patches offer backported fixes when the upgrade
is too costly; automated PRs deliver it. Their own documentation is admirably honest that
low risk means minimal evidence of breakage, not a guarantee.

Do not pretend this overlap away — someone in every serious room will know the product.
The differentiation must be specific, and it is fourfold. First, **they stop where the six
weeks start**: a risk tier tells you an upgrade is dangerous; it does not tell you which
37 of your 4,000 tests to run, and no obligations flow to your CD pipeline. upgrade-delta's
last three stages (routing payload → coverage join → deploy gate) have no counterpart.
Second, **the trust boundary**: Endor's model is platform-centric; upgrade-delta's
publisher/consumer split means the customer's bytecode never leaves their CI, which for
regulated shops is the entry ticket rather than a feature. Third, **whose backport thesis
gets proven**: Endor Patches are Endor's own product; upgrade-delta makes *any*
maintainer's z-stream discipline measurable — the same tool would report an unflattering
number, which is what makes the flattering number credible. Fourth, **the artifact**:
Endor produces findings in a platform; upgrade-delta produces sealed documents designed to
be handed to a change board and verified offline.

The honest reverse view: Endor brings vulnerability intelligence, ecosystem breadth beyond
the JVM, years of program-analysis engineering, and a company behind it. If a customer
needs CVE-driven prioritization and upgrade risk in one platform and has no test-scope or
air-gap requirement, Endor is the safer buy today — and reselling rather than competing
remains a legitimate strategic outcome, as the pivot document said from the start.

### Develocity Predictive Test Selection and Launchable — the other half of the seam

These are the industry's serious test-selection products, and they are genuinely good at
their goal: fast developer feedback on every commit. Develocity PTS trains an ML model on
the organization's build history, fingerprints what each build's inputs changed (catching
toolchain bumps and generated files that a git diff misses), scores every candidate test,
always runs recently-failed/flaky/new tests, and records per-test selection reasons in
Build Scans, with reported time savings up to 70–90%. Launchable applies the same ML
approach keyed to code changes.

The gap they leave is structural, not accidental. Their unit of change is *your commit*;
a dependency bump is a one-line manifest edit whose real change lives in a binary the
model has no delta for. An input-fingerprint system will notice *that* the classpath
changed and react conservatively — typically by selecting broadly — but it cannot reason
about *what* changed inside the jar, cannot distinguish a disciplined backport from a
rewritten minor release, and cannot produce the auditor's sentence "this test runs because
it covers the class that calls the member that changed." Conversely, upgrade-delta is
deliberately not a general-purpose selector: for ordinary application commits, PTS-style
tools are the right instrument, and the two compose — PTS for your code changes,
upgrade-delta for your dependency changes, Surefire consuming both.

The philosophical split (decision 2 in the design document) bears repeating: ML selection
optimizes speed and learns likelihood; rule-based joining optimizes explainability and
proves lineage. A CAB accepts the second; a developer waiting on CI prefers the first.
Different audiences, different correct answers.

### Snyk, Sonatype, OWASP Dependency-Check — the SCA incumbents

These answer "what is vulnerable and what version fixes it," with mature databases,
license compliance, and policy engines. None measure how much a fix-version changed, none
intersect that change with the consuming application at member level, and none touch test
scope. They are upstream of upgrade-delta, not competitive with it: their output ("you
must move off 2.14.1") is this tool's input. The integration posture is deliberately
"compose, don't replace" — which is also why upgrade-delta carries no CVE data of its own.

### Renovate and Dependabot — the delivery rails

They open the PR; they do not evaluate it beyond changelogs and advisories. upgrade-delta
treats them as the workflow vehicle: the GitHub Action comments the scorecard onto the PR
they opened. No competition, pure complement.

### japicmp and Revapi — the ancestors

Excellent, battle-tested API-diff tools for the JVM, and the original demo used japicmp
directly. They compute signal one of five: the API delta between two jars, from the
library's point of view. They do not compute semantic churn, behavior surface, or stream
priors; do not intersect with a consuming application; and produce reports, not decisions.
upgrade-delta's dependency-free Python differ exists mainly for the zero-install CI story;
in a JVM-native production build, embedding japicmp/Revapi for signal one while keeping
the rest of the pipeline would be a defensible engineering choice.

### Azure DevOps Test Impact Analysis and academic RTS

Microsoft's TIA and the research lineage behind regression test selection (Ekstazi,
STARTS) select tests from code-change dependency tracking. Same structural limitation as
the ML selectors for this use case: the dependency bump's real delta is invisible to
source-diff-driven tooling, and the JVM-external evidence chain (sealed reports, deploy
gates) has no counterpart there.

## Where upgrade-delta honestly loses

Breadth: JVM-only today, versus multi-ecosystem SCA platforms. Maturity: a verified
prototype versus products with years of production hardening. Intelligence: no
vulnerability data and no learned model, by explicit choice — customers wanting one pane
of glass for security posture will not find it here. Precision ceiling: conservative
dispatch and hash-compared annotations over-approximate relative to Endor-class program
analysis on hostile inputs. And organizational: a tool without a support organization is
an evaluation, not a purchase — the productization phase (Action, plugin, sealing) narrows
this but does not close it.

## The claim to defend in any bake-off

Hold this sentence and concede everything else gracefully: *from the moment an upgrade is
chosen, no other tool on this table can produce a sealed, offline-verifiable chain from
changed library members, through method-level reachability in this specific application,
to a named test list with per-test reasons, to explicit open obligations consumed by the
deployment gate.* If a competitor demonstrates that chain end-to-end, this document is out
of date — re-verify before the meeting.
