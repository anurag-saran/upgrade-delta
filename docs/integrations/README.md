# Integrations — Lightwell through your existing tools

Proxy the Lightwell Network through the artifact repository managers you already run,
and compose upgrade-delta with SonarQube. These guides are **customer wiring docs**,
not a substitute for Red Hat’s product documentation.

| Guide | When you need it |
|---|---|
| [`ARTIFACTORY.md`](ARTIFACTORY.md) | JFrog Artifactory is your Maven remote |
| [`NEXUS.md`](NEXUS.md) | Sonatype Nexus is your Maven proxy |
| [`SONARQUBE.md`](SONARQUBE.md) | You already gate merges with Sonar and want the honest hand-off to upgrade-delta |

## What this is / is not

**Is:** one remote (or proxy) repository so Maven/Gradle resolve `.rhlw-*` coordinates
the same way they resolve Central — credentials live on the repo manager once, not on
every CI job.

**Is not:** upgrade-delta itself. Artifactory/Nexus make a remediated build *available*.
upgrade-delta grades how much the library *actually changed*, intersects that with *your*
bytecode, and hands test obligations to your deploy gate. SonarQube still owns app-code
quality; it does not grade a dependency bump.

## Official sources

Procedures below follow Red Hat Lightwell Network configure docs (Java):

- [Configure Artifactory (Java)](https://docs.redhat.com/en/documentation/lightwell_network/current/configure-configure_artifactory_to_use_rhln_repository)
- [Configure Nexus](https://docs.redhat.com/en/documentation/lightwell_network/current/configure-configure_nexus_to_use_rhln_repository)
- [Choose the right repository tier](https://docs.redhat.com/en/documentation/lightwell_network/current/get_started-choose_the_right_repository)
- [Configure your Java build tool](https://docs.redhat.com/en/documentation/lightwell_network/current/configure-configure_java_build_tool)

OpenShift demo secrets that hang `settings.xml` directly on packages.redhat.com remain in
[`CREDENTIALS.md`](../../CREDENTIALS.md). Prefer the Artifactory/Nexus pattern for
customers who already centralize remotes.

## URL modes (use in every procedure)

| Mode | Base URL | Auth |
|---|---|---|
| **Production** | `https://packages.redhat.com/lightwell/java/remediated/` (also `validated/`, `predisclosure/`) | Service account `XXXXXXX\|service-account-name` + token |
| **Public demo** | `https://packages.redhat.com/lightwell/public-lightwell-demo/java/remediated/` | None — leave blank, or a placeholder if the UI rejects empty fields. **Smoke-test before a live demo.** |

Most production environments layer tiers in a virtual/group repository, ordered
**Predisclosure → Remediated → Validated** so the most current patched artifact wins.
Lightwell supplies the tiers; you own the combined view. See
[Choose the right repository](https://docs.redhat.com/en/documentation/lightwell_network/current/get_started-choose_the_right_repository).

## Demo narrative (four beats)

Use this when you only have console time with Artifactory and/or Nexus already up:

1. **Show the repo config screen** in Artifactory, then Nexus (or vice versa) — one remote
   repository, minutes of work, additive to existing builds.
2. **Resolve one real coordinate** through each manager — e.g.
   `com.jayway.jsonpath:json-path:2.8.0.rhlw-00001` — same catalog, two repo managers.
3. **Bridge to upgrade-delta** — open a payments-service (or fixture) scorecard: the jars
   came through the same path; the grade answers whether adopting them is safe to
   *test-scope*. See [`DEMO-LIVE-POM.md`](../DEMO-LIVE-POM.md).
4. **Closer (optional)** — Sonar quality gate for app health + upgrade-delta grade-gate /
   `deploy-gate.json` for upgrade obligations. Both must pass; neither replaces the other
   ([`SONARQUBE.md`](SONARQUBE.md)).
