# Evidence signing with cosign + Sigstore (Red Hat RHTAS images)

The pipeline keyless-signs upgrade-delta's evidence (scorecard + routing payload) with
**cosign** against **public Sigstore** (public Fulcio + Rekor). This replaces the local
`upgrade_delta.py seal`/`verify` (Ed25519) with keyless signatures — no private keys to
custody — plus a public Rekor transparency-log entry per signature.

**Images:** the signing tasks use `registry.redhat.io/rhtas/cosign-rhel9:1.3.5` (Red Hat's
supported cosign build), so the namespace needs a `registry.redhat.io` pull secret — see
`CREDENTIALS.md` (#2) and the `redhat-registry` secret in `pac/README.md`. Signing targets
public Sigstore (Fulcio + Rekor) by default; point the env vars at a self-hosted RHTAS
stack (`securesign.yaml`) if you deploy one.

## Files

- `task-sign-evidence.yaml` — `cosign sign-blob` (keyless) → `.sig`, `.crt`, `.bundle` + Rekor entry.
- `task-verify-evidence.yaml` — `cosign verify-blob` → confirms signature + Rekor inclusion.
- `securesign.yaml` — **optional.** Only if you want a *self-hosted* Sigstore stack (Red Hat
  Trusted Artifact Signer). Not required for the public-Sigstore path above; ignore it
  unless you're deploying RHTAS on-cluster.

The cosign images are **distroless (no shell)**, so the tasks call the cosign entrypoint
directly via `args` (one step per file) rather than a bash `script:`.

## The one wiring detail: the OIDC token

Keyless signing needs an OIDC identity token. cosign reads it from the `SIGSTORE_ID_TOKEN`
env var (or does an interactive browser flow, which won't work in CI). In a Tekton/PaC
pipeline you provide it one of two ways:

1. **Projected ServiceAccount token** (in-cluster identity): mount a projected token with
   audience `sigstore` and export it as `SIGSTORE_ID_TOKEN` in the sign step. The signer
   identity becomes the pipeline ServiceAccount; set `cert-identity-regexp` on the verify
   task to match it.
2. **GitHub Actions OIDC** (if you also run this in Actions): the `id-token: write`
   permission gives cosign a token automatically.

Without a token, the sign step fails at "getting identity token" — that's the expected
failure, and the fix is wiring one of the above.

## The flow, end to end

```
build-and-analyze → cab-approval (opc approvaltask approve)
                  → sign-evidence   (cosign sign-blob, keyless → Fulcio cert + Rekor entry)
                  → verify-evidence (cosign verify-blob → confirms signature + Rekor inclusion)
```
Signing runs **after** the CAB approves, so the signature attests *this exact, approved
scorecard*.

## Verify off-cluster (what a change board does)

```bash
cosign verify-blob --bundle scorecard.json.bundle \
  --certificate-identity-regexp '<your-CI-identity>' \
  --certificate-oidc-issuer-regexp 'https://oauth2.sigstore.dev/auth' \
  scorecard.json
```
A pass means: signed by the approved identity, logged in Rekor, unedited since. That is
the audit artifact.

## Honest status

- The sign/verify Tasks are YAML-valid and use the correct distroless-cosign invocation
  pattern, but have **not run on a live cluster**. The one thing that needs wiring for a
  green run is the OIDC token (above).
- Public Sigstore means signatures + Rekor entries are on the **public** Fulcio/Rekor —
  fine for a demo and for public artifacts. For private/air-gapped evidence, either use
  the local `upgrade_delta.py seal`/`verify` (fully offline, no OIDC) or deploy the
  self-hosted RHTAS stack via `securesign.yaml`.
- Local `seal`/`verify` stays in the repo as the zero-dependency path. Same JSON artifact,
  different trust backend — they are not mutually exclusive.
