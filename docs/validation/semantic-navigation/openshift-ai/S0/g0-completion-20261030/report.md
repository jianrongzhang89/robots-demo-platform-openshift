# G0 completion evidence — October 30–31, 2026

Status: **G0 technical PASS**, verified 2026-10-31T03:14:07.021730+00:00. The authoritative result is `../gate-result.json`. Codex performed the technical verification; the user explicitly approved G0 on October 31, 2026 (America/New_York). G1 inference and served navigation remain unqualified.

## Provisioned destination

`semantic-model-serving` contains the `sam3-serving` service account (no API token mount), a dedicated 10 GiB gp3-csi `sam3-checkpoint` PVC, resource quota, client policy, internal ClusterIP service on 8443 and network isolation. The serving account has an image-puller RoleBinding in `semantic-navigation`; it cannot read robotics secrets. The `sam3-replay` client account cannot read serving secrets.

The quota permits one GPU, CPU requests/limits of 8/16 cores, memory requests/limits of 28/56 GiB, one PVC and 10 GiB storage. The model profile remains CPU 3/6 cores, memory 12/24 GiB and one NVIDIA L40S. `sam3-g0-reservation` holds those resources on `ip-10-0-55-175.ec2.internal`, separately from local SAM3 on `ip-10-0-18-251.ec2.internal` and the accepted GPU-rendered fixture on `ip-10-0-44-146.ec2.internal`. Live CUDA 12.8, PyTorch 2.10.0+cu128 and BF16 support are recorded in `gpu-runtime.json`.

The renderer now includes the L40S node's `g6e-gpu=true:NoSchedule` toleration and accepts `--node-name` to retain the reserved placement. `rendered-candidate.json` pins the final built image and serving node. Every object passed server-side dry-run in the actual destination (`destination-admission.txt`). The InferenceService and ServingRuntime have **not** been created; G1 still owns model loading, parity, cold starts and OpenShift AI registration.

## Artifact and rollback

The accepted checkpoint is copied over authenticated Kubernetes exec streams to the new PVC, with SHA-256 validation before atomic rename. The expected SHA-256 is `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`. The original PVC and digest-pinned local SAM3 image remain the rollback artifacts.

The first copy attempt failed before writing because the selected SCC supplied no filesystem group. The loader was recreated with the namespace's allocated group `1000840000`; no root or privileged access was added. `checkpoint-copy-initial-permissions.json` retains that attempt. The final copy contains 3,450,062,241 bytes and matches the expected hash. Independent verification inside the actual serving image also passed, including shared-code hashes. Both `/models` and `/app` are now mounted read-only in the reservation pod; its imageID matches the expected digest.

## Transport and identity

`sam3-serving-tls` contains the serving certificate/key and trusted client CA. `semantic-navigation/sam3-replay-tls` contains the replay credential and server trust. The exact URI SAN `spiffe://semantic-navigation/sa/sam3-replay` is authorized only for `robot_1` / `camera/color` by `sam3-client-policy`. This is explicit certificate issuance by the cluster administrator, not automatic SPIFFE workload attestation.

Leaf certificates expire **November 7, 2026 at 02:58:59 UTC**. The 90-day issuer key is retained only in `semantic-model-serving/sam3-g0-issuer`; private material is absent from repository evidence and temporary issuance files were removed. These are initial short-lived credentials: renew leaves using the retained issuer and restart credential consumers before expiry. Automated renewal and rotation qualification remain S5 work. `commands/g0-security.py` records one-time issuance; it generates a new CA and must not be reused as an in-place rotation procedure.

A temporary pod ran the actual built server's TLS, request validation and identity-policy code without loading a model. Authorized metadata and predict calls returned the expected 503/not-ready. Missing client certificates and wrong server identities failed TLS; an issuer-signed but unbound principal and a spoofed robot returned 403. No inference success or parity is claimed from this probe. See `authentication-results.json`.

The approved namespace/pod selector could connect to port 8443; an unlabeled pod in that namespace timed out. The server could not connect to the Kubernetes API while the client control could, verifying egress denial. Image-pull permission and cross-namespace secret denials were checked independently. The initial image-pull RBAC check used the wrong `oc auth can-i` subresource syntax; `--subresource=layers` corrected the check without changing privileges. Both results are retained. Temporary transport/client pods and the unbound negative-test credential were deleted after verification. No Route or Ingress was created.

## Baseline reproduction

`baseline/plan.json` preserves the accepted series-23 geometry/profile as the source plan. This G0 run selects its first nominal off/on pair; it does not repeat the full 58-trial qualification. The evaluator requires both arms to complete collision-free, nonzero off exposure and at least 90% hull-exposure reduction, using the existing evaluator and 0.246 m hull radius. Speed remains 0.15 m/s; semantic-on uses the accepted lethal-254 experiment. The standing recognition waiver and belief/truth-divergence reporting remain in force.

The private topology temporarily replaces the demo SAM3 pod using its saved specification. The first off-arm attempt failed at the pre-arm capture-trace readiness gate; its full evidence remains in `baseline/trial-runs/trial-0-liveness-1`. The accepted infrastructure retry policy starts a fresh fixture without relaxing checks. The successful off-arm attempt and the first on-arm attempt passed every ordinary trial check. No trial check failure was retried. Hull exposure was **1.408739283 m off versus 0.000 m on (100% reduction)**; both trials completed without collisions. Path lengths were 3.917/5.198 m and completion durations 72.40/94.76 s, respectively. At arrival, belief/truth divergence was 0.528/0.974 m; physical goal distance was 0.574/1.048 m. These remain descriptive under the accepted Phase 6 completion convention, not evidence of 0.20 m physical arrival accuracy. See `baseline/measured-summary.json` and the full retained trial records.

The original demo SAM3 pod was restored 2/2 Ready on its original L40S, loaded/warmed the model and emitted valid results. `semantic-navigation/sam3-g0-rendering-reservation` now reserves the accepted fixture GPU and its aggregate requests (3.15 CPU, 3200 MiB, one A10G) on `ip-10-0-44-146.ec2.internal`. The serving reservation retains its separate L40S and 3 CPU/12 GiB request. Both reservation pods were Running at final verification.

The topology recovery helper no longer depends on the absent workstation file `/tmp/sam3-pod-r3.json`: it renders the pinned pod from the existing topology definition and waits for router availability before starting its one-shot bridge connection. This does not change model, planner, controller, timing limits or retry counts. Nineteen server/qualification tests and six baseline-harness tests passed, including reserved GPU placement and recovery ordering.

## Handoff

Before G1 deployment, recheck certificate validity and platform readiness. Verify the reservations are still Running and the checkpoint hash remains correct. Release `sam3-g0-reservation` immediately before applying `rendered-candidate.json`, because the quota/GPU allow only one model allocation. Keep the model pinned to the reserved node and mount its checkpoint read-only. The reservation is a temporary allocation, not a node taint or ownership claim; its seven-day process lifetime must not be mistaken for an indefinite reservation.

Release the rendering reservation only immediately before the next qualified fixture needs that GPU. Do not consume the restored local SAM3 GPU for serving. Preserve the original model PVC and local runtime for rollback. G1 must independently verify the resulting Pod imageID, warm-up/readiness, three cold starts, frozen replay parity, endpoint security and OpenShift AI dashboard registration.
