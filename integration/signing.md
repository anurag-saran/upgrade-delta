# Evidence sealing

Local dev / air-gapped: `upgrade-delta seal <files> --key keys/evidence-signing.pem`
(Ed25519 detached signatures over canonical JSON: sorted keys, tight separators —
reformatting doesn't break verification, value edits do). Verify: `upgrade-delta verify
<files> --pub keys/evidence-signing.pem.pub` — exit 5 on any mismatch.

Production path: Sigstore keyless in CI (`cosign sign-blob` with the workflow's OIDC
identity) so the signature binds evidence to *which pipeline produced it*, with the key
ceremony outsourced to Fulcio/Rekor. The local Ed25519 mode stays for air-gapped shops —
the same customers who required the no-egress design. Sign at two points: the publisher
seals each delta report at publish time; the consumer's CI seals scorecard + selection
report + deploy gate after the gate passes. What the CAB receives is then not "a JSON
file" but a verifiable chain with two identities on it.
