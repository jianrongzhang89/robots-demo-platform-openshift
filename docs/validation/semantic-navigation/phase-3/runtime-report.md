# Phase 3 SAM3 live-inference runtime

- **Status: PASS; Phase 3 complete, user review approved October 16, 2026.** The user subsequently authorized isolated [Phase 4 work](../phase-4/runtime-report.md); Phase 4 acceptance is tracked separately. Capture-origin timing, native compression, bounded admission, reset hardening and the receiver recovery profile passed the final sustained/fault checks. Earlier failures and partial measurements remain below as history.
- **Final 600-second result:** 4,092 valid mask/cloud pairs, **6.82/s**, **100% pairing**, p95 render-start-to-paired-arrival **236.79 ms**, and p95 through observer validation **243.93 ms**. No readiness interruptions or >500 ms publication gaps. [Complete evidence](capture-timing-consumer-final-600s-20261016.json).
- **Phase 2 authorization:** User approved advancing on October 16, 2026, with the 31 additional development labels and held-out recognition evaluation deferred for this demo. This is a process waiver; it does not establish the waived recall/IoU/false-positive metrics.
- **Recognition configuration:** provisional prompt `red mat`, confidence threshold `0.5`; not frozen. This is used only to exercise the runtime.
- **Model:** original `facebook/sam3`; source commit `0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc`; checkpoint revision `3c879f39826c281e95690f02c7821c4de09afae7`; checkpoint SHA-256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`.
- **Current candidate image:** `sam3-runtime:phase3-timing`, build 7, digest `sha256:f4972af2f294c57d5662284fe3ad027b113fbed990690c55cbeacc4f19512726`. The [bounded native-input manifest](../../../../helm/semantic-navigation/phase3-native-bounded-diagnostic.yaml) pins this runtime, instrumented simulator `d417c9f…`, native compressor build 2 `c3ba94b…`, and the 40 ms work-wait limit. The output consumer must explicitly select the included `cyclonedds-consumer.xml` profile (1 ms NACK delay); the default profile is not qualified for low-latency delivery of large clouds. Earlier images and measurements remain below; timing build 6 was cancelled before deployment and is not qualified.
- **Isolation:** private Phase 3 Zenoh router, distinct Gazebo partition and ROS domains 79/80, separate CPU simulator and L40S inference pod. Only compressed camera RGB/depth, CameraInfo, TF, `/clock` and diagnostic capture/compression traces flow to inference. No navigation command topic, Nav2, costmap, RMF, or OpenShift AI endpoint is connected.
- **Outputs:** `/robot_1/semantic/mask` (`mono8`, labels 0/2), `/robot_1/semantic/points` (organized pixel-aligned `PointCloud2`), durable `/robot_1/semantic/label_info` (JSON), `/robot_1/semantic/status` (JSON), and `/robot_1/semantic/ready` (`Bool`). Empty masks are valid model results; initialization, malformed output, stale work, and inference errors must keep readiness false.

## Runtime acceptance targets

- At least 5 fresh valid mask outputs/s.
- p95 capture-to-result age ≤250 ms. The initial node reports receiver processing age from synchronized-message receipt to output; this excludes source-to-receiver transport age and must not be presented as full capture-to-result latency.
- At least 95% of emitted masks paired with the corresponding valid depth/CameraInfo bundle and projected points.
- Bounded RGB/depth/CameraInfo and pending-inference queues; report all timestamp discards and queue drops.
- Readiness remains false during model load/warm-up and until the first valid live result. After input/inference failure or a stale-result interval, readiness returns false and no stale result is republished with a new timestamp.
- Ten-minute sustained run under declared resource limits, followed by fault tests for bad model output, inference exception, restart, late frame, and input loss.

Passing the runtime transport checks does not reinstate the deferred SAM3 recognition acceptance set. The phase remains inference-only; semantic navigation is not enabled.

## DDS discovery investigation — October 16, 2026

The first runtime image omitted `ros-jazzy-rmw-cyclonedds-cpp`. Selecting Cyclone
therefore failed at ROS initialization. Switching only the inference node to
`rmw_fastrtps_cpp` allowed the model to load, but left that node using a different
discovery configuration from its same-pod bridge. The bridge uses CycloneDDS
internally, restricted by `CYCLONEDDS_URI` to loopback with multicast disabled.
Fast DDS does not consume that Cyclone configuration. The bridge received remote
camera publisher announcements and created routes, while the inference process
reported zero camera publishers and received no samples.

A controlled reproduction ran short-lived publisher/subscriber processes inside
the existing compressor container, using private ROS domains 86–89 and only the
synthetic `/semantic_dds_audit` topic. No camera or model processing participated.
Each subscriber ran for 10 seconds; the publisher ran for 14 seconds at 20 Hz.
Both processes exited successfully in every recorded case. The earlier attempt
failed to initialize ROS logging and is excluded from these results.

| Subscriber configuration | Discovered publishers (peak) | Messages received |
| --- | ---: | ---: |
| Fast DDS, default `SUBNET` discovery | 0 | 0 |
| Fast DDS, `LOCALHOST` discovery | 0 | 0 |
| Cyclone DDS, matching loopback XML | 1 | 201 |
| Fast DDS, default discovery repeated | 0 | 0 |

The publisher was CycloneDDS with the Phase 3 bridge's loopback/no-multicast XML
in every case. It sent 280 messages per run (279 in the final repeat). These
counts demonstrate discovery failure/recovery, not a loss-rate benchmark: the
publisher and subscriber observation windows differ. Package versions in this
test container were `rmw_cyclonedds_cpp` 2.2.4, CycloneDDS 0.10.5,
`rmw_fastrtps_cpp` 8.4.4, and Fast DDS 2.14.6.

The demonstrated cause is the image's missing Cyclone RMW dependency followed by
a fallback to Fast DDS that does not discover the loopback-configured Cyclone
participant in this environment. This does not establish that all Fast DDS and
Cyclone combinations are incompatible, or identify a specific RTPS packet-level
defect. The [bridge documentation](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds#usage)
recommends its tested Cyclone configuration; [ROS middleware guidance](https://docs.ros.org/en/ros2_documentation/kilted/Concepts/Intermediate/About-Different-Middleware-Vendors.html#cross-vendor-communication-among-dds-middleware)
also recommends a common RMW because cross-vendor communication is not guaranteed.

### Solution and validation

1. Install `ros-jazzy-rmw-cyclonedds-cpp` in the SAM3 runtime image and explicitly
   select `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` in the inference container.
2. Keep the bridge and node on the same ROS domain and matching loopback XML.
3. Verify the RMW library loads during image build, so a missing dependency
   fails before model startup. Preserve the corrected entrypoint (`set -eo
   pipefail`), since ROS Jazzy's setup script failed under `set -u` in the first
   image; that was a separate startup defect.
4. Require actual camera messages, a valid live mask/cloud pair, and readiness
   before starting the Phase 3 soak and fault tests.

The full-build Containerfile now installs and checks Cyclone. A pinned overlay
build adds only the middleware package and corrected entrypoint to the original
runtime, retaining the original SAM3 node/model code for the live comparison.
Build `sam3-runtime-phase3-cyclone-1` completed and passed the RMW-library check.
The inference manifest pins the new digest, selects Cyclone, and uses the fixed
entrypoint directly. On the L40S pod, all three camera topics now report one
publisher; the bridge logs discovery of the SAM3 node and all three subscriptions.
An actual RGB camera header was received, followed by valid SAM3 results.

The [30-second live smoke result](cyclone-live-smoke-20261016.json) recorded:

- 301 RGB, 301 depth, and 301 CameraInfo messages.
- 198 masks and 198 point clouds, all 198 matched by exact timestamp and frame
  (about 6.60 outputs/s); no invalid layouts or unmatched outputs.
- 120 ready=true observations and zero ready=false observations after warm-up.
- The last pair contained 5,872 mask pixels and 5,872 points in
  `camera_color_optical_frame`; both inference-pod containers had zero restarts.

This verifies the solution through the actual simulator → compressor → Zenoh →
SAM3 → ROS output path. The model, prompt, confidence threshold, SAM3 node source,
and router/bridge configuration were preserved from the original runtime for
this comparison. The middleware dependency/selection and the previously fixed
entrypoint are the changes. Work-queue replacement is intentional; cumulative
node counters include startup/model-loading frames and must not be treated as
the observer-window yield.

Phase 3 was **not passed** by this initial smoke test. At that point the ten-minute
soak, full capture-to-result age measurement (including transport), fault tests,
and backend conformance remained. The temporary three-pod stack, service, and
ConfigMap were removed after that test; the checkpoint PVC, built image, source,
and manifests remain. The canonical demo deployment was not modified.

Reproduction: source ROS Jazzy in an environment with both RMW packages, then
run [`diagnose_dds_discovery.py`](../../../../scripts/semantic-navigation/diagnose_dds_discovery.py).
Its recorded results are in [dds-discovery-results.json](dds-discovery-results.json).
After starting the isolated Phase 3 manifest and allowing model warm-up, run
[`diagnose_phase3_flow.py`](../../../../scripts/semantic-navigation/diagnose_phase3_flow.py)
inside the inference container to repeat the read-only live smoke check.

## Backend contract and organized outputs — October 16, 2026

The next candidate is `sam3-runtime:phase3-contract`, build
`sam3-runtime-phase3-contract-1`, digest
`sha256:a9db442affa6a502ea862f118ac108f6d911aebe5b7049845118926b059ee62f`.
It preserves the verified Cyclone stack and separates `Sam3ModelRunner` and
`LocalSam3Backend.predict(request)` from ROS. The backend can be imported and
called without ROS. OpenShift AI serving itself remains deferred.

The adapter now implements:

- `semantic-inference/v1` JSON serialization with lossless RGB8 input and binary
  NHW instance-mask output. Requests include robot/stream identity, UUID, capture
  sequence/header, stream epoch, policy generation, prompt/threshold, pinned
  model/preprocessing/decoder versions, and a remaining time budget. Absolute
  monotonic deadlines and retained depth stay in the client.
- Bounds of 640×480 input pixels, 64 returned instances, 28 MiB serialized
  envelopes, one retained in-flight request, one queued frame, and 20 entries
  per input subscription queue. This demo schema supports SAM3's supplied
  instance scores; they are explicitly not calibrated probabilities.
- Validation before publication: mismatched identity/version/header/dimensions,
  invalid mask values/scores, duplicates, out-of-order completion, expired
  request/depth, and invalidated epoch/policy are rejected. Timestamp rollback
  clears retained work and starts a new epoch. A backend error is not an empty
  detection. No backend fallback or navigation authority exists.
- `mono8` labels **0=unobserved, 2=avoid_target**, correcting the earlier 0/255
  smoke implementation. Reliable/transient-local `semantic/label_info` currently
  carries JSON in `std_msgs/String`, including `avoid-target/v1`, generation 1,
  active prompt, and the 0/1/2 mapping. Only 0/2 are emitted. A native plugin
  message binding, if required, belongs to Phase 4; this is not yet a plug-in
  compatibility claim.
- Full **640×480 organized XYZ clouds**, replacing the smoke build's compacted
  target-only cloud. Every pixel keeps its position; invalid/out-of-range depth
  is XYZ NaN. Masks/clouds retain the original capture header. Cloud payload is
  consequently about 3.7 MB per result and is included in live runtime testing.
- Status correlates the last valid result to its original request/header,
  versions, policy, epoch, wall completion time, queue counters, and explicit
  not-ready reason. Receipt-based timeout remains 500 ms; this is not yet a
  source-capture freshness guarantee.

### Executed contract and fault checks

All **19 local unit tests passed**, and the same tests passed in the image build.
They cover serialization/normalization, valid empty detections, error statuses,
malformed masks/scores, dimensions, identities, versions, duplicates, ordering,
deadline/depth expiry, epoch/policy changes, queue bounds, and missing checkpoint.
They also retain the guard against scoring unreviewed development labels.

The [real-model replay](contract-replay-20261016.json) used three existing Phase 2
development RGB captures: initial, oblique, and tile-negative. Actual SAM3 outputs
survived JSON round-trip and deterministic recorded-response normalization with
identical labels; altered identity/epoch/model versions were rejected. The
negative view produced a valid empty mask, not an inference error. These are
backend replay checks, **not ROS RGB-D bag replay or recognition scoring**.
The 31 pending labels and held-out recognition evaluation remain deferred.

The [live exception/delay tests](contract-faults-20261016.json) enabled a
diagnostic-only file hook in this isolated manifest. Each fault was observed
after a 1.5-second settling interval, then for three seconds: no masks appeared,
readiness stayed false with a reason, and the last-valid-result record did not
change. Removing the fault restored fresh output. The delayed request was
rejected as expired, not restamped.

The initial [missing-checkpoint test](missing-model-20261016.json), on private
ROS domain 81, produced explicit `FileNotFoundError`, no masks, and no valid-result
heartbeat. Its teardown exposed a double-shutdown exception after SIGTERM;
the follow-up candidate uses `rclpy.try_shutdown()` and catches executor shutdown.
The original evidence is retained rather than presented as a clean teardown.

### Timing gaps identified in the earlier receiver-timed build

At this stage the timer started when a synchronized triplet was formed, **after Gazebo
rendering, ROS bridging, compression, cross-node transport, and any wait in the
input synchronizer**. An old capture
delivered late can therefore receive a new local deadline. Runtime ordering and
epoch checks do not solve that age problem. Full capture-to-result p95 ≤250 ms
and ≥5 **capture-fresh** outputs/s remain unproven, even if receiver-only numbers
meet those numerical targets.

The next implementation should attach a separate capture trace at the Gazebo
sensor update/render boundary, keyed by the unchanged simulation stamp, source
epoch and sequence. Carry its wall capture time through the compressor/bridge;
measure compression, transport, queue, model, projection and publication spans
separately. Verify cross-node clock offset/uncertainty, bridge `/clock`, report
simulation age and RTF alongside wall age, and derive the client deadline from
the original capture budget. Delayed transport and paused/reset simulation must
not rejuvenate old frames. A compressor-receipt timestamp alone measures only
a partial path and cannot close the full gate.

Do not replace the ROS observation header with wall time merely to simplify
measurement. Gazebo's [RGB-D sensor implementation](https://github.com/gazebosim/gz-sensors/blob/gz-sensors8/src/RgbdCameraSensor.cc)
uses simulation update timestamps; the bridge's
[wall-time override option](https://github.com/gazebosim/ros_gz/blob/ros2/ros_gz_bridge/README.md)
changes outgoing headers rather than supplying a separate capture trace. The
proposed instrumentation preserves simulation-time TF compatibility.

The [60-second RTF sample during the soak](soak-rtf-sample-20261016.json) records
the observed variability; it is not a whole-run RTF trace or a clock-sync proof.
Phase 3 stays **HOLD** until capture timing/freshness and the remaining executed
gate evidence are complete. No Phase 4/Nav2/costmap activation is authorized by
these checks.

## Earlier receiver-timed ten-minute soak and fault checks

The [600-second live audit](contract-soak-600s-20261016.json) ran on build 1
without changing its image/configuration during the measurement, under limits
of 6 CPUs, 24 GiB RAM and one NVIDIA L40S. The source remained the isolated hotel
simulator with depth-20 compressor, private Zenoh router, and fixed `red mat`
prompt. Input remained disconnected from navigation.

| Observation | Measured result | Assessment |
| --- | ---: | --- |
| Duration | 600.0003 s | Required duration exercised |
| Masks / output rate | 4,133 / 6.888 per second | Throughput passes numerically; capture freshness not yet qualified |
| Correctly paired masks | 4,133 / 4,133 = 100% | Emitted-mask pairing target met |
| Clouds observed | 4,134 | One cloud without an observed mask; observation-window boundary is a plausible explanation, not proven |
| Malformed / duplicate / out-of-order outputs | 0 / 0 / 0 | Auditor checks passed |
| Observer RGB-receipt-to-mask p95 / max | 220.21 / 234.35 ms | 4,131 samples; not capture age |
| Status-sampled triplet-to-publication p95 / max | 219.04 / 233.27 ms | 2,255 sampled results; not capture age or every output |
| Runtime RSS, first → last | 2,011.875 → 2,017.875 MiB | +6 MiB over ten minutes; no runaway growth observed, not a proof against long-duration leaks |
| Work queue / largest sampled input queue | 1 / 7 | Within configured bounds of 1 / 20 |
| Input-queue drops | 0 | No input-queue overflow recorded |
| Ready=false status observations | 4 of 2,400 | Four brief availability interruptions; not hidden as continuous readiness |
| Unexpected container restarts during soak | 0 | Later restarts were deliberate fault tests |

The additional cloud and the two mask observations without a preceding RGB
observation are retained in the report, not silently removed from counts.
Camera input was 5,999 RGB messages. Deliberate latest-frame work replacement
means raw-camera-to-mask yield is **not** the emitted-mask/cloud pairing metric.
The collector initially recorded a null status because ready/status are separate
topics; subsequent samples and the final status provide counters and identity.
The collector now waits for both ready and a ready status before new runs.

[Result-log analysis](soak-result-gaps-20261016.json), bracketed by emitted
counters 432–4565, found **16 publication gaps above 500 ms**, maximum
**714.05 ms**, with no inference errors in that range. The four observed
ready=false intervals lasted approximately 0.25 seconds each at the auditor's
status cadence. Processing durations for results following the gaps were
111–118 ms. That points toward input delivery/scheduling gaps rather than slow
model execution, but does not identify which upstream stage caused them.
Source/transport/synchronizer timing is needed before assigning a root cause
or claiming continuously fresh availability. The 60-second Gazebo sample had
566 RTF observations, mean 0.996, range 0.625–1.823; it is consistent with bursty
progress but does not prove causality.

[Router disconnection](router-disconnection-20261016.json) was tested by deleting
and recreating **only** `semantic-phase3-router`. After settling, a three-second
outage observation saw no masks, `stale_input_or_result`, and an unchanged valid
heartbeat. New data restored readiness. The old router took about its grace
period to terminate; a 30-second delete wait timed out, and disappearance was
then verified before the replacement was observed running. The canonical
router was never touched.

Build 2 fixes the SIGTERM/double-shutdown issue. Its
[missing-model rerun](shutdown-fixed-missing-model-20261016.json) again emitted
no masks or heartbeat, and this time exited **0 without a traceback**. Its
[30-second organized-output smoke](shutdown-fixed-smoke-20261016.json) received
217 masks and 216 matching clouds (99.54%, one mask pending at the observation
boundary), with no invalid/duplicate/out-of-order outputs or ready=false samples.

A separate **SIGTERM process-restart test** on build 2 then observed a clean
container exit 0 and a new stream epoch. The
[restart audit](process-restart-20261016.json) captured the transitions
`loading → awaiting_first_valid_result → ready`, followed by 105 masks and 105
matched clouds in 15 seconds, with no invalid/duplicate/out-of-order output.
This is readiness recovery only; no motion or task automatically resumed.
The [exception/delay suite also passed again on build 2](shutdown-fixed-faults-20261016.json),
with no masks or heartbeat refresh during either fault and recovery afterward.
The [recorded deployment identity](verified-runtime-identity-20261016.json)
distinguishes the image-update restart from the subsequent process restart.

### Earlier gate disposition, before capture instrumentation

- **Verified:** local backend separation, deterministic and real-result wire
  checks, policy labels/metadata, organized output layouts, bounded queues,
  ten-minute numerical throughput/pairing, no runaway memory in that interval,
  inference exception/delay handling, input disconnection, missing model, and
  process restart. Replay used three RGB captures; no recognition gate was scored.
- **HOLD:** source-capture wall/simulation timing and corresponding stale-input
  rejection; locate the intermittent delivery gaps using that instrumentation.
  Repeat the ten-minute measurement and delayed-transport/pause/reset tests on
  the final fully instrumented image before signing off capture freshness and
  latency. Preserve current thresholds; no timing waiver was requested.
- **Deferred unchanged:** development label review, held-out recognition scoring,
  OpenShift AI serving, Nav2/costmap connection, motion authority and RMF integration.

Reproduction scripts: `audit_phase3_runtime.py`, `verify_phase3_backend.py`,
`verify_phase3_faults.py`, `verify_phase3_missing_model.py`,
`verify_phase3_connection.py`, and `audit_phase3_sim_timing.py` under
`scripts/semantic-navigation/`. Model replay requires the selected RGB files
inside the inference container and `PYTHONPATH=/opt/semantic-perception`.
The connection test requires explicit external interruption/restoration of the
private router; the diagnostic file hook is enabled only in the isolated manifest.

**Earlier cleanup verified:** the three temporary Phase 3 pods, private router Service,
and diagnostic ConfigMap were deleted. They can be recreated from the pinned
manifest. Both built images and the checkpoint PVC were retained. The canonical
simulator, camera probe, and Zenoh router deployments remained available at 1/1;
no Nav2, costmap, RMF, serving endpoint, or robot-command configuration changed.

## Capture-origin investigation and native compression — October 16, 2026

The follow-up adds an opt-in trace immediately before the actual RGB-D sensor
`Render()` call, with render completion and source-publication timestamps.
The patch targets Gazebo Sensors 8.2.2 commit
`9348f9fe8a11b9d50381819f51e17e136aedab8a`, matching the installed sensor library.
Original image pixels, simulation timestamps and frame IDs remain unchanged.
The [pinned sensor source](https://github.com/gazebosim/gz-sensors/blob/gz-sensors8_8.2.2/src/RgbdCameraSensor.cc)
establishes the measurement boundary: render start, not compressor or receiver
arrival. This does not measure scene-update work preceding render start.

The trace travels with a source epoch/sequence and unchanged simulation stamp.
The adapter also receives `/clock`, source/compression timing records, and
publishes one timing record per valid mask/cloud result. A 500 ms deadline is
derived from original capture age, not renewed on transport arrival. Missing
trace/clock, old epochs and expired captures cannot authorize a valid output.
Wall/steady-clock discontinuities are rejected. Cross-node measurement uses a
conservative 2 ms uncertainty allowance, based on
[read-only chrony checks](capture-clock-check-before-20261016.json); this is a
bounded diagnostic assumption, not continuous clock-health monitoring.

### Source delivery bottleneck established

The raw ROS/DDS compressor socket accumulated **193,463 receive-buffer drops**,
matching the pod's UDP `RcvbufErrors`/`InErrors`; other inspected sockets had no
drops. The host's `net.core.rmem_max` and `rmem_default` were both **212,992 bytes**.
No host sysctl was changed. See the
[socket/host evidence](source-dds-receive-buffer-drops-20261016.json).
Cyclone's [large-sample guidance](https://cyclonedds.io/content/faq)
explains why insufficient UDP receive buffers can cause loss/retransmission.
The observed counters, timing spans and controlled bypass support this diagnosis;
the model is not the source of these raw-input delivery delays.

A separate [60-second source audit](source-dds-timing-60s-20261016.json)
matched 597 capture/compression traces: capture-to-compression p95 **382.34 ms**,
raw pair-wait p95 **303.04 ms**, rendering p95 **64.92 ms**, compression p95
**8.43 ms**. The full-path measured baseline subsequently failed the 250 ms gate:

| 60-second configuration | Outputs/s | Full capture age p95 | Outputs ≤250 ms/s | Emitted mask/cloud pairs |
| --- | ---: | ---: | ---: | ---: |
| Instrumented raw ROS/DDS input | 6.05 | 409.16 ms | 2.18 | 363/363 |
| Direct Gazebo input, existing work queue | 8.30 | 285.03 ms | 5.12 | 498/498 |

Evidence: [DDS baseline](capture-timing-dds-baseline-60s-20261016.json),
[native input](capture-timing-native-60s-20261016.json). These figures include
the 2 ms uncertainty allowance and the publication of both organized cloud and
mask. Every emitted result is included; old or intentionally skipped inputs
are not relabeled as successful outputs. Both runs still **fail p95 ≤250 ms**.

### Isolated native-input candidate

`SEMANTIC_RAW_INPUT=gz` subscribes directly to Gazebo Transport's RGB/depth
images in the private partition, then uses the existing pairer and JPEG/PNG
codecs. Small compressed ROS messages continue over the existing Zenoh path;
CameraInfo and simulation headers are preserved. This avoids fragmenting the
large raw images through DDS without requiring node-wide network tuning.
The default compressor input remains `ros`; the canonical deployment is unchanged.

[Same-capture equivalence](native-codec-equivalence-20261016.json) compared ten
RGB and ten depth outputs against a temporary ROS-input compressor whose output
topics were remapped. Exact capture stamps, optical frames, formats, lengths and
SHA-256 hashes matched in all twenty comparisons. This validates codec/header
equivalence for those samples, not general recognition or moving-scene accuracy.
The mirror process was terminated after the check. Native compressor sockets
still had [zero receive drops](native-source-udp-after-codec-test-20261016.json);
the pod-wide count includes the temporary large-message ROS mirror and must not
be attributed to the native PID 1 sockets.

Native source pair-wait p95 fell to **1.03 ms**, compression p95 **7.06 ms** and
compressed-to-receiver RGB p95 **2.82 ms**. The remaining delay is principally
waiting behind inference: the model takes about 107–111 ms at a 100 ms camera
period. A candidate admission policy therefore limits work-queue wait to
**40 ms**, explicitly counting discarded waiting frames. It does not change
the camera/model resolution, prompt, confidence, capture timestamps, 500 ms
expiry, or acceptance thresholds. Its sustained rate/latency and source faults
must be verified before this candidate is qualified.

### Queue admission and fault-test findings

The [60-second bounded-queue trial](capture-timing-bounded-build3-60s-20261016.json)
used timing build 3, digest `cfea07bbf9be6fc5c03fd3b71b8d4d1ef477b9a0581ed7a8219aa857a9dc7071`.
It emitted 411 paired outputs (**6.85/s**), all within 250 ms; full p95 was
**227.24 ms**, maximum **241.62 ms**. There were no >500 ms publication gaps
(maximum 211.09 ms). During the status window, 600 triplets were paired and
189 waiting frames were deliberately skipped. No unbounded queue is introduced.
This is a short trial, not a substitute for the final ten-minute qualification.

Timing build 4 additionally expires readiness at the existing original-capture
deadline, not 500 ms after publication. Its
[world-pause test](capture-world-pause-build4-20261016.json) passed: not-ready
was observed at 512.51 ms capture age (500 ms deadline plus status/observer delay),
then no output or heartbeat change for three seconds; resuming the private
world restored fresh output. Navigation was never connected.

Reset testing found a separate race. One reset passed, while a
[repeat failed](capture-world-reset-build4-repeat-20261016.json): an old capture
with stamp 113.1 s was published after the local simulation clock reached zero,
giving **−113,100 ms simulation age**, despite wall age of only 301.50 ms.
The callback stored `/clock` updates but did not invalidate work until a later
camera header/source epoch arrived. An in-flight inference could finish in that
gap. The fix immediately changes the adapter epoch and clears retained work on
clock rollback, and checks nonnegative/bounded simulation age again under the
publication lock. Dedicated callback regression tests cover rollback before any
new camera message and preservation of identity on a normal advancing clock.
The failed and passing pre-fix trials are retained; the passing trial alone
cannot qualify this race.

The missing-model test correctly produced 117 not-ready status observations,
zero masks and no heartbeat, but teardown exposed a SIGTERM race in Jazzy's
executor wait-set initialization (`RCLError`, invalid context). The shutdown
handler now suppresses that exception **only after ROS context shutdown**;
errors while the context remains live still propagate. This needs a fresh
missing-model/restart check on the final image.

An attempted `SIGSTOP`-based compressor outage was **inconclusive**: PID 1
remained running and the observer timed out waiting for the intended fault.
No pass is claimed. The private compressor candidate instead provides an
explicit opt-in, tokenized, at-most-ten-second delivery-delay hook. The observer
must witness expired source captures arriving, verify that none becomes an
output, and verify not-ready/unchanged heartbeat and fresh recovery. The hook
does not alter capture timestamps and is absent from the canonical manifest.

### Final-image regression checks

Timing build 7 passed [27 transport/contract tests and two actual ROS callback
tests](capture-runtime-build7-tests-20261016.txt). An additional
[installed-adapter barrier test](capture-runtime-reset-barrier-20261016.txt)
rejects a pre-reset wall capture even when its simulation stamp fits the new
timeline, and accepts a genuinely post-reset capture with that same stamp.
The local macOS system Python lacks NumPy, so its full unit invocation was not
usable; the successful suites ran in the built ROS runtime, not that interpreter.

The final runtime and native compressor build 2 passed:

| Fault/check | Executed result |
| --- | --- |
| Real simulation resets | Three consecutive passes; 37, 37 and 36 post-reset outputs checked, no invalid simulation age or old-epoch output after the observed reset transition |
| World pause | Not-ready at 511.37 ms capture age; three seconds with no output or heartbeat refresh; fresh recovery |
| Eight-second camera delivery delay | 83 expired captures observed arriving (oldest 8,074.67 ms); none emitted; not-ready at 522.88 ms; fresh recovery |
| Inference exception and delayed backend response | No output/heartbeat refresh during each three-second quiescent check; recovery after removing the fault |
| Missing checkpoint | Three passes; explicit not-ready, zero masks, no heartbeat, clean exit 0 on SIGTERM |
| Process restart | Prior process exited 0; runtime reloaded/warmed and resumed paired valid outputs, without any motion authority |
| Native codec/header equivalence | Ten RGB and ten depth samples still byte/header-identical to the ROS-input mirror |

Evidence: resets [1](capture-world-reset-final-1-20261016.json),
[2](capture-world-reset-final-2-20261016.json),
[3](capture-world-reset-final-3-20261016.json);
[pause](capture-world-pause-final-20261016.json);
[delivery delay](capture-compressor-delay-final-20261016.json);
[inference faults](capture-runtime-inference-faults-20261016.json);
[missing model](capture-runtime-missing-model-final-20261016.json) and
[two repeats](capture-runtime-missing-model-repeats-20261016.json);
[restart](capture-runtime-restart-20261016.json);
[codec equivalence](native-codec-equivalence-build2-20261016.json).
The [deployment identity](capture-runtime-final-identity-20261016.json) records
image digests, resource limits and the successful termination/restart.
Shutdown of an in-flight inference logged its intentional invalidation and a
nonfatal rosout-context warning; no Python traceback or nonzero exit occurred.

These are runtime/transport checks, not recognition scoring or proof of every
possible reset/network ordering. The canonical simulator and robot-control
configuration were not changed. Runtime readiness can recover with fresh
results; this is not permission for automatic robot-motion resume.

### Ten-minute publisher qualification and receiver-delivery gap

The [first capture-timed 600-second run](capture-timing-final-600s-20261016.json)
used final image build 7 with the default DDS receiver profile. It produced
**3,974 masks and 3,974 matched valid clouds** (**6.623/s**), with publisher
capture-age p95 **228.07 ms**, maximum **290.56 ms**. Of those, 3,964 outputs
were within 250 ms (**6.607/s**). There were no invalid layouts, duplicate result
identities, out-of-order timed results, capture-age errors, not-ready transitions
or publication gaps >500 ms; the maximum publication gap was **276.03 ms**.
Input/paired-triplet counters advanced by 6,000, while 2,014 waiting frames and
12 replaced pending frames were deliberately skipped. The 66.23% processed
fraction is an admission choice, not raw camera loss. Runtime RSS increased
by about 4.02 MiB across 61 samples; measured queues remained bounded.

However, the observer's **paired validation-completion age p95 was 326.83 ms**
(maximum 411.56 ms). Publication performance alone therefore does not qualify
low-latency delivery to a consumer. This original observer timestamp is taken
after structural/numeric validation; later audits report callback arrival and
validation completion separately instead of silently redefining that metric.

A [thin receiver audit](output-delivery-thin-30s-20261016.json), without the
per-frame validation loops, still measured point-cloud arrival p95 **311.66 ms**
versus mask arrival **224.94 ms**. Its own UDP socket accumulated **6,504**
additional receive-buffer drops in 30 seconds, exactly matching the pod-wide
error-counter increase. Thus expensive validation alone does not explain the
delay. The [read-only GPU-node check](capture-clock-check-between-soaks-20261016.json)
also found a 212,992-byte receive-buffer limit. No host network setting changed.

Installed CycloneDDS is `0.10.5-1noble.20260225.142613`, with RMW
`2.2.4-1noble.20260911.095700`. Its [version-pinned schema](https://github.com/eclipse-cyclonedds/cyclonedds/blob/0.10.5/etc/cyclonedds.xsd)
documents a default `Internal/NackDelay` of 100 ms. Setting **1 ms only in the
receiver** preserves discovery, reliability, payloads and headers, while
requesting missing data sooner. The [controlled thin-receiver test](output-delivery-nack1ms-30s-20261016.json)
reduced cloud arrival p95 to **236.65 ms**. Receive drops still occurred
(5,458 additional drops); this is faster recovery, not elimination of loss.
It is a scoped demo configuration, not a general network-tuning recommendation.

The [full-validator 60-second follow-up](capture-timing-nack1ms-60s-20261016.json)
then measured p95 **227.88 ms at publication**, **235.83 ms at paired callback
arrival**, and **243.07 ms after validation**, at approximately **6.7 pairs/s**.
All 402 received masks/clouds paired; 401 timing records fell inside the
observation window. Such boundary differences are reported, not counted as
successful timing observations. The same receiver profile must pass a new
ten-minute run before end-to-end qualification.

The first run's full source trace gives a simulation/wall-time ratio of
**1.0000007**. A parallel Gazebo stats process reported mean RTF **0.99480**, range
**0.58693–2.33232**. Its tool output truncated the middle of the sample array;
only the [header/aggregate summary](capture-soak-rtf-summary-20261016.json) and
[explicitly truncated raw output](capture-soak-rtf-truncated-20261016.txt) are
retained. The revised RTF auditor writes full samples to a file for subsequent
runs, avoiding that output-size limitation. Full capture-timing evidence was
retrieved directly as a file and is not truncated.

### Reproducing the receiver-qualified profile

Use the pinned `phase3-native-bounded-diagnostic.yaml` manifest in the existing
isolated namespace. Its node selectors, model PVC and clock allowance describe
the tested cluster, not a portable hardware guarantee. Do not replace the
canonical deployment or connect command/costmap topics as part of this test.

After model readiness, run the observer with the **consumer** DDS profile:

```sh
oc exec -i -n semantic-navigation semantic-phase3-inference -c sam3-inference -- \
  bash -lc 'source /opt/ros/jazzy/setup.bash; export CYCLONEDDS_URI=file:///phase3-config/cyclonedds-consumer.xml; exec /opt/sam3-venv/bin/python - --duration 600 --progress --output /tmp/my-phase3-capture-audit.json' \
  < scripts/semantic-navigation/audit_phase3_capture_timing.py
```

The output file must not already exist. Retrieve it with `oc cp` before deleting
the temporary pod. `receiver_cyclonedds_uri` and `receiver_cyclonedds_sha256` in
the report identify the actual consumer configuration. Run
`audit_phase3_sim_timing.py --duration 600 --output /tmp/my-phase3-rtf.json` in the
simulator container in parallel, then retrieve that file too. Verify host clock
health and retain the uncertainty assumption with each scored run.

Fault tests are separate from the nominal soak. The source-fault observer prints
`audit_ready` before external intervention. Only control the private
`semantic_phase3_inference` world; always restore pause/temporary faults. The
camera-delay injector removes its own trigger in `finally`. A direct PID-1
`SIGSTOP` is not a valid fault injection here. The final image source files
match the workspace [by SHA-256](capture-runtime-source-hashes-20261016.json).

Any later Nav2/costmap consumer must explicitly retain/requalify the relevant
receiver settings and independently reject stale captures. An observer's
delivery result is not proof that an actual costmap meets its 300 ms phase-4
budget. The ROS-independent backend contract remains unchanged; OpenShift AI
serving is still a separate proposal requiring its own performance qualification.

## Final end-to-end qualification — PASS, review approved

The [final 600.002-second run](capture-timing-consumer-final-600s-20261016.json)
kept build 7, native compressor build 2, 640×480 RGB-D, the fixed `red mat`
prompt/0.5 threshold, 40 ms admission bound, and declared container quotas
unchanged. Only the consumer uses the qualified 1 ms NACK profile, SHA-256
`56e4016d05028b6b0b6ad2ac506ebdb00a1cbefb738afee578afd1a225fc0b8d`.
All ages below include the 2 ms clock allowance.

| Boundary/check | Final measurement | Assessment |
| --- | ---: | --- |
| Valid output rate | 4,092 pairs; 6.820/s | Above 5/s |
| Capture → both publications | p95 231.36 ms; max 286.33 ms | Pass |
| Capture → paired callback arrival | p95 236.79 ms; max 293.42 ms | Pass |
| Capture → completed pair validation | p95 243.93 ms; max 301.87 ms | Pass at the stricter measured boundary |
| Pairs validated within 250 ms | 4,041; 6.735/s | Above 5/s even with this stricter freshness interpretation |
| Emitted mask/cloud matching | 4,092/4,092, 100% | Above 95% |
| Invalid layout/class, duplicate identity, order/age errors | Zero | Pass |
| Readiness interruptions / gaps >500 ms | Zero / zero; max publication gap 271.01 ms | Pass |
| Simulation capture age | p95 220 ms; max 280 ms | Valid, unchanged simulation headers |

The 250 ms criterion is a **p95**, not a maximum-latency guarantee. No Nav2
consumer or costmap processing is included. Phase 4 must measure that additional
work and enforce its own lifecycle/freshness checks.

Source and compression traces each counted 6,000 frames. Status counters recorded
1,902 queue-wait rejections and seven pending-frame replacements, with no new
input queue drops or timestamp discards. Pending work at the window boundary
accounts for a one-frame counter-balance difference. Deliberate inference
skipping remains explicit; it is not labeled as transport loss. Sampled input
and work queue depths never exceeded one; configured caps remain 20 and one.
Source compressor UDP socket drops remained zero and pod receive-error counters
did not increase between [before](native-source-udp-soak-before-20261016.json)
and [after](native-source-udp-soak-after-20261016.json) snapshots. This does not
claim that the separate output receiver has zero packet loss; it recovers it
with the documented profile.

Runtime RSS rose from **2,089.50 to 2,128.38 MiB** (+38.88 MiB), chiefly during
the first 90 seconds, then varied by only 2.25 MiB through the remainder. Queues
are bounded and no runaway growth was observed in the tested interval; this is
not proof of indefinite leak-free operation. [GPU samples](capture-soak-gpu-samples-20261016.json)
stayed at **5,855 MiB**. The limits were 6 CPU cores, 24 GiB RAM and one L40S for
inference; exact source/compressor/router limits are in the identity artifact.

The complete [parallel Gazebo RTF evidence](capture-consumer-soak-rtf-600s-20261016.json)
contains 5,666 received statistics samples: mean **0.99322**, range
**0.58338–2.51151**. The full-run capture simulation/wall ratio was **1.0000002**;
the simulator was not slowed to improve wall-latency results. The
[before/between](capture-clock-check-between-soaks-20261016.json) and
[after](capture-clock-check-final-after-20261016.json) chrony snapshots report
normal synchronization and support the 2 ms allowance. These snapshots and
per-capture wall/steady consistency checks are not continuous clock-fault
monitoring or a safety certification.

**Disposition:** the Phase 3 technical gates pass for this pinned, isolated
source/runtime/consumer profile, including the executed fault regressions above.
The user approved this review on October 16, 2026 ("Review approved."), completing
the Phase 3 reviewer gate. The user subsequently requested Phase 4 implementation;
its isolated costmap work is tracked in the [Phase 4 report](../phase-4/runtime-report.md).
Neither approval connects the active hotel navigation or authorizes Phase 5 motion.
Deferred recognition labels/held-out scoring remain deferred and unqualified.
OpenShift AI serving, Nav2/costmaps, robot motion and RMF integration remain out
of this executed scope. No navigation benefit is claimed yet.

**Final cleanup verified:** the three private Phase 3 pods, router Service and
diagnostic ConfigMap were removed after retrieving the complete evidence. They
can be recreated from the pinned manifest. Candidate images and the checkpoint
PVC were retained; the PVC is Bound and all three canonical deployments remain
available at 1/1. [Cleanup readout](capture-final-cleanup-20261016.json).
No host sysctl, canonical navigation configuration or robot-command route was
changed. Changes are local/uncommitted; no commit or push was requested in this turn.
