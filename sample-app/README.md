# payments-service — real Spring Boot app on Red Hat Lightwell

No mock libraries. Every dependency is a real artifact pulled from the Lightwell
**remediated** repository at the exact serviced version (see `pom.xml`):
jackson-databind, spring-web/webmvc/core, spring-boot, spring-security, commons-io,
httpclient, json-smart — all `…redhat-NNNNN`.

## Build (needs Lightwell credentials)

```bash
cp settings.xml.template settings.xml     # then edit in your orgID|account + token
mvn -s settings.xml clean package
```

This resolves the remediated jars, compiles, runs the tests Surefire is pointed at
(`target/upgrade-delta/surefire-includes.txt` when the router has written one; the full
suite otherwise), produces `target/payments-service.jar`, `target/bom.json` (CycloneDX
SBOM), and JaCoCo coverage under `target/site/jacoco/`.

## What upgrade-delta does with it

```bash
# from the repo root, against the built jar + SBOM:
python3 ../upgrade_delta.py coverage --sbom target/bom.json \
    --catalog ../catalogs/lightwell-remediated-java-sbom.json \
    --html ../out/reports/coverage.html
python3 ../upgrade_delta.py scan target/payments-service.jar \
    --sbom target/bom.json --evidence ../out/evidence \
    --routing-payload ../out/routing.json --fail-on D
```

The jackson-databind row is the hero: your app calls `ObjectMapper.readValue` /
`writeValueAsString` directly, and the Lightwell rebuild `2.13.4 → 2.13.4.redhat-00001`
is a drop-in that touches none of it — measured, grade B, 0.3% churn.
