## 🔴 upgrade-delta: project grade **F**
*worst pending grade across best available remediation paths* — **3** libraries in this change

| Dependency | Version | Grade | Lane | CVEs fixed |
|---|---|---|---|---|
| **`json-path`** | `2.6.0` → `2.8.0.rhlw-00001` | 🟡 C | Test each module that uses it | `CVE-2023-51074` |
| **`snakeyaml`** | `1.30` → `1.33` | 🔴 F | Fix your code first | — |
| **`spring-core`** | `5.3.18` → `5.3.18.rhlw-00003` | 🟡 B | Test the parts you use | — |

### Lightwell catalog context *(not this PR's grade)*

_Demo corpus grades from community vs Lightwell .rhlw jars (upgrade_delta analyze). Not this PR's headline — catalog context only._

| Library | Pair | Grade |
|---|---|---|
| **`org.json`** | `20220320` → `20220320.0.0.rhlw-00003` | 🟡 B (+14 API) |
| **`woodstox-core`** | `6.0.3` → `6.0.3.rhlw-00001` | 🟡 B (+2 API (pom resources ≠ behavior)) |
| **`spring-core`** | `5.3.18` → `5.3.18.rhlw-00003` | 🟡 B (license/notice resources) |
| **`json-path`** | `2.8.0` → `2.8.0.rhlw-00001` | 🟢 A (quiet same-base remidiation) |
| **`json-path`** | `2.7.0` → `2.7.0.rhlw-00001` | 🟢 A (quiet same-base remidiation) |

*Every validated demo rebuild graded B — none A / C / F.*

| Rank | Library | Churn | Flag for “just a rebuild” |
|---:|---|---:|---|
| 1 | **`httpclient`** | 42.1% | 198 classes; public-suffix-list.txt moved — best demo |
| 2 | **`snakeyaml`** | 11.6% | +15 public members |
| 3 | **`org.json`** | 7.4% | +14 public members |
| 4 | **`commons-fileupload`** | 6.1% | +5 public members |
| 5 | **`logback-classic`** | 0.6% | 11 resource/default changes |
| 6 | **`commons-io`** | 0.5% | resource/pom churn |
| 7 | **`jackson-databind`** | 0.3% | +1 member (live B lane) |

Full tables: `scorecard.html` → *Lightwell catalog grades*.

### Tests — 6 of 6 classes
- ✅ **BootSmokeIT**
- ✅ **ConfigLoaderTest**
- ✅ **GatewayClientTest**
- ✅ **LedgerTest**
- ✅ **PaymentServiceTest**
- ✅ **RefundServiceTest**

### Results
- ✅ **All passed** — 9 methods — does **not** clear project **F**

---
**CAB:** A/B auto-approve with audit log; C needs human CAB; grade ≥ D fails the pipeline (`fail-on`). Full call-site / reachability detail: `scorecard.html`.
Full call-site / reachability detail: `scorecard.html`.
