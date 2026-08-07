## 🔴 upgrade-delta: project grade **F**
*worst pending grade across best available remediation paths* — 3 rated dependencies, 3 unrated package roots

| Dependency | Path | Calls | Grade | Lane | CVEs fixed |
|---|---|---|---|---|---|
| **`com.jayway.jsonpath:json-path`** | `com.jayway.jsonpath:json-path:2.6.0 → com.jayway.jsonpath:json-path:2.8.0.rhlw-00001` | `JsonPath.read(String, String, Predicate, Object)` from `com.example.payments.PaymentService` | 🟡 C | Test each module that uses it | `CVE-2023-51074` |
| **`org.yaml:snakeyaml`** | `org.yaml:snakeyaml:1.30 → org.yaml:snakeyaml:1.33` | `TypeDescription(Class)`, `Yaml(BaseConstructor)`, `Yaml.load(InputStream, Object)`, `Constructor(TypeDescription, Collection)` from `com.example.payments.ConfigLoader` | 🔴 F | Fix your code first | — |
| **`org.springframework:spring-core`** | `org.springframework:spring-core:5.3.18 → org.springframework:spring-core:5.3.18.rhlw-00003` | `SpringVersion.getVersion(String)` from `com.example.payments.PaymentService` | 🟡 B | Test the parts you use | — |

**SBOM vs. shipped artifact (informational)**
- `shipped-not-declared` — payments-service 1.0.0 is inside the artifact but absent from the SBOM
- `declared-not-shipped` — accessors-smart 2.5.0 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — asm 9.3 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — commons-codec 1.11 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — commons-io 2.11.0 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — commons-logging 1.2 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — httpclient 4.5.12 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — httpcore 4.4.13 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — jackson-annotations 2.13.4 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — jackson-core 2.13.4 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — jackson-databind 2.13.4 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — json-path 2.6.0 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — json-smart 2.5.0 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — slf4j-api 1.7.30 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — snakeyaml 1.30 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-aop 5.3.18 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-beans 5.3.18 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-boot 2.7.18 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-boot-autoconfigure 2.7.18 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-context 5.3.31 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-core 5.3.18 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-expression 5.3.18 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-jcl 5.3.18 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-security-core 5.7.11 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-security-crypto 5.7.11 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-security-web 5.7.11 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-web 5.3.18 is in the SBOM but not fingerprinted in the artifact
- `declared-not-shipped` — spring-webmvc 5.3.18 is in the SBOM but not fingerprinted in the artifact

**Coverage gap — not rated yet:** com.fasterxml.jackson.databind, org.apache.http.client.methods, org.springframework.boot — no delta report published yet; upgrades here are tested blind.

<sub>Same data as scorecard.html (Maven GAV + named call sites + CVEs). Coverage.html answers catalog availability; this comment answers graded upgrade cost. ✍️ = de-escalation signed off.</sub>
