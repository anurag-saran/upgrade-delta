# Committed examples

Real-library demo corpus (keep in sync via `./demo.sh`):

- `demo-jars/payments-service-1.0.0.jar` + `payments-service.sbom.json` — sample app
- `demo-jars/payments-tests-1.0.0.jar` — MiniRunner + `com.example.payments` tests
- `demo-jars/lib/*.jar` — runtime classpath so MiniRunner pass/fail is about the upgrade
- `evidence/{json-path,snakeyaml,spring-core}.json` — analyze output for the three graded rows
- `tests/` — test sources + coverage map the router uses
- `osv/` — offline OSV advisories used by the scan

**Verified snapshots** (same numbers the cluster demo prints):

| Artifact | Role |
|---|---|
| `coverage.json` / `coverage.html` | Lightwell catalog meter — **16/27** drop-in (59%) |
| `scorecard.json` / `scorecard.html` | Grades **F** · spring-core **B** / json-path **C** / snakeyaml **F** + test outcomes |
| `test-results.json` | **9** methods passed / **0** failed + per-library attribution |
| `pr-comment.md` | CAB markdown: grades table + test plan + test results |

Browsable reports are also written to `out/reports/` when you run `./demo.sh`.
