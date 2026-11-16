# G5 replay credential rotation — November 16, 2026

**Result: PASS.** The supported stopped-replay rotation replaced the G0 issuer
CA plus the SAM3 serving and replay-client leaf credentials. The existing
baseline model image remained `sha256:f9bcc273a164f741426079ccf4c9d2269c9ec5e9530845029e593bf466a3aa2e`.
The replacement serving pod returned Ready, matched the accepted deployment
identity, and served `/ready` with HTTP 200.

The rotation check confirmed the retired client certificate was rejected and
that a connection without a client certificate was rejected. The new serving
and client leaves expire November 23, 2026; the new issuer expires February 14,
2027. The temporary client pod was deleted after verification. The detailed
result contains only status, deployment identity and certificate metadata; it
does not contain private key material.

This rotation addresses the exposed **G5 replay** credentials. It does not
provision Phase 7 operator client identities or the Phase 7 permit signing key,
so the Phase 7 managed-credential gate remains HOLD. Phase 6 workloads were
not changed.

## Precondition deviation

The first invocation was rejected by the script's own exclusivity check
because two `phase8-multilevel-hotel` pods (one not-ready, one Failed) carried
the `semantic-serving-client=sam3-mat-v1` label. No secrets were changed in
that invocation. The Phase 8 demo deployment was scaled from 1 to 0 and back
to 1 around the successful rotation; its not-ready pod was replaced by an
equivalent pod from the same ReplicaSet.
