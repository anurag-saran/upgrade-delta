# Install — OpenShift console + GitHub only

This sets up the demo using **only the OpenShift web console and github.com** — no
terminal, no `oc`, no `opc`. Once it's wired, opening a pull request runs the pipeline and
the console shows the result.

The **base demo** (clone → score → route) runs entirely on fixtures committed to this repo,
so it needs **no Lightwell credentials, no registry pull secret, and no JDK on your side**.
Credentials are only for the optional add-ons at the end.

> **Already running a previous version on this cluster?** Tear it down first so stale tasks,
> PipelineRuns, and the old reports PVC don't collide with the new set:
> ```
> ./cleanup-openshift.sh          # keeps the namespace + your credential secrets
> ```
> Then either follow the console steps below, or run the scripted setup (see the end).

---

## What you need first

- **An OpenShift 4.x cluster** where you are cluster-admin (or can install an Operator and
  create projects).
- **Admin on a GitHub copy of this repo** — fork it or push it to your own
  `github.com/<you>/upgrade-delta`. You'll point the pipeline at your copy.
- **(Only if you want the rendered HTML scorecard viewer)** a StorageClass that supports
  **ReadWriteMany** (usually NFS-backed). Everything else works on any default StorageClass.

---

## 1. Install the OpenShift Pipelines Operator  *(console)*

Console → **Operators → OperatorHub** → search **"Red Hat OpenShift Pipelines"** →
**Install** (defaults are fine; it installs cluster-wide). Wait until it shows
*Succeeded*. This bundles Tekton **and** Pipelines-as-Code (PaC) — the PR trigger.

## 2. Create the project  *(console)*

Switch to the **Developer** perspective → **Project** dropdown → **Create Project** → name
it exactly **`upgrade-delta-demo`**. (Or Import `deploy/00-namespace.yaml` in step 3.)

## 3. Apply the demo's cluster resources  *(console — Import YAML)*

Top-right **＋ (Import YAML)**. Paste each file from `deploy/` and **Create**, in order:

1. `deploy/10-reports-pvc.yaml` — the shared reports volume (the pipeline's workspace).
   **Before creating**, if you're doing the viewer, set `storageClassName` to your RWX
   class (see the comments in the file; list classes under **Storage → StorageClasses**).
2. `deploy/20-scorecard-viewer-deployment.yaml` — the nginx viewer *(optional; skip if you
   only want the numbers).*
3. `deploy/22-scorecard-route.yaml` — the viewer's Route *(optional).*

> Prefer the terminal-free minimum? Apply only `10-reports-pvc.yaml` (you can leave it
> ReadWriteOnce) and read the grade/coverage/test results off the PipelineRun **Results**
> tab in step 6 of the demo. The viewer just makes the *pretty* scorecard browsable.

## 4. Connect GitHub with a Pipelines-as-Code GitHub App  *(github.com + console)*

This is the webhook that makes a PR start the pipeline. It's created on GitHub and stored
on the cluster — both web UIs, no laptop tools.

**4a. Find your PaC controller URL (console).**
**Networking → Routes**, project **`openshift-pipelines`** → copy the URL of the route
named **`pipelines-as-code-controller`** (looks like
`https://pipelines-as-code-controller-openshift-pipelines.apps.<cluster>`). This is your
webhook target.

**4b. Create the GitHub App (github.com).**
GitHub → your profile **Settings → Developer settings → GitHub Apps → New GitHub App**:

- **Webhook URL:** the controller URL from 4a.
- **Webhook secret:** any random string — keep it, you'll paste it in 4c.
- **Repository permissions:** *Contents* Read-only · *Metadata* Read-only ·
  *Checks* Read & write · *Pull requests* Read & write · *Issues* Read & write.
- **Subscribe to events:** *Pull request*, *Push*, *Issue comment*.
- Create, then **Generate a private key** (downloads a `.pem`) and note the **App ID**.

**4c. Install the App on your repo (github.com).**
On the App's page → **Install App** → choose **`<you>/upgrade-delta`** (only that repo).

**4d. Store the App credentials on the cluster (console — Import YAML).**
Console, project **`openshift-pipelines`**, **＋ Import YAML**, paste and edit:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: pipelines-as-code-secret
  namespace: openshift-pipelines
type: Opaque
stringData:
  github-application-id: "1234567"          # your App ID from 4b
  webhook.secret: "the-random-string"        # the webhook secret from 4b
  github-private-key: |                       # paste the WHOLE .pem, indented
    -----BEGIN RSA PRIVATE KEY-----
    ...
    -----END RSA PRIVATE KEY-----
```

> Faster if you happen to have the CLI: `opc pac bootstrap` does 4a–4d in one browser flow.
> Not required — the steps above are the fully-web equivalent.

## 5. Tell PaC about your repo  *(console — Import YAML)*

Edit `integration/tekton/pac/repository.yaml` so `spec.url` is **your** repo URL, then
Import it (project **`upgrade-delta-demo`**). PaC now matches PRs on that repo and runs the
`PipelineRun` in `.tekton/pull-request.yaml`.

The pipeline and tasks themselves don't need to be pre-applied — `.tekton/pull-request.yaml`
carries annotations that make PaC fetch `pipeline-demo.yaml` and the two task files from
your repo at run time.

## 6. (Recommended) Make the pipeline your merge gate  *(github.com)*

GitHub → repo **Settings → Branches → Add branch ruleset/protection** for `main` →
require status checks to pass → select the **`upgrade-delta-pr`** check. Now a PR can't
merge until the scan is green — the audit gate lives in the merge button.

---

✅ **Setup done.** Go run the demo: [`docs/DEMO-SCRIPT.md`](DEMO-SCRIPT.md).

---

## Scripted setup & teardown (the CLI alternative)

If you have `oc` and prefer scripts over clicking:

```bash
./setup-openshift.sh      # namespace, secrets, tasks, deploy/ (PVC + viewer), git-clone;
                          # then prints the two manual steps (connect GitHub, open a PR)
./cleanup-openshift.sh    # remove the app resources; keep namespace + credential secrets
```

`cleanup-openshift.sh` is what you run before re-installing over a previous version. Modes:

| Command | Effect |
|---|---|
| `./cleanup-openshift.sh` | Remove pipeline, tasks, Repository CR, viewer, approval gate, all PipelineRuns, and the reports PVC. Keeps the namespace and credential secrets. |
| `./cleanup-openshift.sh --keep-pvc` | Same, but keep the reports PVC and its data. |
| `./cleanup-openshift.sh --purge` | Also delete the Lightwell/registry secrets (you'll re-enter tokens). |
| `./cleanup-openshift.sh --namespace` | Delete the whole `upgrade-delta-demo` namespace (everything). |
| `./cleanup-openshift.sh --yes` | Skip the confirmation prompt (combine with the above). |

It never touches the OpenShift Pipelines operator or the PaC GitHub App secret in
`openshift-pipelines`, so your GitHub connection survives a cleanup.

---

## Optional add-ons (credentialed / advanced)

You do **not** need these for the core demo. Add them only if you're showing the
production-shaped path.

### A. Real Maven build against Red Hat Lightwell
Builds `sample-app/` against genuine `…redhat-NNNNN` remediated jars instead of using the
committed fixtures. Needs a `console.redhat.com` service account. Create a
`lightwell-maven-settings` Secret (a Maven `settings.xml`) in `upgrade-delta-demo`.
Reference: `CREDENTIALS.md`. The scriptable helper `setup-openshift.sh` also wires this.

### B. Sigstore / RHTAS evidence signing
Keyless-signs the approved scorecard against Sigstore (Fulcio + Rekor). Needs a
`registry.redhat.io` pull secret for the cosign image and an OIDC token in the pipeline.
Runbook: `integration/tekton/rhtas/README.md`.

### C. In-pipeline CAB approval (pause the run for a human)
The base pipeline doesn't pause. To add a Change-Advisory-Board pause you can approve from
the **console** (no terminal), enable the native gate on the operator and use the
`ApprovalTask` — see `integration/tekton/pac/README.md`. Approvers then click Approve in the
console's Pipelines view. (Branch protection in step 6 already gives you a merge gate
without this.)
