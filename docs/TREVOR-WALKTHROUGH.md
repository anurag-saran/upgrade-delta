# Walkthrough — static chain + test gate (stable links)

Short durable guide for reviewing what upgrade-delta already ships. Prefer these
links over ad-hoc sandbox URLs that get recycled.

## Stable scorecard

Live demo Route (project `upgrade-delta-demo`):

**https://scorecard-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html**

Committed snapshot (always available offline):
[`examples/scorecard.html`](../examples/scorecard.html).

Repo: https://github.com/anurag-saran/upgrade-delta

## Two jobs (don’t blur them)

| Job | What it is | When |
|---|---|---|
| **Static grade** | Reachability ∩ published delta → A–F early signal | Before / without a full suite |
| **Test gate** | Select → run → pass/fail on the scorecard | After tests; this is the merge gate |

JaCoCo is **not** a second grade. Class-level “look here” for reflection/DI is
optional diagnostics later — not required once selected tests pass.

## What to look for on the scorecard

1. **Eyebrow / jobs blurb** — “static grade early · tests decide the gate.”
2. **snakeyaml F** — app reaches a removed / incompatible constructor; honest note
   that reflection/DI is still invisible to static analysis.
3. **Internal call-chain** (when present in reasons) — entry point → library method
   you never name, but an internal path hits a changed member. One-hop static
   would miss it; this tool already grades it.
4. **Transitive / sign-off** — de-escalation never silent; `--accept-transitive-scope`
   is explicit. Reflection blindness compounds across hops.
5. **Config & reflection heuristics** — FQCNs found in resources/string constants
   (cheap slice of the blind spot, made visible).
6. **Test outcomes on each Do: row** — after the pipeline runs MiniRunner /
   Surefire, pass/fail is attributed per library when selection or coverage map
   allows it.

## Demo pipeline shape

`analyze/scan → select-tests → run-tests → grade-gate (fail-on ≥ D) → summary`

Same shape on the live `pom.xml`-diff pipeline: early tasks do **not** fail on
grade; the gate runs **after** tests so the scorecard still carries outcomes.

## Presenter path

Full console + GitHub run-of-show: [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md).
