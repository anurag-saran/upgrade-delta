# Committed examples

Real-library demo corpus:

- `demo-jars/payments-service-1.0.0.jar` + `payments-service.sbom.json` — rebuilt sample-app
- `demo-jars/payments-tests-1.0.0.jar` — MiniRunner + `com.example.payments` tests
- `evidence/{json-path,snakeyaml,spring-core}.json` — analyze output for the three graded rows
- `tests/` — test sources + coverage map the router uses

Browsable reports are produced by `./demo.sh` into `out/reports/` (coverage.html, scorecard.html).
