# Demo Script — presenter's guide

Total: ~25 minutes plus questions. The terminal does the proving; you do the framing.
Run `./demo.sh` with Enter-to-advance (default) so you control pacing. Rehearse once with
`DEMO_AUTOPLAY=1 DEMO_TYPE_DELAY=0 ./demo.sh` to see every beat land.

Audience calibration before you start: if the room is CAB/release-management heavy, spend
longer on beats 6, 9, and 11 (reports, sealing, deploy gate). If it is engineering heavy,
spend longer on beats 7 and 8 (method-level precision, fat-jar hazards). Never cut beat 10
(failure modes) for either audience — it is where trust is actually earned.

---

## Opening (2 min, before touching the terminal)

> "Quick history: we came to you before with a demo about patching without rebuilding.
> You told us — correctly — that you're not changing how you package applications. We
> listened. Nothing you'll see today asks you to change anything about your build. Fat
> jars, rebuild-and-redeploy, exactly as you work now.
>
> Here's the question we're answering instead. When Log4Shell hit, the rebuild took four
> minutes. The six weeks went to the regression run nobody could justify shrinking, and
> the change board that wouldn't approve until someone could. So: **an upgrade fixes the
> CVE — how much of your test suite does it actually owe, and can you prove that number
> to your change board?** Today the honest answer everywhere is 'we don't know, so we run
> everything.' Let's replace that."

Do not oversell the corpus: say once, plainly, that today's libraries are compiled samples
mirroring the Log4j shapes, that the same commands run on real Maven Central artifacts,
and that you'll happily run the real pairs in their environment. Pre-empting this costs
ten seconds; being caught by it costs the meeting.

## Beat 1 — Setup (1 min)

The script states the scenario: one CVE, two artifacts that close it — the community
forward-upgrade and a maintained backport. Land the line: "Same CVE. Nobody today can say
in advance how much testing each path owes. Watch the tool say it."

## Beat 2 — Forward upgrade → F (2 min)

Let the output breathe, then:

> "That verdict *is* the six weeks. And notice what it isn't: it isn't a policy or an
> opinion. It's a structural diff of two real jars intersected with this application's
> own bytecode. The app calls a member that no longer exists — this path doesn't need a
> bigger test plan, it needs a migration, and now you know that *before* you start."

## Beat 3 — Backport → A (2 min)

> "Same CVE closed. One class changed. The application touches nothing that moved. Smoke,
> canary, promote. The six-week difference was never the code — it was which artifact you
> sourced. Until now that was a vendor claim; now it's a number anyone in this room can
> recompute."

This is the commercial heart. Pause here.

## Beat 4 — The honest B (1 min)

> "And the rule doesn't take version numbers on faith. This one *claims* to be a patch —
> half the internals rewritten, a shipped default flipped — so it does not get the fast
> lane. Escalation is automatic; that's what makes the fast lane defensible when it is
> granted."

## Beat 5 — Trusting the churn number (2 min)

The verify harness runs live. This beat exists for the most skeptical engineer present:

> "Your first instinct should be: hash two identical builds from different toolchains and
> watch a naive tool report 100% churn. So we do exactly that, in front of you. Every
> byte differs; semantic churn zero. The one real method edit still reads 6.2%. And
> anything the fingerprint can't parse falls back to raw hashing — this metric is allowed
> to over-report, it is structurally unable to under-report."

## Beat 6 — Published catalog (1 min)

Open `out/reports/index.html` in a browser beforehand; alt-tab to it.

> "One certificate per remediated artifact — rating, evidence, and a printed section
> called *what this report cannot see*. In most shops the bottleneck isn't the engineer's
> confidence, it's the approval. The report is the product; the analysis is how we make it."

## Beat 7 — Project scorecard, transitives, method-level precision (4 min)

Three ideas, keep them separated:

> "First: the score never averages and risk never rolls up. A transitive counts at full
> weight — one migration-grade dependency makes this a migration-grade project. But the
> *work plan* rolls up, because the fix lever lives at the parent: bump it or pin an
> override. Two audiences, one page: the top third is for approval, the middle is
> Monday's tasks.
>
> Second: acme-codec never appears in this app's bytecode at all. The SBOM says the http
> client brought it in; reachability walks app → parent's call graph → codec. And it does
> that at *method* level — see the line where class-granular analysis would have flagged
> the removed member, because a debug method the app never calls reaches it. Method-level
> proves the path unreached. Without that precision, real frameworks inflate every blast
> radius and the de-escalation value evaporates.
>
> Third: the de-escalation is *offered, not applied*. It takes an explicit sign-off flag,
> the flag is recorded, and the same project fails the CI gate without it and passes with
> it. The gate enforces the conversation."

## Beat 8 — Enterprise reality: reactors, fat jars, hazards (2 min)

> "Same scan, three packagings — thin jar, reactor modules, uber jar — same grade.
> On the uber jar, three things you've likely been bitten by: bundled dependency
> internals are excluded from *your* code's view; the SBOM-vs-artifact drift check
> catches the tree you declared not matching the tree you shipped; and there's a
> relocated shaded copy of the codec in here — classpath roulette — surfaced as a
> hazard row. The SBOM is the map. The artifact is the territory. We check both."

## Beat 9 — Test routing and the CD handoff (4 min)

> "Now the loop closes. The scanner emitted affected *code* — never test names, because
> your test topology is yours. The router joins that with your own coverage map, with
> provenance: which build, which SHA, how stale. Read the reasons: every RUN traces to a
> changed member. That test ran because it's *absent from the map* — unknown means run.
> That one widened in because it covers code modified since the map was collected. And
> the boot test appended as mandatory — declared by a tag *in the test source*, resolved
> at run time, and it would run even if the join selected nothing. 'Seven of eleven,
> here's why for each' is what turns a shortcut into a CAB artifact.
>
> Then watch a *different process* consume the gate file at deploy time. The build never
> claims it ran the canary — a build plugin claiming that would be exactly the false
> assurance we're eliminating. It emits the obligation OPEN; the deployment stage closes
> it. One unbroken, truthful chain."

## Beat 10 — Failure modes (2 min) — do not cut this

> "Any tool can demo its happy path. Watch this one fail, on purpose. Stale coverage —
> full suite, loudly, with the refusal reason on every line. Someone untagged the boot
> test — hard build failure naming the stale declaration; the gate cannot silently
> vanish. Deploy without a gate file — blocked. The only failure modes this system
> permits are too many tests, a failed build, and a blocked promotion. Never a silently
> skipped gate. Tools in this category die the first time they're caught silently wrong."

## Beat 11 — Sealing (1 min)

> "Last: someone edits the grade from B to A after the fact. Caught — signatures are over
> canonical JSON, so reformatting is harmless and a value edit is fatal. To a change
> board, an unsigned JSON is a text document; a sealed one is an audit artifact.
> Production path is Sigstore keyless in CI; local keys exist because some of you are
> air-gapped, and this whole design assumes your code never leaves your building."

## Close (1 min)

> "So, end to end: measure the delta, rate it, publish it with every artifact, score your
> whole project with transitives at full weight, route the exact tests with reasons, and
> hand explicit obligations to your deploy gate — sealed at every step. And one caveat we
> print on every report rather than whisper: static analysis can't see everything, which
> is why the canary and the rollback never leave the plan, even at grade A. The tool
> sizes the risk. It doesn't abolish it.
>
> What we'd like from you isn't a purchase order — it's twenty minutes on three questions:
> when a critical CVE lands, what's your longest pole; how do you decide today how much
> to retest a dependency bump; and do you keep per-test coverage data. Your answers
> decide what we build next."

---

## Objection handling

**"Endor Labs already does upgrade impact analysis."** Agree first — it validates the
market, and their docs are honest that low risk isn't a no-break guarantee. Then the four
specifics: they stop at a risk tier, we continue to a named test list with reasons and a
deploy gate; our split means your bytecode never leaves your CI; we measure *any*
maintainer's backport discipline, including unflatteringly, which is what makes the
flattering number credible; and our output is a sealed offline-verifiable document, not a
platform finding. If they need CVE-driven prioritization in one pane, Endor may genuinely
be the better buy — say so; the candor buys more than the point costs.

**"We use Develocity PTS / Launchable for test selection."** Keep them — they're the
right tool for *your commits*. Their unit of change is your code; a dependency bump is a
one-line diff whose real delta is a binary their models have no visibility into. We're
the instrument for the dependency case, and both feed the same Surefire. Also note the
audience split: ML selection answers 'likely useful signal'; a CAB needs 'runs because it
covers the class that calls the member that changed.'

**"Static analysis can't see reflection."** Correct, and we print it rather than footnote
it. Three mitigations: the heuristics comb resources and string constants for library
FQCNs and mark hits as reachable; two-hop evidence carries lower confidence *by rule* —
de-escalating a transitive requires a recorded sign-off; and the canary stays in every
lane including A. Then invert it: today you have the same blind spot with zero of the
visibility.

**"Our jars are shaded/relocated beyond recognition."** Show the hazard row again.
Relocation without bytecode rewriting keeps internal class names, so we detect it from
zip entry paths; full relocation with rewriting is detectable by class-structure
fingerprinting and is on the roadmap — and we'd rather tell you that than pretend.

**"What does a stale SBOM do to this?"** Misleads the transitive analysis — which is why
the artifact-vs-SBOM inventory exists. We trust neither the map nor the territory alone;
disagreement is itself a finding.

**"Can we gate on B instead of D?"** Yes — `--fail-on` is a threshold you own. Start at
D, tighten when the histogram says you can afford to.

**"Is this a product?"** It's a verified prototype with a working pipeline and honest
scaffolds where noted — the Maven plugin compiles the real JUnit-discovery piece, the
mock CD gate stands in for your CD tooling reading one JSON file. What we're validating
with you is which stage is the product. Don't dress this up; regulated buyers smell it.

## Pre-flight checklist

Run the full demo once on the presentation machine the same day. Open the catalog
`index.html` and both scorecards in browser tabs beforehand. Terminal at 18pt+, dark
theme, `demo.sh` from a clean `out/` regeneration. Have `docs/COMPARISON.md` and the
sealed JSONs on hand for the inevitable deep-dive request. If any beat errors live,
skip forward without apologizing twice — the failure-mode beat has, more than once,
converted a live glitch into credibility. Know your one non-negotiable sentence: *from
chosen upgrade to deploy gate, nobody else produces this chain.*
