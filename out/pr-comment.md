## 🟡 upgrade-delta: project grade **B**
*worst pending grade across best available remediation paths* — 3 rated dependencies, 4 unrated package roots
> Without the best available remediation paths this project scores **F** — that gap is the measured value of the maintained backports.

| Dependency | Path | Grade | Lane |
|---|---|---|---|
| **acme-http-client** | `4.5.13 → 4.5.14` | 🟡 B | Targeted tests |
| **acme-json** | `2.13.4 → 2.13.4.2` | 🟡 B | Targeted tests |
| **acme-logging** | `1.12.1 → 1.12.2` | 🟢 A | Fast lane |

**Unrated:** com.acme.xml, org.apache.logging.log4j, org.apache.logging.log4j.core.config, org.apache.logging.log4j.core.lookup — upgrades here are currently tested blind.

<sub>Ratings computed by upgrade-delta; evidence JSON is sealed — verify with `upgrade-delta verify`. ✍️ = de-escalation signed off.</sub>
