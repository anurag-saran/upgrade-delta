# Integrate Lightwell with Sonatype Nexus

Configure Nexus Repository Manager as a **Maven2 (proxy)** repository that fronts the
Lightwell Network feed, so builds resolve `.rhlw-*` artifacts through your centralized
Nexus instance.

Source procedure: [Configure Nexus to use the Lightwell Network repository](https://docs.redhat.com/en/documentation/lightwell_network/current/configure-configure_nexus_to_use_rhln_repository).
Notably shorter than the Artifactory path. This guide adds the **public demo** URL mode
and the bridge to upgrade-delta. Index: [`README.md`](README.md).

---

## Before you begin

- Administrator access to Sonatype Nexus Repository Manager.
- For **production**: an active Lightwell Network membership and a
  [service account](https://docs.redhat.com/en/documentation/lightwell_network/current/get_started-create_a_red_hat_lightwell_network_service_account)
  (`XXXXXXX|service-account-name` + token).
- Chosen [repository tier](https://docs.redhat.com/en/documentation/lightwell_network/current/get_started-choose_the_right_repository)
  (Validated / Remediated / Predisclosure).

---

## Procedure

1. **Create a new repository** → type **Maven2 (proxy)**.
2. Set:

   | Field | Production | Public demo |
   |---|---|---|
   | Remote Storage | `https://packages.redhat.com/lightwell/java/remediated/` | `https://packages.redhat.com/lightwell/public-lightwell-demo/java/remediated/` |
   | Layout Policy | **Strict** | **Strict** |

   The official doc calls out **Strict** specifically: *"to ensure proper resolution of
   `.rhlw` suffixes."* Do not leave this permissive — a loose layout policy can
   mis-resolve the vendor suffix.

   Swap `remediated` for `validated` or `predisclosure` when needed. For multiple tiers,
   create separate proxies and combine them in a Nexus **group**, typically ordered
   Predisclosure → Remediated → Validated.

3. **Authentication** (production):

   | Field | Value |
   |---|---|
   | Username | `XXXXXXX\|service-account-name` |
   | Password | service-account token |

   For the **public demo** path, leave authentication empty if Nexus allows it. If the UI
   requires non-empty fields, use a placeholder and smoke-test a fetch — the demo feed does
   not validate credentials for anonymous GETs.

---

## Verify

1. Open the new proxy repository in Nexus.
2. Request a known artifact (browse or `curl` / Maven resolve) — e.g. navigate toward
   `org/springframework/spring-core/` and confirm a `.rhlw-` jar is retrievable.
3. From a test Maven build that uses the Nexus group/proxy as its remote, resolve the same
   GAV you would use in an Artifactory demo (e.g.
   `com.jayway.jsonpath:json-path:2.8.0.rhlw-00001` when that version exists in the tier).

---

## Point Maven at Nexus

Configure clients to resolve through **your Nexus URL** (proxy or group), not
packages.redhat.com directly. See Red Hat’s
[Configure your Java build tool](https://docs.redhat.com/en/documentation/lightwell_network/current/configure-configure_java_build_tool)
and Nexus’s Maven client documentation for `settings.xml` / mirror patterns.

OpenShift demo Secret `lightwell-maven-settings` (direct packages.redhat.com auth) is
documented in [`CREDENTIALS.md`](../../CREDENTIALS.md). Customers who already run Nexus
should put Lightwell credentials on the proxy and keep CI pointed at Nexus only.

---

## Bridge to upgrade-delta

Nexus makes the remediated jar *available*. It does not grade impact on *your* bytecode or
select the owed tests. After the proxy works, score the upgrade with upgrade-delta —
[`DEMO-LIVE-POM.md`](../DEMO-LIVE-POM.md). Same story as Artifactory: availability vs.
test-scope evidence.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Odd / missing `.rhlw-` versions | **Layout Policy** must be **Strict** |
| 401 / 403 from packages.redhat.com | Production username format (`orgId\|name`) and token on the proxy |
| Artifact not cached | Hit the proxy once from Maven; confirm Remote Storage URL ends with the correct tier |
| CI still hits packages.redhat.com | Client still lists Lightwell URL instead of the Nexus proxy/group |
| Demo auth required by UI | Placeholder credentials + smoke-test before presenting |
