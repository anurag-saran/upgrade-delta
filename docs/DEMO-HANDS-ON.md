# Demo script — hands-on (beginner)

Follow this checklist to see the same numbers the cluster demo produces.  
New to the ideas? Read [`DEMO-101.md`](DEMO-101.md) first (~5 min).

**Verified outcome:** grade **F** · coverage **59%** (16 / 1 / 10 of 27) · rows
**spring-core B / json-path C / snakeyaml F** · tests **9 passed / 0 failed**.

---

## Part A — Offline on your laptop (~5 min)

Needs: Python 3. Java is optional (skips MiniRunner if missing; committed
`examples/` snapshots still show the full picture).

```bash
cd upgrade-delta   # this repo
./demo.sh
```

### What just ran

| Step | What it did |
|---|---|
| 1. coverage | Checked every SBOM dep against the Lightwell catalog → `coverage.html` |
| 2. scan | Graded reachability ∩ delta → project **F** (snakeyaml blocks) |
| 3. select-tests | Full-suite fallback (F/C lanes) → 6 of 6 classes |
| 4. MiniRunner | Executed tests with `examples/demo-jars` + `lib/` → **9 / 0** |
| 5. sync | Wrote scorecard + PR comment with test outcomes into `examples/` |

### Open these files

1. `out/reports/coverage.html` — catalog meter (16 drop-in ready).
2. `out/reports/scorecard.html` — look for:
   - Eyebrow: *static grade early · tests decide the gate*
   - Banner: *6 classes · 9 methods · 9 passed · 0 failed*
   - **snakeyaml F** with the breaking `Constructor(TypeDescription, Collection)`
   - **Do:** rows with per-library selected tests
3. `examples/pr-comment.md` — same story as a CAB comment (grades + test plan + results).

> Say this out loud: *“Coverage answers ‘is there a remediated build?’ Scorecard answers
> ‘what will this upgrade cost *this* app?’ Tests that passed are the real gate; F still
> fails policy (≥ D).”*

---

## Part B — OpenShift + GitHub (~10 min)

Setup must already be done: [`INSTALL-OPENSHIFT.md`](INSTALL-OPENSHIFT.md).  
Full presenter beats (what to say): [`DEMO-SCRIPT.md`](DEMO-SCRIPT.md).

### Before you start

- Tab 1: GitHub repo https://github.com/anurag-saran/upgrade-delta  
- Tab 2: OpenShift console → project **`upgrade-delta-demo`**
- Scorecard Route (bookmark):  
  https://scorecard-upgrade-delta-demo.apps.asaran.na-launch.com/out/reports/scorecard.html

### Steps

1. **Trigger** — On GitHub, open a small PR against `main` (edit a README line or the sample
   SBOM). A check named **`upgrade-delta-pr`** goes pending → click **Details**.
2. **Watch the graph** — PipelineRun: clone → coverage → scan → select-tests → run-tests →
   **grade-gate** → summary. Scan does *not* fail early; **grade-gate** fails when F ≥ D.
3. **Results tab** — Confirm `PROJECT_GRADE=F`, coverage 59 / 16 / 1 / 10, tests passed 9 /
   failed 0.
4. **Summary log** — Open the `summary` task: one VERDICT banner.
5. **Scorecard Route** — Same HTML as Part A, refreshed by this run.
6. **PR comment** — Back on GitHub: CAB table + test plan + test results (even on a red check).

### Expected red

The PipelineRun is **Failed** at `grade-gate` with  
`GATE: project grade F breaches --fail-on D`.  
That is the demo working — not a broken classpath.

---

## Part C — Optional: make something else go red

Untag the mandatory boot test: in a PR, remove `@Tag("upgrade-gate")` from
`examples/tests/BootSmokeIT.java`.  
`select-tests` should fail loudly (exit 3) — a required gate that resolved to zero tests.

---

## If something looks wrong

| Symptom | Likely cause |
|---|---|
| MiniRunner ClassNotFound / few FAIL lines | Missing `examples/demo-jars/lib/` on the classpath (fixed in current `main`) |
| Scorecard has no test banner | Looking at a pre-test scan HTML; re-run `./demo.sh` or wait for pipeline `summary` |
| Dead Route URL | Sandbox recycled — use `examples/scorecard.html` or the Route above |
| Coverage % ≠ grade rows | Expected: catalog coverage ≠ “libraries with published delta evidence” |

Re-sync committed snapshots anytime: `./demo.sh`.
