# Pipelines-as-Code — PR trigger + CAB approval, on OpenShift

This wires github.com/anurag-saran/upgrade-delta to your cluster so that **every pull
request** builds the real Spring Boot app against the Lightwell remediated repo, runs
upgrade-delta, pauses for a **CAB approval**, and reports the scorecard back onto the PR.

## One-time bootstrap (needs cluster-admin + GitHub admin on the repo)

### 1. Install Pipelines-as-Code (bundled with OpenShift Pipelines 1.9+)
```bash
oc get pods -n openshift-pipelines | grep pipelines-as-code   # already there?
# if not, enable it on the operator:
oc patch tektonconfig config --type=merge \
  -p '{"spec":{"platforms":{"openshift":{"pipelinesAsCode":{"enable":true}}}}}'
```

### 2. Create the PaC GitHub App and connect it
```bash
# opc is the OpenShift Pipelines CLI (dnf install openshift-pipelines-client, or brew)
opc pac bootstrap
# -> opens a browser, creates a GitHub App on your account, installs it on the repo,
#    and stores the app's webhook secret + private key on the cluster.
```
This is the step only you can do — it creates the GitHub webhook. I cannot create it from
outside your GitHub account.

### 3. Create the namespace, Lightwell Maven secret, and tasks
```bash
oc new-project upgrade-delta-demo

# Lightwell credentials as a settings.xml secret the pipeline mounts:
cat > /tmp/settings.xml <<'XML'
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <servers>
    <server>
      <id>lightwell-remediated</id>
      <username>YOUR_ORG_ID|your-service-account</username>
      <password>YOUR_TOKEN</password>
    </server>
  </servers>
</settings>
XML
oc create secret generic lightwell-maven-settings \
  --from-file=settings.xml=/tmp/settings.xml -n upgrade-delta-demo && rm /tmp/settings.xml

# Red Hat registry pull secret (for the RHTAS cosign image the signing tasks use):
oc create secret docker-registry redhat-registry \
  --docker-server=registry.redhat.io \
  --docker-username='NNNNNNN|name' --docker-password='TOKEN' -n upgrade-delta-demo
oc secrets link pipeline redhat-registry --for=pull -n upgrade-delta-demo

oc apply -f https://raw.githubusercontent.com/tektoncd/catalog/main/task/git-clone/0.9/git-clone.yaml -n upgrade-delta-demo
oc apply -f integration/tekton/pac/approval-gate.yaml
oc apply -f integration/tekton/pac/repository.yaml
```

### 4. The CAB approval gate — two options by Pipelines version

Check your version:
```bash
oc get csv -n openshift-operators | grep -i pipelines
```

**Pipelines < 1.16 (no manual-approval-gate feature) — use the portable manual gate:**
```bash
oc apply -f integration/tekton/pac/approval-rbac.yaml \
         -f integration/tekton/pac/approval-gate-manual.yaml
```
The pipeline (`.tekton/pull-request.yaml`) already references `cab-approval-manual`. The
run pauses until a human approves by creating a ConfigMap:
```bash
oc create configmap upgrade-delta-approved -n upgrade-delta-demo   # = APPROVE
# (do nothing to reject; the gate times out after 30 min)
```

**Pipelines >= 1.16 — use the native ApprovalTask (nicer UX):**
```bash
oc patch tektonconfig config --type=merge \
  -p '{"spec":{"pipeline":{"enable-manual-approval-gate":true}}}'
oc get crd approvaltasks.openshift-pipelines.org      # confirm it appears
oc apply -f integration/tekton/pac/approval-gate.yaml
```
Then swap the `cab-approval` task in `.tekton/pull-request.yaml` from `cab-approval-manual`
to the ApprovalTask block (commented in `approval-gate.yaml`). Approve with:
`opc approvaltask approve upgrade-delta-cab -n upgrade-delta-demo`.

## The flow, per PR

1. You open a PR against `main`.
2. PaC sees `.tekton/pull-request.yaml`, starts the PipelineRun, posts a "running" check on the PR.
3. `clone` → `build-and-analyze` (Maven build against Lightwell + upgrade-delta scan) → the run **pauses** at `cab-approval`.
4. A reviewer reads the grade/coverage/tests (shown in the ApprovalTask description and
   the PipelineRun), then approves the paused run:
   ```bash
   # portable manual gate (Pipelines <1.16):
   oc create configmap upgrade-delta-approved -n upgrade-delta-demo    # = approve
   # native ApprovalTask (Pipelines >=1.16):
   opc approvaltask approve upgrade-delta-cab -n upgrade-delta-demo
   ```
   (Approvers can also approve from the OpenShift console's Pipelines view.)
5. On approval the run completes; PaC reports the scorecard status back onto the PR.
6. Branch protection on `main` (GitHub side) can require this check to pass before merge — that's your merge-gate.

## Branch protection = the merge approval

In the repo settings → Branches → add a rule for `main`: require the
`upgrade-delta-pr` check to pass before merging. Combined with the in-pipeline CAB
approval, you get two gates: a human approves the upgrade in the pipeline, and GitHub
blocks the merge until the whole run (including that approval) is green.

## Honest status

- The PipelineRun, Repository CR, and ApprovalTask are written and YAML-valid, but have
  **not run on a live cluster** — budget one shakedown. The most likely items: the
  `enable-manual-approval-gate` operator toggle (step 4 — without it the ApprovalTask CRD
  does not exist and the pipeline errors at cab-approval), image pull policy, and the
  git-clone task version.
- The Maven build needs the Lightwell secret to resolve dependencies; without valid
  credentials the `build-and-analyze` step fails at dependency resolution.
- `opc pac bootstrap` and the GitHub App install are yours to run — they require your
  GitHub account, and no external tool can create that webhook for you.
