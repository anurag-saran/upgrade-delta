# Jackson evidence — the real Lightwell-serviced hero

Lightwell rebuilds jackson-databind. Note the suffix mismatch you'll hit:
the **catalog SBOM** labels it `2.13.4.redhat-00001`, but the **repo path** serves it as
`2.13.4.rhlw-00001`. Use whichever returns HTTP 200 — test with:

    curl -sI -u "$RHLN_USER:$RHLN_TOKEN" \
      'https://packages.redhat.com/lightwell/java/remediated/com/fasterxml/jackson/core/jackson-databind/2.13.4.rhlw-00001/jackson-databind-2.13.4.rhlw-00001.jar' | head -1

Then generate the evidence (sandbox can't — no route to Maven Central / packages.redhat.com):

    ./lightwell-report.sh com.fasterxml.jackson.core jackson-databind 2.13.4 2.13.4.rhlw-00001

Copy out/evidence/jackson-databind-2.13.4-to-2.13.4.<suffix>.json into this directory.
The demo's "what Lightwell actually gives you" beat globs for either suffix and shows the
real grade; until then it prints the command and defers to the coverage meter (which
already proves Jackson is serviced for this app's exact version).
