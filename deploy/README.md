# deploy/ — cluster resources for the console + GitHub demo

These are the pieces the pipeline needs that are **not** created by Pipelines-as-Code
itself. Previously they only existed as live cluster objects; keeping them here means the
demo is reproducible if the cluster is ever rebuilt.

| File | Kind | Purpose |
|---|---|---|
| `00-namespace.yaml` | Namespace | The `upgrade-delta-demo` project (or create it in the console). |
| `10-reports-pvc.yaml` | PVC | Shared `upgrade-delta-reports` volume — fixture pipeline workspace **and** the viewer docroot. Must be **ReadWriteMany**. |
| `11-live-reports-pvc.yaml` | PVC | Separate `upgrade-delta-live-reports` volume for the live pom pipeline (**payments-service**, with tests). Keeps fixture + live from colliding. |
| `12-live-reports-pvc-notests.yaml` | PVC | Separate `upgrade-delta-live-reports-notests` for **payments-service-notests** (REACHABILITY_ONLY). Prevents with-tests / no-tests live runs from racing on one PVC. |
| `20-scorecard-viewer-deployment.yaml` | ConfigMap + Deployment | Read-only nginx for the with-tests live reports PVC. |
| `21-scorecard-viewer-notests-deployment.yaml` | ConfigMap + Deployment | Second nginx viewer mounting the notests PVC. |
| `22-scorecard-route.yaml` | Service + Route | Exposes the with-tests viewer (`scorecard`). |
| `23-scorecard-route-notests.yaml` | Service + Route | Exposes the notests viewer (`scorecard-notests`). |

## Apply from the console (no terminal)

Console → **＋ (Import YAML)**, top-right. Paste the contents of each file (or all of them
at once, separated by `---`) and **Create**. Do them in filename order.

For live demos, apply `11-…` + `12-…` PVCs and both viewers/routes
(see `docs/DEMO-LIVE-POM.md`). `setup-openshift.sh` applies fixture + both live
PVC/viewer stacks when those files are present.

## The one gotcha: the PVC must be ReadWriteMany

The viewer pod and each PipelineRun pod mount `upgrade-delta-reports` at the same time. On a
default block/RWO StorageClass the second pod to schedule gets a *Multi-Attach* error and
hangs. Set `storageClassName` in `10-reports-pvc.yaml` to an **RWX** class (usually
NFS-backed). Check what you have: `oc get sc`.

If you'd rather skip the viewer and just read the grade/coverage/test numbers off the
PipelineRun **Results** tab (which is the whole executive summary anyway), you can change
the PVC to `ReadWriteOnce` and not apply files 20/22.

## After applying

Get scorecard URLs from **Networking → Routes**:

| Demo | Route | Typical path |
|---|---|---|
| With tests | `scorecard` | `https://scorecard-upgrade-delta-demo.apps…/out/reports/scorecard.html` |
| No tests | `scorecard-notests` | `https://scorecard-notests-upgrade-delta-demo.apps…/out/reports/scorecard.html` |

Also useful: `/out/reports/coverage.html` and `/out/reports/` (directory listing).
