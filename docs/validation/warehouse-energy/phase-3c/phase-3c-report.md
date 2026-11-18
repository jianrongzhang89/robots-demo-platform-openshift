# Warehouse energy Stage 3C serving qualification report

**Date:** November 17, 2026  
**Status:** **COMPLETE / PASS.** The Stage 3C serving gate passed: the frozen Stage 3B
release is deployed as a versioned OpenShift AI CPU inference service behind mutual TLS,
and the qualification suite passed all eleven checks — model identity, offline/server
combined-prediction parity, local/server physics parity, wrong-version, out-of-envelope,
and oversized-batch rejection, malformed and stale-generation response rejection,
endpoint-unavailable physics fallback, cache reuse, and the latency target. Stage 4
(comparative demonstration) may proceed.  
**Runtime:** `energy-predictor-v1` InferenceService (RawDeployment-orchestrated, one warm
CPU replica) in the `semantic-model-serving` namespace, cluster-local, ingress-isolated to
labeled clients in `semantic-navigation` and `warehouse-energy`.

## Deployment

The serving image is built from the pinned hotel runtime image — the same Python 3.12.3,
numpy 1.26.4, and scipy 1.11.4 as the Stage 3B training environment — with the vendored
xgboost 2.1.4 tree (wheel digest recorded in the Stage 3B report; `libnccl` is not a
load-time dependency and is excluded). The frozen release artifacts, the shared physics
code, and a fail-closed manifest are baked in; the build self-test loads the predictor and
runs one full-batch inference before the image is pushed. The deployed pod's `imageID`
(`sha256:8bdcea5312a96bdff5b87dd661392e0f919610c61e087083263ac22ce8d73cd6`) matches the
rendered, digest-pinned image — container identity is verified from the pod status, not
self-attested.

The serving contract packages feature validation, the calibrated physics calculation, the
XGBoost residual model, and the uncertainty calibration together, exactly as the proposal
requires: requests carry raw planning-time segment inputs (length, ramp geometry, signed
rise, speed, turn, stops, dwell, mass, class), and the server derives the features,
computes the physics baseline with the frozen Stage 2 model, applies the residual with the
physical-bounds rule, and returns per-segment physics, residual, and combined estimates
plus the frozen allowances. Batches are limited to 32 segments; one batch is admitted at a
time. Health is unauthenticated on 8080; all model data requires a client certificate on
the data port. Model identity (name, frozen release hash, artifact digests) is served only
over mTLS.

One platform adaptation is recorded: the cluster's OpenShift AI 3.5.2 KServe controller
injects a `kube-rbac-proxy` sidecar on pod port 8443 for new InferenceServices (the
accepted SAM3 deployment predates that platform upgrade). The mutually authenticated data
port therefore listens on 8090 and the cluster-local TLS Service
(`energy-predictor-v1-tls.semantic-model-serving.svc:8443`) targets it directly; the
injected proxy is present but unused, and the InferenceService reports Ready with all
containers healthy.

## Qualification results

The qualification client ran in an isolated, labeled pod in `semantic-navigation` with
mTLS credentials provisioned as Secrets (credential bytes never committed). All eleven
checks passed ([`qualification-result.json`](qualification-result.json)):

| Check | Result | Evidence |
| --- | --- | --- |
| Model identity over mTLS | PASS | name, frozen release SHA-256, artifact digests, batch limit match the frozen release |
| Offline/server combined-prediction parity | PASS | 24 replay batches, 96 segments; all predictions within 1e-9 Wh of the frozen offline expectations |
| Local/server physics parity | PASS | served physics equals the dataset's frozen local physics values within the same tolerance |
| Wrong model version rejected | PASS | HTTP 400 `invalid_input` |
| Out-of-envelope input rejected | PASS | speed above the frozen envelope rejected |
| Oversized batch rejected | PASS | 33-segment batch rejected against the frozen limit of 32 |
| Malformed response rejection | PASS | missing identity, wrong frozen hash, stale generation, request mismatch, non-finite values, count mismatch, and wrong allowance all rejected by the client validator |
| Endpoint-unavailable physics fallback | PASS | unreachable endpoint falls back to local calibrated physics with the frozen 0.037 Wh conservative allowance |
| Cache reuse under a new generation | PASS | identical inputs served from cache; generation echoed per request |
| Latency target | PASS | 100 fresh 32-segment requests: **p95 69.5 ms** (target 250 ms), max 98.9 ms (deadline 1 s) |
| Latency-batch parity | PASS | the 32-segment batch also reconciles within 1e-9 Wh |

The replay batches ([`replay-batches.json`](replay-batches.json)) were built in the pinned
training pod from the Stage 3A navigation runs using exact graph-derived inputs; their
offline expectations are the dataset's frozen physics values plus the frozen release's
booster predictions, so the parity checks verify the complete serving path — request
validation, feature derivation in the built image, serialized inference — against
independently frozen numbers. A subtle derivation detail is pinned by unit tests: the
server's feature derivation reproduces the Stage 3A dataset rows bit for bit (including
sample-order-dependent float summation and the exact graph turning angles), which the
`test_nav_dataset_rows_reproduce_exactly` test guards locally.

## Stage 3C gate status

| Gate | Status | Evidence |
| --- | --- | --- |
| CPU serving deployment of the frozen release | PASS — one warm replica, digest-pinned image, Ready | `deployment.json`, InferenceService status |
| Offline/server combined-prediction parity | PASS — 96 segments within 1e-9 Wh | `qualification-result.json` |
| Local/server physics parity | PASS | `qualification-result.json` |
| Timeout/unavailable fallback | PASS — documented physics fallback with conservative allowance | `qualification-result.json` |
| Wrong-version rejection | PASS | `qualification-result.json` |
| Malformed-response rejection | PASS | `qualification-result.json` |
| Stale-generation rejection | PASS | `qualification-result.json` |
| Invalid-input rejection | PASS — envelope and batch limits | `qualification-result.json` |
| Latency target | PASS — p95 69.5 ms vs 250 ms target at batch 32 | `qualification-result.json` |

## Assumptions and limits

The service serves modeled energy predictions for the frozen warehouse fixture only; no
physical calibration, route-choice, or energy-saving claim is made here. The uncertainty
allowances are those frozen in the Stage 3B release (13-mission calibration caveat
retained). Request-time training, downloads, and state are absent by construction; the
admission model is one batch at a time with immediate 429 rejection of concurrency. The
mTLS credentials are provisioned as cluster Secrets with a recorded rotation expectation
following the existing G5 practice.

## Reproduction and evidence

Render and deploy from a repository checkout (the serving image must first be built via
the `energy-predictor-s1` binary BuildConfig from a context containing the repository
paths and the vendored xgboost tree):

```sh
python3 helm/warehouse-energy-demo/openshift-ai/render.py --image <digest-pinned-image> | oc apply -f -
python3 scripts/warehouse-energy/provision_energy_serving_credentials.py
```

Rebuild the replay expectations in the pinned pod with
`build_energy_replay.py`, then run the qualification suite from a labeled client pod with
the client TLS Secret mounted (see `scripts/warehouse-energy/README.md`). Stage 3C unit
tests: `python3 -m unittest test_stage3c` from `scripts/warehouse-energy/` (13 tests:
input validation, exact dataset-row feature parity, response validation, and fallback).
