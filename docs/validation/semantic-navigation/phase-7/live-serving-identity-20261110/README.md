# Live SAM3 serving identity probe — November 10, 2026

**Result: PASS for authenticated metadata and identity verification.** A short-lived pod labeled with the approved `sam3-mat-v1` replay-client policy mounted the existing `sam3-replay-tls` credential read-only and performed only `GET /v1/models/sam3-mat-v1` against the live internal HTTPS service. TLS chain and hostname verification succeeded; the service returned HTTP 200 and `ready: true`.

The returned identity pins the deployed server image `sha256:f9bcc273a164f741426079ccf4c9d2269c9ec5e9530845029e593bf466a3aa2e`, weights `sha256:9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`, model revision `3c879f39826c281e95690f02c7821c4de09afae7`, and policy `avoid-target/v1`. It supports only the approved `red mat` prompt. The KServe Pod was separately confirmed Ready with its `kserve-container` `imageID` matching the metadata digest; that snapshot is `serving-pod-image.json`. The metadata probe did not submit image data or change the serving deployment. The identity, raw metadata response, and probe pod spec are archived here; the probe pod was deleted afterward. `SHA256SUMS` covers the archived evidence.

This validates the live model-service identity and current replay credential. It does not qualify Phase 7 prompt transitions, another category, or production operator credentials.
