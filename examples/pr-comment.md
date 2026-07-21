## 🟡 upgrade-delta: project grade **B**
*worst pending grade across best available remediation paths* — 4 rated dependencies, 1 unrated package roots
> Without the best available remediation paths this project scores **F** — that gap is the measured value of the maintained backports.

| Dependency | Path | Grade | Lane |
|---|---|---|---|
| **acme-http-client** | `4.5.13 → 4.5.14` | 🟡 B | Targeted tests |
| ↳ acme-codec *(via acme-http-client)* | `1.11 → 1.15` | 🟡 D → B ✍️ | Targeted tests |
| **acme-json** | `2.13.4 → 2.13.4.2` | 🟡 B | Targeted tests |
| **acme-logging** | `1.12.1 → 1.12.2` | 🟢 A | Fast lane |

**⚠️ Hazards**
- `declared-not-shipped` — legacy-xml 1.0 is in the SBOM but not fingerprinted in the artifact
- `relocated-copy` — acme-codec: classes under 'com/acme/codec' also exist relocated at 'shaded/com/acme/codec' — classpath-ordering roulette; the shaded copy is invisible to version-based remediation
- `relocated-copy` — acme-codec: classes under 'com/acme/codec/internal' also exist relocated at 'shaded/com/acme/codec/internal' — classpath-ordering roulette; the shaded copy is invisible to version-based remediation

**Unrated:** com.acme.xml — upgrades here are currently tested blind.

<sub>Ratings computed by upgrade-delta; evidence JSON is sealed — verify with `upgrade-delta verify`. ✍️ = de-escalation signed off.</sub>
