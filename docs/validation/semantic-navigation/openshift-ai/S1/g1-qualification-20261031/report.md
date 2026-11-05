# G1 live model qualification — October 31, 2026

**Technical result: PASS.** The pinned model is deployed, warm and Ready in `semantic-model-serving`. Codex performed the technical verification; the user signed off G1 on October 31, 2026. G0 remains user-approved. The authoritative result is [gate-result.json](../gate-result.json).

## Deployed configuration

- InferenceService: `semantic-model-serving/sam3-mat-v1`; ServingRuntime: `sam3-runtime-v1`.
- Supported application origin: `https://sam3-mat-v1-tls.semantic-model-serving.svc:8443`; inference path: `/v1/models/sam3-mat-v1:predict`.
- Runtime image: `image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-model-server@sha256:f9bcc273a164f741426079ccf4c9d2269c9ec5e9530845029e593bf466a3aa2e`.
- Weights SHA-256: `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`; source revision: `0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc`.
- L40S on `ip-10-0-55-175.ec2.internal`; BF16; PyTorch 2.10.0+cu128; CUDA 12.8; driver 580.95.05. Model and application mounts are read-only.
- Model-container requests/limits remain CPU 3/6 cores, memory 12/24 GiB and one GPU. OpenShift injects a KServe agent with an additional 100m CPU/100 MiB request and 1 CPU/1 GiB limit. This fits the existing quota; only the model container requests a GPU.

The supported client path is the dedicated mTLS Service. KServe's generated `http://sam3-mat-v1-predictor...` status URL is not the supported custom JSON/mTLS application endpoint. Health and agent ports are blocked for clients. No Route or Ingress exposes the model publicly. This custom contract does not claim KServe V2 tensor-protocol support.

[Final resources](final-serving-resources.json), [deployed manifest](deployed-manifest.json), [hardware](live-hardware.json), [driver](live-driver.txt) and [final admission](final-manifest-admission.txt) retain the actual configuration. The original local SAM3 pod and separate rendering reservation remain Running; see [rollback and rendering capacity](rollback-and-renderer.json). The serving reservation was replaced by this InferenceService.

## Frozen reference and parity

The local reference was generated before deploying the endpoint, in the isolated GPU reservation using the same image, checkpoint, shared runner and L40S/BF16 configuration. It did not run in the active robot pod. Archived source-image hashes were verified before conversion to lossless RGB requests. The three cases are mat present, absent target, and a synthetic black empty-mask image. Local output contains one mask for the mat and zero masks for the two negative cases.

The [qualification plan](qualification-plan.json) was written before served comparisons. The frozen replay manifest SHA-256 is `5e000545e7ba6fb4f97932a7825b7fa9016831724fbf76758f80612a41bc2a90`.

| Criterion | Required | Observed |
| --- | --- | --- |
| Per-frame union-mask IoU | ≥0.99 | 1.0 for every comparison |
| Empty/nonempty agreement | 100% | 100% |
| Occupied-fraction difference | ≤0.005 | 0.0 |
| Cases | Mat, absent target, empty mask | All three |

Three replay batches produced **nine exact comparisons across three unique frames**, including a batch after the process-hang recovery. Requests, baseline responses and their checksums are retained in [frozen/manifest.json](frozen/manifest.json). See [run 1](parity-1.json), [run 2](parity-2.json) and [run 3](parity-3.json). This small frozen set establishes the declared backend parity only; it does not close the standing recognition waiver or establish live navigation latency.

## Cold starts and recovery

Three distinct Pod UIDs independently loaded the model. Every cycle exposed HTTP 503 with `ready=false` and no deployment identity before returning a verified loaded identity. The implementation assigns its backend only after artifact verification, precision checking and a full-size warm-up; actual Pod imageIDs matched the expected digest in all cycles.

| Cycle | First ready response after probe-loop start | Evidence |
| --- | --- | --- |
| 1 | 30.942 s | [Readiness samples](cold-start-1/readiness.json) |
| 2 | 10.425 s | [Readiness samples](cold-start-2/readiness.json) |
| 3 | 10.779 s | [Readiness samples](cold-start-3/readiness.json) |

These are fresh process/model starts, not host reboot or uncached image-pull benchmarks. Timing begins when the in-cluster probe loop starts after the new Pod receives an IP. Cached image layers and filesystem pages are not evicted. Full Pod states, container start times, logs and InferenceService conditions are archived beside each readiness record.

The live hang test stopped the entire server process. Sending SIGSTOP from inside its PID namespace was ignored because the server is namespace init; [that ineffective attempt](process-hang-1/result.json) is retained and is not counted as a fault result. A temporary node-debug command then checked the exact CRI container ID, process command and cgroup before delivering SIGSTOP from the parent PID namespace. It confirmed the stopped state; the debug pod was removed.

Kubelet recorded liveness failures, removed readiness, restarted the model container once, and restored service. Recovery was observed **53.15 s after the host injection command began**, including debug-command startup. Post-recovery replay again matched exactly. See [result](process-hang-2/result.json) and [events](process-hang-2/events.json). The worker-only busy timeout is covered by unit tests; this live injection tests a whole-process hang. No claim of a 500 ms robot stop follows from this backend restart measurement.

## Contract, security and network checks

All **22 live checks passed** in [live-contract-1.json](live-contract-1.json): loaded identity, full-resolution prediction, missing certificates, an issuer-signed but unbound principal, server hostname validation, unauthorized robot/stream, malformed/nonfinite JSON, invalid envelopes/content type, wrong model/policy/prompt, pixel bounds, expired budgets, oversized/slow uploads, the exact 28 MiB wire boundary, bounded concurrent admission and recovery to healthy predictions.

A 16-request concurrent burst produced one valid prediction, seven HTTP 429 overload responses and eight TLS connection rejections at the bounded transport-worker limit. No invalid or cross-request prediction was accepted. The exact 28 MiB legal request succeeded; larger declared requests returned 413 and stalled uploads returned 408. The endpoint remained healthy afterward.

[Network checks](network-results.json) confirmed that the authorized labeled client could reach 8443, an unlabeled client could not, and client access to health port 8080 and agent port 9081 was blocked. The model pod could not initiate a connection to the Kubernetes API while a client control could, with a deny-all-egress policy active throughout model loading and inference. The serving pod mounts no API token, and no public endpoint exists.

The final local runs passed **19 server/qualification tests and 27 shared perception/contract tests**. See [server tests](server-tests-final.txt) and [shared tests](shared-regression-tests.txt).

## OpenShift AI registration

The authenticated AI dashboard API returns the project, Ready InferenceService and correct ServingRuntime. Inspection of the installed frontend showed that project, model and runtime lists require `opendatahub.io/dashboard=true`. The initial runtime lacked that label despite being returned by the unfiltered API. The label was added to the live runtime and resource renderer, and a regression assertion now covers all three resources. The running Pod UID and container IDs were unchanged by this metadata correction.

[Visibility verification](dashboard-visibility.json), [dashboard API results](dashboard-api-results.json) and the installed frontend selection code are retained. No browser surface was connected, so this is API/selection-rule verification, not a visual screenshot review. The initial missing-label evidence is preserved in [dashboard-initial-filter-check.json](dashboard-initial-filter-check.json).

## Retained issues and handoff

The first replay invocation used a flattened `/tmp` path and failed while resolving the repository root, before any inference request. Preserving the script's directory layout fixed the invocation; [the attempt](parity-initial-harness-error.json) is retained. No parity threshold, model weight or inference code changed during qualification.

Temporary replay/negative-test pods and the unbound certificate Secret were deleted after qualification. The positive replay credential and server certificate remain in their existing Secrets; no private key material is stored in this evidence directory. Leaf certificates expire **November 7, 2026 at 02:58:59 UTC**. Renew credentials before expiry and restart consumers as required. The separate rendering reservation still has its documented seven-day lifetime.

The next gate is **G2: CPU ROS adapter integration**, including reset/late-result rejection and transport/auth/version failure behavior. G3 measures live timing/projection; G4 qualifies served navigation. Neither ROS routing nor robot motion was switched to this endpoint during G1.
