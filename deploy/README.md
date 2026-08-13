# deploy/ — cluster resources for the console + GitHub demo

These are the pieces the pipeline needs that are **not** created by Pipelines-as-Code
itself. Previously they only existed as live cluster objects; keeping them here means the
demo is reproducible if the cluster is ever rebuilt.

| File | Kind | Purpose |
|---|---|---|
| `00-namespace.yaml` | Namespace | The `upgrade-delta-demo` project (or create it in the console). |
| `10-reports-pvc.yaml` | PVC | Shared `upgrade-delta-reports` volume — fixture pipeline workspace **and** the viewer docroot. Must be **ReadWriteMany**. |
| `11-live-reports-pvc.yaml` | PVC | Separate `upgrade-delta-live-reports` volume for the live pom pipeline (payments-service). Keeps fixture + live from colliding. |
| `20-scorecard-viewer-deployment.yaml` | ConfigMap + Deployment | Read-only nginx that serves the rendered HTML reports the pipeline writes. |
| `22-scorecard-route.yaml` | Service + Route | Exposes the viewer so you can open the scorecard in a browser from the console. |

## Apply from the console (no terminal)

Console → **＋ (Import YAML)**, top-right. Paste the contents of each file (or all of them
at once, separated by `---`) and **Create**. Do them in filename order.

For live demos against payments-service, also apply `11-live-reports-pvc.yaml`
(see `docs/DEMO-LIVE-POM.md`). `setup-openshift.sh` applies the fixture PVC/viewer;
apply the live PVC explicitly when enabling that path.

## The one gotcha: the PVC must be ReadWriteMany

The viewer pod and each PipelineRun pod mount `upgrade-delta-reports` at the same time. On a
default block/RWO StorageClass the second pod to schedule gets a *Multi-Attach* error and
hangs. Set `storageClassName` in `10-reports-pvc.yaml` to an **RWX** class (usually
NFS-backed). Check what you have: `oc get sc`.

If you'd rather skip the viewer and just read the grade/coverage/test numbers off the
PipelineRun **Results** tab (which is the whole executive summary anyway), you can change
the PVC to `ReadWriteOnce` and not apply files 20/22.

## After applying

Get the scorecard URL from **Networking → Routes → `scorecard`**. Replace
`scorecard.apps.EXAMPLE.com` in docs/templates with your real Route host. After a run, open:

- `https://<route>/out/reports/scorecard.html` — the project scorecard
- `https://<route>/out/reports/coverage.html` — the coverage meter
- `https://<route>/out/reports/` — directory listing of everything the run produced
