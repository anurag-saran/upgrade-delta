# Committed examples

Generated from the sample corpus so the repo is browsable without running anything:

- `example-delta-report.html` — the published report card for the A-grade backport
- `scorecard-signed.json` (+ `.sig`, and the public key) — a sealed project scorecard;
  verify it yourself: `python3 ../upgrade_delta.py verify scorecard-signed.json --pub evidence-signing.pem.pub`
- `routing.json` — the affected-code payload the scanner hands to the test router
- `selection-report.json` / `deploy-gate.json` — the router's outputs for that payload
- `pr-comment.md` — the same scorecard rendered as a Renovate-PR comment


Everything else under `out/` is reproducible: run `./demo.sh`.
