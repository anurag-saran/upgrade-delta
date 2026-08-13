## 🔴 upgrade-delta: project grade **F**
*worst pending grade across best available remediation paths* — **3** libraries in this change

| Dependency | Version | Grade | Lane | CVEs fixed |
|---|---|---|---|---|
| **`json-path`** | `2.6.0` → `2.8.0.rhlw-00001` | 🟡 C | Test each module that uses it | `CVE-2023-51074` |
| **`snakeyaml`** | `1.30` → `1.33` | 🔴 F | Fix your code first | — |
| **`spring-core`** | `5.3.18` → `5.3.18.rhlw-00003` | 🟡 B | Test the parts you use | — |

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
**CAB:** approve by merging. Grade ≥ D fails the pipeline. Full call-site / reachability detail: `scorecard.html`.
