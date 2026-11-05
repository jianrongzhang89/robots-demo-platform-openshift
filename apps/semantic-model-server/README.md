# SAM3 OpenShift AI runtime (S1)

This package serves the existing `semantic-inference/v1` application contract at
`POST /v1/models/sam3-mat-v1:predict`. It reuses the three shared Python modules in
`apps/semantic-perception`; no ROS node, tracking session, depth processing or
motion authority runs in the server. This is custom JSON on a KServe-managed
predictor, not V2 tensor-protocol support.

**G0 is user-approved and G1 technical qualification passed.** The pinned
InferenceService is deployed and Ready; G1 was signed off by the user on October 31, 2026. See the
[qualification record](../../docs/validation/semantic-navigation/openshift-ai/S1/report.md).

## Identity and admission

`model-manifest.json` freezes the checkpoint hash/revision, SAM3 source revision,
red-mat prompt, threshold 0.5 and BF16 precision. The container inherits the pinned
Phase 6 SAM3 dependency image. It builds a manifest of the shared Python file
hashes; startup verifies those files and streams the checkpoint through SHA-256
before loading it. Readiness follows full-size warm-up and a precision check.
The checkpoint is mounted read-only; no downloads occur during startup or
requests. Offline library settings and an egress-deny policy enforce this design
when the candidate is deployed.

Successful responses and valid-envelope failures add `deployment`, with schema
`semantic-deployment/v1`, to the unchanged v1 fields. It contains model name,
weight hash, source revision, shared-code hashes, container digest, versions,
precision and prompt policy. Metadata at `GET /v1/models/sam3-mat-v1` returns the
same identity. Existing `versions.model` retains its revision meaning.

The checkpoint and shared-code hashes are measured at startup. Source provenance
comes from the digest-pinned base image; the source revision is recorded at build
time. The container digest is deployment-supplied, not self-attestation: live
qualification must compare the expected image digest with Pod `imageID` and pin
the complete metadata identity before replay. A server's own assertion is not
independent proof of its container identity.

Admission allows one model call at a time and immediately rejects concurrent
calls with HTTP 429. There is no inference queue. At most eight transport workers
hold uploads/connections; excess connections are closed. Inputs are bounded by
the shared 28 MiB contract limit, a five-second upload deadline and two-second
socket timeouts. Server budget accounting includes upload, validation and
response encoding. It cannot cancel an executing CUDA kernel or enforce the
client's capture deadline across hosts; the S2 client must enforce that deadline
through response download and decoding. Requests are never retried.

Malformed envelopes receive HTTP 400 without echoing absent identity fields.
Valid empty masks are HTTP 200; timeout, overload, not-ready and inference failure
are distinct failures. A worker busy for ten seconds fails health checks; the
candidate probes then restart the process. Startup has a separate ten-minute
limit. These are server recovery bounds, not the robot's 500 ms watchdog.

## Internal endpoint and credentials

Port 8443 requires mutual TLS for prediction, metadata and metrics. Certificates
must chain to the configured client CA and contain exactly one URI SAN listed in
the client policy. The policy binds that authenticated principal to allowed
robot/stream pairs. Certificate validity is checked on each request, including
reused connections. An absent certificate fails TLS; a trusted certificate with
an unknown principal, or a spoofed robot/stream, receives HTTP 403.

The proposed replay principal is
`spiffe://semantic-navigation/sa/sam3-replay`. This URI is an explicit certificate
policy, not a Kubernetes TokenReview claim or automatically issued SPIFFE
identity. The platform owner must provision short-lived client credentials for
that principal and a trusted server certificate for
`sam3-mat-v1-tls.semantic-model-serving.svc`, before deployment. The candidate
references Secret `sam3-serving-tls` with keys `tls.crt`, `tls.key` and
`client-ca.crt`; no credentials are stored in this repository. Credential
rotation/reload is a later S5 qualification item; certificate material is loaded
at process startup.

Port 8080 exposes only `/live` and `/ready` for probes. It never exposes inference
or metadata. The stable application endpoint is the explicit ClusterIP TLS
Service on 8443, not an automatically generated KServe HTTP URL. The installed
cluster has ingress creation disabled; the rendered NetworkPolicy also denies
all ingress except port 8443 from labeled clients in `semantic-navigation`, and
denies all serving egress. The predictor has no service account token. KServe
service wiring, dashboard API/selection rules, GPU scheduling, egress denial and
the loaded TLS endpoint passed live G1 verification. The application origin is
`https://sam3-mat-v1-tls.semantic-model-serving.svc:8443`; the generated KServe
HTTP status URL is not the supported client endpoint.

## Build and render

Run commands from the repository root. The build context must preserve the
`apps/semantic-model-server` and `apps/semantic-perception` paths. Supply only the
Containerfile, server/manifest files and three shared modules; do not upload the
full validation archive to the build.

```sh
oc apply -f helm/semantic-navigation/openshift-ai/build.yaml
oc start-build semantic-model-server-s1 -n semantic-navigation --from-archive=/path/to/minimal-context.tar
oc get istag semantic-model-server:s1 -n semantic-navigation -o jsonpath='{.image.dockerImageReference}'
python3 helm/semantic-navigation/openshift-ai/render.py --image IMAGE_AT_SHA256 --node-name RESERVED_L40S_NODE > /tmp/serving.json
oc apply --dry-run=server --validate=true -f /tmp/serving.json
```

The renderer creates candidate Namespace, service account, client policy,
ServingRuntime, InferenceService, TLS Service and NetworkPolicy resources. It
does not apply them. It requires an image digest, fixes one L40S replica, and
preserves the accepted 3/6 CPU and 12/24 GiB request/limit profile. Cross-project
image pulling needs an explicit pull grant. Provision and verify a
`sam3-checkpoint` PVC **in the serving project** before use; the existing robotics
PVC cannot be mounted there. Reserve an L40S separately from the live renderer.

The final built image is deployed on the reserved node in
`semantic-model-serving`; the serving reservation was released during G1.
See the [live qualification and handoff](../../docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031/report.md).
The quota permits one GPU, so replacement deployments must account for the
existing model allocation. Recheck certificate validity before deployment;
the current leaf credentials expire November 7, 2026 at 02:58:59 UTC.

## Tests and replay

```sh
PYTHONPATH=apps/semantic-model-server:apps/semantic-perception python3 -m unittest discover -s apps/semantic-model-server/tests -v
PYTHONPATH=apps/semantic-perception python3 -m unittest discover -s apps/semantic-perception/tests -v
python3 scripts/semantic-navigation/check_serving_prerequisites.py --output /tmp/new-inventory.json
```

Local tests use a deterministic runner, plus real HTTPS connections and ephemeral
test certificates. They do not establish GPU parity or real cold-start behavior.

The proposed frozen source set is
`docs/validation/semantic-navigation/openshift-ai/S1/replay-selection.json`: an
archived mat frame, an absent-target tile frame and a synthetic black image for
the empty-mask case. The archived JPEGs are decoded once and transported as
lossless RGB8 to both backends. Their source hashes are fixed. A local GPU run
must confirm the black image actually produces an empty result; an unexpected
result fails the freeze. This small set tests backend plumbing, not recognition
accuracy or live timing.

In a separate GPU evaluation environment with the built runtime and repository
captures available, generate the local response baseline before contacting the
served endpoint:

```sh
python3 scripts/semantic-navigation/freeze_serving_replay.py \
  --selection docs/validation/semantic-navigation/openshift-ai/S1/replay-selection.json \
  --model-manifest /app/model-manifest.json --model-dir /models \
  --build-identity /app/build-identity.json --runtime-image-digest sha256:ACTUAL_DIGEST \
  --output /evidence/local-baseline
```

Archive the local manifest and outputs, actual GPU/precision inventory and
Pod image IDs. Obtain server metadata through verified mutual TLS and compare it
against the pinned artifacts before recording `expected-identity.json`. Then:

```sh
python3 scripts/semantic-navigation/replay_serving_parity.py \
  --manifest /evidence/local-baseline/manifest.json \
  --identity /evidence/expected-identity.json \
  --endpoint https://sam3-mat-v1-tls.semantic-model-serving.svc:8443 \
  --ca /credentials/server-ca.crt --cert /credentials/client.crt --key /credentials/client.key \
  --output /evidence/parity-attempt-001.json
```

The parity checker requires per-frame union-mask IoU ≥0.99, identical
empty/nonempty status, and occupied-fraction difference ≤0.005. It checks hashes,
response identities and the complete loaded deployment identity. Five-second
offline request budgets do not establish S3 latency. Preserve each attempt;
output paths cannot overwrite existing reports. G1 additionally requires three
cold starts, real readiness/auth/restart/input-bound tests, dashboard visibility
and observed no-egress behavior. G0 and all those checks must pass before G1 can
be accepted. Navigation, the CPU ROS adapter and live motion remain later phases.

## G5 candidate monitoring

The G5 candidate adds fixed cumulative histograms for admission (request arrival
through upload/validation to worker acquisition), backend call time, total worker
occupancy, and queue time. Queue time is explicitly zero because admission never
queues: busy requests still receive 429. Backend timing includes the shared
backend's decoding and output construction; it is not CUDA kernel timing.
Worker timing includes failed work and serialization. These server measurements
are not capture-to-result or capture-to-costmap latency.

The original `semantic_inference_duration_seconds_sum` remains for compatibility;
it is a successful-response work sum and must not be treated as a percentile.
New histograms use fixed names/buckets and no robot, request, or credential labels.
A client-policy principal mapped to `[]` may read metadata/metrics but cannot
submit any robot/stream pair for inference. Port 8080 remains health-only.

Build G5 with `helm/semantic-navigation/openshift-ai/build-g5.yaml`; this uses a
separate `g5` tag and does not overwrite the accepted `s1` tag. A built candidate
is not navigation-qualified until the applicable gates are rerun.
