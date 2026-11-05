# S5 lifecycle and operations — November 4, 2026

G5 remains **HOLD / in progress**, not accepted. Stopped lifecycle operations,
actual pod-loss and wrong-version safety demonstrations have passed. The dashboard
has 21 panels and live navigation sources have been queried through Thanos.
Browser/evidence-link review and the new-presenter run remain outstanding. G4's
acceptance and paused paired-series campaign remain unchanged.

## Verified results

| Work | Result and evidence |
| --- | --- |
| Registry | Registered in `ryans-model-registry` (model 3, version 4, artifact 2). Complete identity, checkpoint locator, policy, evaluation limitations and immutable evidence links read back exactly. Second invocation reused all three IDs with no writes. `registry-registration-1.json`, `registry-readback-2.json` |
| Candidate build | Separate `g5` tag; digest `sha256:af5cb7325f08fd137380d488745cba3a229857cb57d059d31befce93e25246c9`. Shared inference modules match the accepted baseline hashes. `candidate-build.json`, `candidate-source-hashes.json` |
| Update/rollback | Three complete Recreate cycles, six distinct replacement pod UIDs, three frozen frames passing at each candidate and rollback state. Final restoration parity passed. `replay-cycles-1/result.json` and per-transition reports |
| Credentials | Rotated CA, server and replay-client leaves; full loaded identity unchanged. New credentials succeeded, old client failed with TLS `unknown ca`, absent client failed with `certificate required`. `rotation-1/result.json` |
| Read-only monitor | Dedicated URI principal maps to zero allowed inference pairs. Live metadata/metrics reads succeeded; a valid inference request returned 403. `monitoring-1/result.json` |
| Monitoring | Authenticated HTTPS ServiceMonitor, narrowly scoped Prometheus ingress, and 21-panel Perses dashboard applied. Thanos verified scrape `up=1`, worker ready, request counts, GPU utilization/memory and running image inventory. `monitoring-verification-1.json`, `monitoring-safety-final.json` |
| Dependency isolation | Actual serving pod could not connect to registry/dashboard route IPs or external HTTPS; control client could. Frozen replay still passed. `dependency-isolation-2.json`, `post-isolation-parity.json` |
| Recovery | Replacement after rotation and monitor-policy reload returned to Ready with the pinned loaded identity and passing replay. Separate moving pod-loss evidence is recorded below. `rotation-1/result.json`, `monitoring-1/result.json`, `post-operations-parity.json` |
| Tests | 22 server tests, 42 shared-perception tests, 10 operational/telemetry/attribution tests (including the three lifecycle/rotation tests), four preflight tests. Failure-injection tests verify original runtime/strategy or original Secret data restoration. `server-tests.txt`, `shared-regression-tests.txt`, `operations-tests.txt`, `safety-tool-tests.txt`, `safety-final-tests.txt`, `validation.txt` |

The candidate adds bounded histograms for admission, backend work, worker
occupancy and queue delay. There is no queue: busy admission still immediately
rejects; admitted queue delay is zero. Backend timing includes shared-backend
processing, not just GPU kernels. These metrics do not measure capture freshness.
The candidate ran only in replay; it is **not qualified for navigation**. The
accepted `f9bcc273…` runtime is restored and retained. Candidate histogram panels
therefore show no current data on the rollback runtime; captured candidate metrics
are retained in `replay-serving-samples.jsonl`. Missing data is not filled with zero.

## Corrections and retained unsuccessful evidence

The initial preflight used the ambiguous short resource name `modelregistries`,
which selected the platform component. The corrected script uses
`modelregistries.modelregistry.opendatahub.io` and its `Available` condition.
`preflight-20261104-2.json` verifies the actual registry instance. The original
snapshot remains retained and is not proof of instance readiness.

The cluster has upgraded to OpenShift AI **3.5.2**, versus 3.4.2 in the accepted
historical records. This drift is recorded rather than rewriting those records;
the final preflight includes current cluster/operator versions. Stopped replay and the two bounded safety demonstrations on the current platform
passed. Capture-stream RTF over their fault/recovery windows was 0.6736 for pod loss
and 0.6786 for wrong version (`rtf-audit.json`). These are scoped observations, not
a repeat of the three ten-minute G3 qualification runs or the full G4 campaign.

`dependency-isolation-1.json` is FAIL: platform ingress restrictions also blocked
the replay client's direct ClusterIP positive controls for registry/dashboard.
The external HTTPS control already succeeded. The second attempt uses supported
registry/dashboard ingress routes, resolves them first, and tests direct IPs on
443 from both source pods. This fixes the control path without weakening the
requirement that controls connect and the serving pod times out. No shared
platform service was stopped and no serving egress permission was added.

The generated KServe ServiceMonitor targeted HTTP; it was left unchanged. The new
`sam3-g5-authenticated` monitor targets the explicit mTLS service. Only labeled
Prometheus pods in `openshift-user-workload-monitoring` gain network access, and
the dedicated certificate principal cannot submit inference requests.

## Current cluster state and remaining gate work

- Accepted serving runtime retained Ready; original rollout strategy restored.
- Server leaf expires **2026-11-11 14:14:48 UTC**; replay client expires one second
  later. Monitor leaf expiry is in `monitoring-1/result.json`. Issuer Secret keeps
  the existing name `sam3-g0-issuer` but now holds the G5 CA. Future proxy issuance
  must use the current issuer/trust bundle; old leaves are retired.
- Registry entry, monitoring resources, monitor credential/policy, separate build
  and candidate image are intentional retained deliverables.
- Temporary `sam3-g5-client` removed; ephemeral retired/monitor key copies removed.
  Rendering reservation, accepted local SAM3 and hotel-sim at zero are checked in
  `preflight-safety-final.json`; `cleanup-safety-final.json` records no temporary
  G3/G4/native or proxy resources. The costmap wrapper returned PASS with cleanup
  complete. No sampler or new G4 campaign remains active.

## Integrated safety demonstrations

Both use the accepted served runtime and original native ROS safety fixture,
500 ms semantic freshness threshold, 100 ms trigger-to-applied-zero limit,
contact checks and unchanged original evaluator. Semantic perception is
observation-only in this fixture; these trials do not claim semantic cost influence
on the navigation path or qualify the metrics candidate for motion.

| Fault | Result | Trigger to applied zero | Confirmed stationary | Recovery |
| --- | --- | --- | --- | --- |
| Actual serving-pod deletion | PASS, `pod-loss-5/result.json` and `attribution.json` | 1.266446 ms | 885.254230 ms | New pod UID with accepted image, fresh results, no automatic resume over 482 native samples |
| Wrong response version during verified motion | PASS, `wrong-version-1/result.json` | 0.912384 ms | 848.010457 ms | Identity fault latched; ordered adapter replacement, fresh results, no automatic resume over 476 native samples |

Stationary time is recorded separately from the applied-zero bound. The pod-loss
attribution brackets deletion in the fixture's clock using a source timestamp and
the complete host-monotonic command round trip. Its conservative deletion upper
bound precedes the watchdog stop by 1354.617202 ms. Host and cluster wall clocks
differed; direct subtraction between those clocks would be invalid.

All unsuccessful attempts remain visible. `pod-loss-1` encountered a stale fixture
ConfigMap before setup; its full record was retained before removal. Attempt 2
used default graceful deletion and stopped normally before the outage. Attempt 3
never armed or received any native command packet: its readiness timeout has
21,505 explicit zero-packet/disarmed native samples and zero semantic results.
`g5_prearm.py` records the narrow setup-retry rule and rejects any packet, armed
sample, coordinator/fault event or failed existing check. The G4 classifier is
unchanged. Attempt 4 used one-second grace but extra CLI reads delayed injection
until normal stopping; it remains FAIL. Attempt 5 freezes the corrected immediate
delete path and passes the original evaluator plus the separate attribution test.
No armed failure was retried with the same protocol or relabeled as a setup retry.

## Passive navigation telemetry

The exporter has no ROS connection, service-account token, GPU or egress access.
An operator collector copies source-stamped adapter, fixture and applied-costmap
observations into it. Prometheus ingress is restricted to user-workload monitoring.
Metrics cover capture-to-result/costmap latency, last capture age, drops, RTF,
armed state and bounded stop-reason labels. Source timestamps older than ten
seconds, absent timestamps and future timestamps produce unavailable status and
omit state/latency values. This dashboard TTL never changes the robot's 500 ms
safety threshold. Applied command traces remain in the native evidence.

`navigation-live-verification-2.json` verifies live fixture/adapter data through
Thanos, including 0.189000684 s capture-to-result latency and capture-stream RTF
0.641558824 in the sampled window. The original collector used the host clock;
`navigation-collection-1.jsonl` is exploratory and is not freshness proof. The
corrected collector preserves host time separately and uses source clocks.
`navigation-live-verification-1.json` remains FAIL because its fixture produced no
semantic results. No missing value was converted to a healthy zero.

`costmap-telemetry-3` verifies a separate stationary source: all 254 captured
results match applied request IDs and capture timestamps in **both** global and
local maps (100% coverage, no unexpected in-window IDs or capture/stream mismatch).
The 60-second costmap trace has p95 capture-to-costmap upper ages 252.945 ms global
and 253.458 ms local. Thanos independently observed the applied-costmap metric.
There is no safety fixture in this stationary demonstration, so its safety status
correctly remains unavailable. See `correlation.json`, `costmap/summary.json` and
`monitoring.json` within that attempt.

The historical CPU worker lacked capacity (`costmap-telemetry-1`); the alternate
worker lacked the required socket-buffer limit (`costmap-telemetry-2`). Both
attempts are retained FAIL with successful cleanup. Attempt 3 co-locates the
CPU-only consumers on the already tuned G4 rendering worker, with the existing
simulator's narrow toleration and unchanged images, resource requests and DDS
settings. It makes no new G3 timing/navigation qualification claim. Its longer
costmap collection brackets the 40-second capture window; the 95% correlation
threshold was not changed.

`navigation-unavailable-verification.json` passes after collection stopped: snapshot,
adapter, safety and costmap availability all equal zero; capture/result/costmap
latency, last capture, RTF, armed/stop reason and drop series are absent.

Browser automation returned **No browser is available**; `dashboard-browser-check.json`
records NOT_RUN. API verification does not establish visual usability or that the
presenter can follow the evidence links. The new presenter must review the complete
identity/evidence, perform the runbook including explicit recovery/resume, and
record their name, date and evidence before technical G5 PASS can be considered.
User acceptance is separate. No presenter identity or acceptance is recorded.

Registry implementation follows the installed v0.3.10 [upstream API schema](https://github.com/kubeflow/model-registry/blob/v0.3.10/api/openapi/model-registry.yaml).
Deployment/monitoring schemas were checked against the installed CRDs and existing
platform dashboards. No acceptance criterion or navigation safety threshold changed.
