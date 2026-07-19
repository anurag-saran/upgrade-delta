# Per-test JaCoCo collection → coverage.json

Three steps, run on the customer's schedule (nightly / weekly full builds — NOT every CI run):

1. `mvn test -Pper-test-coverage` — Surefire forks a fresh JVM per test class
   (`reuseForks=false`), so each fork's `.exec` contains exactly that class's coverage.
   Rename `fork-N.exec` to the test class name using Surefire's per-fork reports
   (`target/surefire-reports/*.txt` records which class ran in which fork), or use a
   `RunListener` that calls the JaCoCo agent's JMX `reset()`/`dump()` around each class
   for zero-rename operation.
2. `python3 jacoco2coverage.py target/jacoco-per-test/ \
      --sha $(git rev-parse HEAD) --build "$BUILD_ID" --age-commits 0 \
      --only-prefix com/yourcompany -o coverage.json`
   `--only-prefix` keeps the map small: the router joins on YOUR app classes.
3. Publish `coverage.json` where the router can fetch it. The embedded SHA is what the
   router's staleness check runs against — never strip it.

`jacoco2coverage.py --selftest` verifies the binary parser (round-trip, varint,
bit-packing, probe semantics) without needing a JVM.

Trade-off stated plainly: `reuseForks=false` makes the nightly run slower. That is the
price of per-test attribution, and it is paid once per night, not per selection.
