# Using real libraries — three tiers of "real"

The fixture demo uses mock `acme-*` jars so the app-intersection story has an app whose
versions we control. To make it real with actual Lightwell artifacts, pick the tier that
matches how much realness you need. Each tier is strictly more real (and more setup) than
the last.

---

## Tier 1 — real coverage meter on your real SBOM  *(no credentials, do this first)*

The **coverage meter** matches your app's CycloneDX SBOM against the committed Lightwell
remediated catalog and buckets every dependency: exact-version drop-in / serviced at
another version / uncovered. This is real and needs nothing but your SBOM — the catalog is
in the repo.

`samples/customer-sbom.json` already contains your four artifacts. Run it:

```bash
python3 upgrade_delta.py coverage \
  --sbom samples/customer-sbom.json \
  --catalog catalogs/lightwell-remediated-java-sbom.json \
  --json out/coverage.json --html out/reports/coverage.html
```

Result (verified against your artifacts):

| Your artifact | Bucket | Lightwell offering |
|---|---|---|
| `commons-io:commons-io:2.13.0` | serviced at another version | `2.11.0.redhat-00001` |
| `org.springframework:spring-core:6.1.6` | serviced at another version | `5.3.18.redhat-00005` |
| `org.springframework:spring-web:6.1.6` | serviced at another version | `5.3.18.redhat-00005` |
| `ch.qos.logback:logback-classic:1.4.14` | **not covered** | (Validated, not in the Remediated catalog) |

To make the **console pipeline** show this instead of the sample, edit
`integration/tekton/pipeline-demo.yaml` → `coverage` task → change the `app-sbom` param to
`samples/customer-sbom.json`. Better still, generate a real SBOM from your actual app with
the CycloneDX Maven plugin (`mvn org.cyclonedx:cyclonedx-maven-plugin:makeAggregateBom` →
`target/bom.json`) and point `app-sbom` at that — then the meter reflects your whole real
dependency graph, not just these four.

> **Read the result honestly.** All three Spring/commons rows are *serviced at another
> version*, and it's an **older** version — `spring 6.1.6 → 5.3.18` is a major backport
> (Spring 6 → 5 means the `jakarta.*` ↔ `javax.*` namespace break), and `commons-io
> 2.13.0 → 2.11.0` is a minor step back. So these are **not drop-ins** for a Spring-6 app;
> the meter is correctly telling you the remediated option is a different stream that needs
> a real upgrade decision. If your app is actually on Spring **5** (javax) already, then
> `5.3.18.redhat` *is* a clean drop-in and would bucket as covered — swap the SBOM versions
> to your true baseline and re-run.

## Tier 2 — real grades + scan on real jars  *(needs a Lightwell token)*

The **scan** (per-dependency A–F grades, reachability, the scorecard) needs the actual old
and new jars, because the grade comes from diffing their bytecode and intersecting it with
your app's bytecode. `sample-app/` is already wired for this: it's a real Spring Boot
service pinned to real `…redhat-NNNNN` versions, with CycloneDX + JaCoCo + Surefire
`includesFile` configured in its `pom.xml`.

1. Put a real console.redhat.com service-account token back in the cluster secret
   (`lightwell-maven-settings`) — see `CREDENTIALS.md` / `setup-openshift.sh`.
2. Build `sample-app` against Lightwell (`mvn -s settings.xml clean package`) or pull the
   raw jars with `./fetch-lightwell-app-jars.sh`. This produces the real app jar, a real
   `target/bom.json`, and the resolved dependency jars.
3. Run `upgrade_delta.py analyze old.jar new.jar --app target/payments-service.jar …` for
   each pair you care about to produce evidence JSON, then `scan target/payments-service.jar
   --evidence <dir> --sbom target/bom.json --lib-jars <resolved-jars>` for the graded
   scorecard.

To do this on the cluster you need a pipeline variant that mounts the Lightwell secret and
runs the Maven build before the scan (the current `pipeline-demo.yaml` deliberately uses
committed fixtures and no build). That variant is the natural next build-out.

## Tier 3 — real per-test routing  *("run these N of your M tests, named")*

Everything above still routes tests against a coverage map. To route against **your real
tests**, generate a real per-test coverage map with JaCoCo and feed it to the router.

The map is captured from a **prior instrumented test run** — one `.exec` per test class —
then converted:

```bash
# one .exec per test class via the profile in integration/jacoco/pom-profile.xml, then:
python3 integration/jacoco/jacoco2coverage.py target/jacoco-per-test/ \
  --sha $(git rev-parse --short HEAD) --build "$BUILD_ID" --age-commits 0 \
  --only-prefix com/yourorg/app -o coverage.json
```

Point the route task's `coverage-map` param at that `coverage.json`. The router then
selects your real tests, printing the reason for each — and enforces the fail-closed rules
(unknown test runs, stale map → full suite, missing mandatory gate → hard fail).

---

### Why the split (and the answer to "are you capturing this from before the build?")

- **Library delta** and **app reachability** are computed **fresh at scan time**, from the
  jars in this build.
- The **test → code map** is the one piece captured **before** — from a previous JaCoCo
  run — and it carries provenance (git SHA, build id, age in commits). The router refuses to
  trust a stale map: past the drift threshold it runs the full suite, and a "widening rule"
  force-runs tests covering any app class changed since the map's SHA. So old coverage can
  only ever cause **more** tests to run, never fewer than the evidence supports.
