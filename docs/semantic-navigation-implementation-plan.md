# Semantic navigation implementation plan

Date: October 22, 2026. Status: **Phases 0 and 1 complete; Phase 2 passed with a user-approved demo waiver for deferred recognition review/held-out scoring; Phases 3 and 4 complete and review approved by the user on October 16, 2026; Phase 5 complete — all four moving gates passed and the evidence review was approved by the user on October 26, 2026 with recorded caveats (footprint-geometry correction, private-profile deviations including the watchdog UDP companion path, single-floor scope, the standing Phase 2 recognition waiver, and twelve retained failed matrix series); Phase 6 is unlocked and its qualification gates are HOLD until run; a separate, narrowly scoped Phase 6D demo track is user-approved. D0 static profile preflight, D1 stationary perception-to-costmap smoke, and D2 fixed-scene paired navigation are DEMO PASS. D2 completed three off/on pairs after resolving the isolated command route, stale camera/clock routes, CPU contention, and Nav2 startup-order failures. The October 22 Phase 5 non-actuating preflight passed 169 unit tests and its native/plugin fixtures but did not qualify motion or close any Phase 5 acceptance gate; on October 23 the recovery-repeatability subgate passed 10/10, the moving fault-stop subgate passed its 10/10 fault matrix, and on October 26 the moving SAM3 observation subgate passed its 10/10 series (100% capture-time registration, ~7 results/s) and the armed semantic fault matrix passed its 10/10 series (five fault classes, mode-qualified first reasons, zero within 0.3–2.6 ms of the 500 ms freshness trigger, observed late successes with no motion resume) on the guarded GPU fixture.** The pinned SAM3 checkpoint/runtime and hotel-scene recognition remain unqualified for general use. D2 demonstrates a staged semantic-cost route choice only; it does not qualify safety or robot-footprint clearance beyond the Phase 5 evidence, change the canonical hotel deployment, or authorize physical-robot use.

## Decision and scope

Implement **SAM3 first**, using a pretrained model and one fixed text prompt to avoid starting with a custom training project. Retain a fixed-category ONNX model as an alternative implementation behind the same sensor, policy, and costmap interfaces. ONNX training is not a prerequisite for the SAM3 path.

The first deliverable is a single robot on one hotel floor, navigating around a recognizable surface that it would otherwise cross. Keep NavFn and Regulated Pure Pursuit (RPP), with the same settings in both comparison arms. Defer NeuPAN, lift transitions, runtime prompt changes, and fleet-copilot integration until the basic semantic demonstration is verified.

Make the inference boundary compatible with later OpenShift AI Model Serving **during this implementation**, but defer the serving deployment itself. Phases 0–6 require a versioned backend contract and conformance tests, not OpenShift AI operators, KServe resources, or a remote endpoint. The [separate OpenShift AI serving proposal](semantic-navigation-openshift-ai-serving-proposal.md) defines that later migration and its acceptance gates.

This plan supersedes the ONNX-first sequence in the October 12 research. The [source audit and broader Nav2 proposal](nav2-ai-demo-implementation-proposal.md) remain the reference for plugin internals, robot geometry, and the separate learned-controller experiment.

## Demonstration and implementation options

Use a visually distinctive floor mat in a spacious L1 area, with a clear route around it. Start with a candidate prompt such as `floor mat`; choose the final wording through the recognition tests. Do not assume that `restricted surface` describes a visual category a pretrained model can recognize. The model detects the mat; our policy assigns its navigation cost.

Both runs use identical geometry, map, start, goal, and perception workload. Without semantic costs, the robot should cross the mat. With semantic costs, it should detour. The evaluator knows the mat's ground-truth footprint, but that annotation must not become a navigation input. A target already blocked by the map or LiDAR would not demonstrate added semantic value.

| Choice | SAM3 first | Fixed-category ONNX alternative |
|---|---|---|
| Recognition | Pretrained text-prompted segmentation; hotel-scene accuracy must be tested | Select a suitable pretrained model first; train/fine-tune only if necessary and separately approved |
| Runtime | Accelerator-backed process, isolated from Nav2 | Start with ONNX Runtime CPU; measure actual performance |
| Principal risk | Hardware compatibility, latency, and recognition of rendered hotel scenes | Finding a checkpoint with the required indoor category |
| Reused work | Camera, depth registration, policy adapter, semantic layer, watchdog, and evaluation | All of the same integration and acceptance tests |
| Later benefit | Runtime category changes without retraining, if validated | Potentially smaller, simpler runtime for a fixed demonstration |

The official ONNX example supplies an outdoor sidewalk/grass/background model, not an indoor mat detector. It is useful as an isolated reference, not a ready-made fallback for the hotel task. [Nav2 ONNX tutorial](https://docs.nav2.org/jazzy/tutorials/general_tutorials/navigation2_with_semantic_segmentation/navigation2_with_semantic_segmentation/).

### SAM3 hardware choice

Choose the implementation only after verifying the available node:

- **Compatible AMD hardware:** evaluate the Open Navigation ROS integration and its ROCm/MIGraphX build process. Pin its dependencies and semantic-layer revision. [Reference setup](https://github.com/open-navigation/opennav_amd_semantic_navigation/blob/5e82f4a458f9e97ddd92e2cf10feb2c3552295d3/opennav_sam3_setup/README.md).
- **Compatible NVIDIA hardware:** evaluate Meta's SAM3 image-inference API, initially with a small ROS adapter and detection on each selected frame. This is proposed adapter work, not a claim that the AMD package is CUDA-portable. Meta documents Python 3.12+, PyTorch 2.7+, and CUDA-compatible hardware/software requirements. [Meta installation and image API](https://github.com/facebookresearch/sam3#installation).
- **No suitable accelerator:** hold the live SAM3 path. Offline feasibility results alone do not authorize navigation. Decide whether to provision hardware or evaluate ONNX; do not silently switch the selected approach.

Start with original SAM3, not an unqualified mix of SAM3 and SAM3.1 checkpoints or exports. The upstream repository contains both versions; pin the model and compatible code explicitly. Measure memory demand instead of promising a GPU size from model parameter count. The approved account downloaded the original SAM3 checkpoint at pinned revision `3c879f39826c281e95690f02c7821c4de09afae7`; Phase 0 runtime execution passed, while category recognition remains unqualified. [Upstream version and access guidance](https://github.com/facebookresearch/sam3).

## Shared architecture

Keep inference in a separate process/container on a suitable accelerator node, not inside `controller_server`. Use a dedicated inference workload when the GPU is on a different node from Gazebo; use a sidecar only if placement and resource isolation make sense. Nav2 stays in `robot-nav-robot-1`. The ROS adapter retains synchronized sensor data, calls a replaceable inference backend, and converts its masks into policy labels. Those labels and the retained registered cloud feed the semantic layer.

Separate the model runner from ROS subscriptions, TF, navigation policy, and cost assignment. The runner owns model-specific preprocessing, inference, and mask decoding; it must be callable without ROS or Nav2 installed. The ROS adapter owns timestamps, depth pairing, result validation, label normalization, and health reporting. Keep KServe-specific transport and authentication out of the costmap and controller code. This allows a future server to reuse the qualified model runner while the robot-side interfaces remain unchanged.

For initial CUDA inference, a stateless image API avoids tracker state while establishing correctness. The AMD implementation may use its existing detector/tracker pipeline, but that mode must be recorded and tested. Introducing tracking later is an explicit change requiring perception and latency revalidation.

The adapters normalize model-specific outputs into these proposed contracts. Topic names are relative to the robot namespace; actual bridge mappings must be verified in the deployed configuration.

| Interface | Contract |
|---|---|
| `camera/color/image_raw`, `camera/color/camera_info` | RGB and calibration with sensor capture timestamp and optical frame |
| `camera/depth/points` | Organized, pixel-aligned XYZ cloud; preserve invalid points rather than changing pixel order |
| `semantic/mask` | `mono8` IDs at cloud resolution; nearest-neighbor label resizing only |
| `semantic/label_info` | Reliable/transient-local mapping: 0 `unobserved`, 1 `traversable` when explicitly detected, 2 `avoid_target` |
| `semantic/confidence` | Optional, with documented meaning; missing confidence is not a calibrated score of 1 |
| `semantic/overlay` | Debug visualization, never the costmap input |
| `semantic/status` | Proposed status message containing readiness, model/policy version, capture/result times, active prompt, dropped frames, and failure reason |

For one target prompt, publish IDs 0 and 2; do not label all other pixels as floor. Map SAM3 instance masks into the stable `avoid_target` class. ONNX class IDs must undergo the same normalization. Reject unmapped labels. Keep the original capture header on masks and correlate the status record to it; never restamp an old result as fresh.

The Phase 4 candidate also requires `mask_sha256` and `cloud_sha256` in the
per-result `semantic/timing` JSON record, binding the exact ROS payloads to their
capture/identity metadata. This is adapter-side transport integrity, not a
change to the inference backend API: future OpenShift AI serving still returns
recognition results only, and the robot-side adapter retains the original cloud.

The semantic plugin consumes aligned masks/clouds and label metadata; inference remains external. Its optional-confidence behavior and clearing risks require tests below. [Layer interface](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/README.md), [implementation](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/src/semantic_segmentation_layer.cpp).

That upstream layer remains a reference, not the currently selected executable.
Phase 4 implements `demo_semantic_costmap::SemanticLayer` in this repository for
the existing JSON metadata and fixed policy. It has no confidence accumulation
or runtime ontology changes. Its conservative maximum merge leaves geometric
unknown cells unknown as well as preserving occupied cells. This narrower
implementation carries local maintenance responsibility and must pass the same
projection/lifecycle gates; it is not a claim of upstream plugin qualification.

Apply semantics to global and local costmaps before inflation, merging with maximum cost so labels cannot erase geometric obstacles. Start with an explicitly selected soft cost of 200 for the target. Evaluate lethal cost 254 as a separate exclusion experiment. Unobserved pixels add no semantic assertion. A model-only restriction is not a production safety boundary.

Preserve geometric collision handling and introduce an independently verified final-command watchdog. When a task requires semantics and perception becomes stale, stop and report the task as paused/failed; geometry-only completion must not be reported as semantic success.

### Inference backend compatibility contract

Define a transport-independent `predict(request) -> response` contract now. Initially implement the selected SAM3 backend; the ONNX branch uses the same envelope. Reserve a remote backend for the later proposal without implementing its endpoint in phases 0–6. Backend selection is explicit configuration, not an automatic runtime fallback. Here, a local backend means a directly managed inference workload; it need not run onboard the robot.

| Contract area | Required behavior |
|---|---|
| Request identity | Schema version, unique request ID, robot/stream ID, capture sequence, stream epoch, and policy generation. Start a new epoch after a clock reset or sensor/adapter restart so old results cannot match new captures |
| Image and prompt | Original image dimensions, encoding/color order, image payload, and approved prompt/category specification. Version preprocessing and output decoding with the pinned model artifact; do not depend on mutable global prompt state |
| Time budget | Preserve the original ROS capture timestamp and optical frame. Track a client-side monotonic deadline and pass the remaining budget to the backend. Do not compare monotonic timestamps from different hosts |
| Successful result | Echo request identity and policy generation; report actual model artifact and preprocessing/decoder versions. Return typed instance/category masks in original image coordinates with declared dimensions and lossless mask encoding. Scores are optional and must declare their meaning |
| Failure result | Distinguish a valid empty detection from not-ready, timeout, invalid input, overload, and inference failure. Errors must not become an all-zero mask that looks like a successful observation |
| Resource limits | Bound request size, in-flight requests, and retained RGB/cloud pairs. Prefer recent frames; discard expired work instead of accumulating a retry backlog |

The adapter is authoritative for the original ROS header and corresponding depth/cloud; the inference service does not need the cloud, TF, or costmap. Validate returned identity, versions, dimensions, mask values, and deadline before publication. Reject duplicates, results older than the last accepted capture, wrong epochs/policy generations, and results whose matching cloud has expired. Status diagnostics may describe rejected requests, but must not advance the last-valid-observation heartbeat. Never use a new cloud or timestamp to rescue an old result.

Normalize masks to the existing `semantic/*` ROS interfaces only after validation. Keep navigation costs and task authority on the robot side: an inference backend returns recognition results, not movement commands or permission to resume. Record inference, queue, transport, and end-to-end timing separately, with the end-to-end deadline measured at the adapter.

Use stateless, per-image inference as the portable baseline. If the initial AMD path uses tracking, isolate it as an explicit backend capability; migrating that mode will require session isolation, replica routing, and reset semantics. A stateless deployment must not silently replace a qualified tracker without repeating recognition and live-navigation gates.

## Phase verification rules

Each phase requires a stored report with `PASS`, `FAIL`, or `HOLD`, the exact inputs/configuration, raw evidence, measured values, and reviewer sign-off. **Do not activate the next phase until all mandatory checks pass.** Current execution status is recorded under `docs/validation/semantic-navigation/`; a documented test is not an executed test.

The user-approved demo-only track below is an explicit, limited exception to the
normal Phase 5/6 entry gates. Its result must be recorded as **DEMO PASS** or
**DEMO HOLD**, never as a Phase 5 or full Phase 6 qualification pass. It does
not unlock Phases 7 or 8 or remove any full-qualification requirement.

Keep evidence under the proposed `docs/validation/semantic-navigation/phase-N/` directory. Store large bags, models, and videos in artifact storage with checksums and links, not directly in Git. Every report identifies source commits, image digests, model hashes, hardware, prompts, parameters, and simulation seeds.

Thresholds below are initial engineering acceptance targets, not achieved measurements or safety certification. Freeze them before scored runs. If a threshold changes after a failure, document why and rerun affected gates rather than relabeling the failed result. A model, camera calibration, prompt, cost policy, or runtime change invalidates its dependent evidence.

All ROS nodes use the simulator clock for observation/TF timestamps. Record capture age in simulation time and compute/transport duration in wall time, synchronizing host clocks for cross-node measurements. The throughput and latency gates require wall-time measurements as well as valid simulation-time ages; a slow simulator must not make stale perception appear fast. Report Gazebo real-time factor with each run. Use a wall-clock watchdog even when the simulation clock pauses.

### Phase 0 Preserve the baseline and prove runtime feasibility

**Work:** create an isolated semantic-demo profile/namespace, preserve the current deployment, inventory accelerator access and container security requirements, and choose AMD or CUDA. Pin code and obtain authorized model weights into a versioned read-only volume. Load the model on the intended hardware and process a small image batch. Do not install GPU drivers from inside a workload container.

**Verification:** record the unchanged hotel configuration and image digests; reproduce its existing single-floor route; render the new manifests without changing the existing release. Demonstrate model loading, valid finite masks, accelerator use, peak memory, and a second startup using cached weights without network downloads. Record dependency/license and resource requirements. Confirm there is no mandatory dependency on the fleet copilot or hosted LLM.

Freeze the initial backend schema, model/preprocessing identifiers, and local backend configuration. Demonstrate that the model runner's image smoke test works without ROS/Nav2 dependencies and that the initial deployment has no OpenShift AI serving dependency.

**Pass gate:** baseline is reproducible and a pinned SAM3 runtime executes successfully on an available deployment target. Otherwise remain at phase 0 and resolve hardware/access, or explicitly choose the ONNX branch.

**Evidence and rollback:** inventory, baseline run, model smoke-test outputs, package lock, resource report, and image/model hashes. The original deployment remains unchanged and runnable.

### Phase 1 Add and validate the camera pipeline

**Work:** add an RGB-D sensor to the robot SDF, matching URDF camera/optical frames, and Gazebo-to-ROS bridges. Keep large raw images local to the simulator pod: JPEG-compress color and losslessly PNG-compress metric depth before Zenoh, then reconstruct points beside inference from the compressed depth and CameraInfo. Extend the rendered per-robot Zenoh allowlists only for the required compressed topics, calibration, and TF. Record a robot-perspective view and validate depth/projection on a known floor region while autonomous commands are inhibited. Introduce the task-specific mat/restricted-surface scene in phase 2 before collecting SAM3 recognition examples. Select sensor resolution/rate after verifying the runtime's input requirements.

**Verification:** inspect RGB, depth/cloud, and calibration at the receiving pod; verify dimensions and pixel order, capture timestamps, namespaces, QoS, and transform availability. Test known floor points and target corners, plus a late-starting subscriber. Record 10 minutes and report delivery/drop rates and Gazebo real-time factor.

**Pass gate:** at least 5 usable synchronized RGB/cloud pairs per second at the receiver; valid depth on at least 95% of the target evaluation region; 95% of checked projected points within 0.10 m of their known location, with no systematic frame offset. Resolve optical-frame or calibration errors rather than enlarging the tolerance. No camera data may enter an active semantic costmap yet.

**Evidence and rollback:** calibration/TF report, synchronization metrics, bag, and annotated projection images. Disable the sensor/bridge overlay and return to the phase 0 image if needed.

### Phase 2 Qualify SAM3 recognition offline

**Work:** collect actual simulated robot-camera views of the mat and similar-looking distractors. Separate prompt-development images from a held-out evaluation set containing at least 50 target-present and 50 target-absent views across distance, angle, lighting, and partial occlusion. Freeze the prompt, inference resolution, thresholds, and visibility envelope before scoring. No training is planned.

**Verification:** compare predicted masks to manually checked target masks. A detected target counts as correct only when its mask intersects the target with intersection-over-union (IoU) ≥0.5. Score misses as zero IoU; do not report accuracy only on detected frames. Measure negative-frame false detections and inference latency/memory on the phase 0 runtime.

**Pass gate:** target recall ≥95%, median target IoU ≥0.70 across all positive views, and false-positive frames ≤5% on negatives, within the frozen visibility envelope. Show the failures, not just selected overlays. These small-sample criteria establish demo feasibility, not general recognition reliability.

**Evidence and rollback:** image manifest, annotations, masks, score report, prompt/configuration, and timing samples. If recognition fails, stay offline: revise prompt/scene and use a fresh held-out set, select another meaningful target with review, or evaluate ONNX. Do not compensate for bad masks by making their navigation cost larger.

### Phase 3 Run live inference without navigation influence

**Work:** implement the SAM3 ROS adapter/policy normalization and status output. Keep semantics disconnected from active navigation. Bound the input queue and retain the cloud corresponding to each processed capture; deliberately skipped camera frames are acceptable, mismatched pairings are not. Provide readiness only after the model is warm and valid results are arriving.

**Verification:** replay phase 2 data and then run live for at least 10 minutes under the intended container quota. Check timestamp propagation and label durability. Inject inference exceptions, process restart, delayed responses, disconnection, and missing model files. Compare transport/inference behavior with recorded recognition results.

Run the backend conformance suite against the local implementation and a deterministic test double. Exercise request/response serialization, valid empty detections, malformed masks, wrong image dimensions, mismatched model versions, wrong robot/stream identity, duplicates, out-of-order completion, expired requests/clouds, and old epochs/policy generations. Verify identical normalized ROS output for identical valid model results across both adapters. The test double proves interface behavior, not recognition accuracy or remote-serving performance; no live OpenShift AI endpoint is required.

**Pass gate:** ≥5 fresh masks/s; p95 capture-to-result age ≤250 ms; ≥95% of emitted masks pair with their corresponding valid cloud; no unbounded queue or memory growth. Every accepted output has the expected frame, policy version, and class mapping. Faults produce explicit not-ready state, not stale output with new timestamps.

All backend conformance cases must pass before phase 4. Invalid results must produce no semantic observation and must not refresh the valid-result heartbeat. Deadline expiry and backend restarts must not trigger implicit backend switching or motion resume.

**Evidence and rollback:** ROS contract tests, latency percentiles/worst case, pairing statistics, resource traces, and fault logs. Inference can be stopped without disrupting ordinary Nav2.

**Execution update, October 16, 2026 — PASS; user review approved:**
The user approved the Phase 3 review on October 16, 2026, completing this phase's
reviewer gate. This approval does not activate Phase 4 or change the deferred
recognition-review waiver.

The isolated SAM3 runtime has the versioned backend contract,
0/2 policy labels, durable metadata, organized clouds and bounded queues.
Capture timing now starts immediately before Gazebo RGB-D rendering and retains
original simulation headers, with a 2 ms cross-node clock allowance. The raw
DDS source path failed full p95 latency (409 ms) and showed receive-buffer drops.
Direct Gazebo input to the existing compressor preserves codec bytes/headers
and avoids that large-message DDS hop. A 40 ms inference-queue admission limit
controls waiting work. A separate output-consumer DDS recovery profile (1 ms
NACK delay) resolves the measured point-cloud retransmission delay without
changing host sysctls. The final 600-second run produced **4,092 valid pairs at
6.82/s, 100% pairing, and p95 capture age of 231.36 ms at publication, 236.79 ms
at paired arrival, and 243.93 ms after validation**. There were no invalid
outputs, readiness interruptions or publication gaps >500 ms. Queues remained
bounded; RSS largely plateaued after early buffer growth. These measurements
qualify the pinned runtime **and the documented receiver profile**, not an
arbitrary Nav2 subscriber or model-serving deployment.

Fault checks on the final image passed delayed source delivery, pause, three
simulation resets, inference exception/delay, three missing-model checks and
process restart. The reset fix immediately invalidates retained work on `/clock`
rollback, rejects pre-reset wall captures, and checks simulation age before
publication. Twenty-nine build tests and a separate installed-adapter reset
barrier check passed. The [Phase 3 runtime report](validation/semantic-navigation/phase-3/runtime-report.md)
retains failed/intermediate evidence and exact image pins. Recognition scoring,
OpenShift AI serving, Nav2/costmaps and motion remain deferred; no next-phase
activation follows automatically from these runtime tests.

### Phase 4 Verify projection and semantic map lifecycle

**Execution update, October 16, 2026 — PASS; user review approved:** The user
authorized Phase 4 after approving Phase 3. Implementation and evidence are
tracked in the [Phase 4 report](validation/semantic-navigation/phase-4/runtime-report.md).
The selected candidate is a repository-local fixed-policy Nav2 layer, not the
unmodified upstream semantic layer. It uses the Phase 3 JSON metadata contract,
capture-based expiry, bounded state, full raster rebuilding, and reset barriers.
An additive payload-hash timing extension binds mask/cloud contents to an
inference result across repeated simulation timestamps. Twenty-three deterministic
tests and an additional full-grid snapshot test passed. Live clear,
deactivate/reactivate, paused-clock expiry and simulation reset checks passed;
stale costs disappeared 1,031 ms after capture against the measured 1,069 ms
expiry limit. A separate 600-second run applied 3,957 distinct results to each
map at 6.59/s, with p95 capture-to-costmap age **252.16 ms global / 252.84 ms
local**, no new rejections, no queue evictions, and no not-current intervals.
Publisher-to-applied correlation was 100% in the aligned capture interval
(not raw-camera admission yield). Observed state and RSS remained bounded.
These results qualify the pinned isolated profile only, not moving navigation,
hotel-map/inflation performance, or OpenShift AI serving. Recognition scoring
remains deferred. The user subsequently approved the Phase 4 review and requested
Phase 5; that approval is recorded without extending the stationary qualification
to moving navigation.

**Work:** load the semantic layer into isolated test costmaps, with robot motion inhibited. First feed deterministic synthetic masks/clouds, then the phase 3 model output. Synthetic inputs verify integration only; they are not AI results. Fix or select a layer revision that passes lifecycle tests before proceeding.

**Verification:** assert exact costs on a small known grid; test maximum merging against occupied and unknown geometric cells. Test target removal, observation expiry, clear/reset, deactivate/reactivate, rolling-window motion, out-of-order data, and simulation clock reset. Inspect the layer's raster and observation buffers, not only its visible overlay.

Delay an inference result across a reset and verify it cannot repopulate cleared costs. Invalidate pending requests whenever clearing establishes a new observation epoch; only captures from the new epoch may rebuild the map.

**Pass gate:** every deterministic test passes. Expired or explicitly cleared target observations cannot reappear without a fresh observation; static obstacles remain occupied. For a configured observation lifetime T, obsolete semantic cells disappear by T plus two measured costmap update periods. An explicit reset clears both raster and temporal state. Capture-to-costmap p95 age is ≤300 ms in the live path.

**Evidence and rollback:** automated grid assertions, before/after maps, lifecycle logs, selected plugin commit and any patch tests. Keep semantic layers disabled outside the isolated test profile. Restart the test process to remove stale state if rollback requires it; an `enabled: false` toggle alone is not proof of clearing.

### Phase 5 Validate the shared navigation and stop configuration

**Execution update, October 16, 2026 — IN PROGRESS; gate HOLD:** The user approved
Phase 4 and requested Phase 5. Implementation, command-path/geometry audit and
incremental qualification are tracked in the
[Phase 5 report](validation/semantic-navigation/phase-5/runtime-report.md).
At the October 22 checkpoint, the pinned non-actuating preflight passed 169
semantic-safety tests, the static geometry audit, the native Collision
Monitor/smoother fixture, and the owned-action lifecycle fixture. This does not
qualify motion or close a Phase 5 acceptance gate; the measured geometry
discrepancy and remaining moving gates are recorded in the
[Phase 5 report](validation/semantic-navigation/phase-5/runtime-report.md).
The follow-up placement scan found no reserved non-GPU worker; the user
postponed the moving trace rather than run it on shared capacity. The launcher
has an opt-in pinned-node GPU check, and the recovery-series runner now requires
that check for every trial; neither reserves CPU resources. Phase 5 remains HOLD.
The candidate uses an explicit footprint, enabled geometric protection and a
disconnected output topic. The earlier preflight passed 30 guard/receiver tests,
six profile tests, and an isolated native Nav2 collision-monitor fixture.
The frame discrepancies now have isolated asset corrections and a
capture-preserving sensor bridge (four asset tests and six installed-ROS callback
tests). A native Gazebo guard enforces 80 ms command leases directly at the wheel
commands, with 15 native tests. The private flat-world fixture passed all eight
live checks in two runs: producer loss reached wheel zero in 61.6–62.7 ms,
explicit stop in 0.94–1.21 ms, and late commands did not resume motion. This is
actuator qualification at 0.1 m/s, not hotel navigation. Startup transport
stalls and premature stops are retained as failed evidence in the report;
connections are now warmed while stopped and service calls isolated from
Python status callbacks, without extending the 80 ms moving lease.
At that initial checkpoint the full Nav2-to-hotel motion route was not connected;
the October 17 update below supersedes that integration status.
Further non-actuating tests now pass for UUID-bound ROS task cancellation and
the stamped Nav2 smoother/monitor chain: 49 pure Python tests, eight owned-action
checks, eight native command-chain checks and seven profile tests. Cancellation
ACKs do not permit a new task until terminal confirmation; late backend success
after a fault remains a stopped task. A source-command ledger rejects the
smoother's timeout-generated fresh stamps, which otherwise could conceal old
command authority. The combined coordinator now passes ten live flat-world
checks twice, with 69 Python tests, six ROS frame callback tests and 15 native
tests. Native capture-time mapping, live stationary/neutral checks and bounded
zero-motion arming are connected to the guard. At 0.1 m/s, halted supervisor
output reached wheel zero in 48.9–61.1 ms, killed transport in 50.8–53.7 ms,
and scan-evidence loss in 489–491 ms from update cessation (before the freshness
deadline). The fixture still uses controlled commands, synthetic scan/TF evidence
and one fake action backend. Actual hotel sensor streams, full Nav2 task ownership,
adversarial runtime publisher checks and moving-frame registration remain to
integrate and verify. Per-message Cyclone GUID binding now passes its isolated
observer subgate; that alone does not authorize motion.
The next disarmed hotel fixture now runs actual sensors, AMCL and the candidate
Nav2 stack. It found and fixed costmap lidar namespace resolution: both candidate
maps now explicitly use `/robot_1/scan_fixed`. Actual planning, nonzero command
generation through the smoother/monitor, terminal cancellation and stationary
capture-time sensor-to-map transforms pass. No actuator lease is issued and no
baseline goal completion is claimed. Four software-rendering threads restored
near-real-time operation in a short diagnostic; sustained timing is still pending.
A bounded 20 ms capture join handles independent command/native-status ordering
without extending command lifetimes. The read-only Cyclone built-in publication
lookup resolves per-message handles to endpoint GUIDs; live probes of an
unexpected writer and its restarted replacement each resolved to a distinct
GUID and were rejected against the approved graph. A Nav2 1.3.13 smoother
overlay now preserves `frame_id` on timeout deceleration without changing the
source-command deadline; the actual overlay executable passed hotel frame,
cancellation, and ledger checks. With 10 Hz private lidar and 100 Hz smoother,
two 20-second 40 Hz controller observations had zero optimistic authority gaps
(1,797 and 1,997 eligible outputs), while a 30 Hz run had one 2.77 ms gap. The
next disarmed repetition passed all 14 live checks, with 1,996 eligible checked
outputs and zero optimistic gaps. It also recorded the ten actual Nav2 action
servers in the candidate graph (navigation, follow-path, recovery, planning and
smoothing actions), closing discovery but not runtime all-client ownership or
fault-time cancellation. See the retained [action inventory](validation/semantic-navigation/phase-5/hotel-28-20261017/runtime/action-endpoint-inventory.json).
At that disarmed checkpoint the
40 Hz profile remained an isolated diagnostic, not a motion-qualified setting:
coverage analysis omits supervisor/lease timing and window edges, and the run
was stationary/disarmed. The overall Phase 5 gate remains HOLD pending moving
baseline trials, physical stop measurements, moving-frame validation, and live
fault injection. See the [runtime report](validation/semantic-navigation/phase-5/runtime-report.md).
**October 17 implementation update:** the real-input hotel adapter now connects
the coordinator to native actuation in a private test mode. Native-zero startup
replaces the idle-Nav2-zero dependency; dispatch/admission revalidate task state,
collision STOP latches, and newly accepted commands enqueue leases immediately.
The exact ten action endpoints and allowed/frozen client graph are checked;
parent/child terminal status is tracked without pretending UUIDs encode lineage.
Native capture samples are drained between ROS callbacks. The explicit baseline
tree excludes recoveries, whose qualification remains outstanding. Candidate
rates are 40 Hz controller/behavior and 100 Hz smoother; guarded lidar is 10 Hz.
RPP rechecks positional arrival (`stateful: false`) without changing goal
tolerances. Hotels 32, 34 and 35 each passed all 16 integration checks and completed
the one-meter target; hotel 33 stopped on an unclassified rejected scan and is
retained as a failed trial. These are initial integration results, **not** the
10/10 collision-free baseline. Local checks total 106 safety tests and ten
profile/tree tests, with six additional installed adapter callback tests.
The updated combined fault fixture passed all 11 checks, including latched
collision-state stop/clear, suspended supervisor processing and transport death.
The [runtime report](validation/semantic-navigation/phase-5/runtime-report.md)
records implementation, failures, measurements and remaining acceptance work.
**Contact/geometry follow-up:** diagnostics confirmed backward tipping onto the
rear chassis corners. Opt-in rear ball casters plus finer physics steps remove
that unintended contact; chassis contact was not exempted. A level robot exposed
the original 3.5 m lidar's insufficient range in the open starting area. The private
candidate now uses an explicit **12 m virtual sensor**, not a claimed physical
TurtleBot capability. The scan validator requires the selected range to match.
At 2 ms physics with 200 Hz native odometry, hotel 45 passed **20/20 guarded
integration/contact/stop checks**, completing the target without unexpected contacts.
Native odometry remains capture-stamped, motion correction stays enabled, and
source/lease/freshness limits are unchanged. Failed 1 ms timing and 2 ms/50 Hz
lease-expiry trials remain retained. The final-image obstacle-contact positive
control passed. Local tests now total **121 safety tests plus ten profile/tree tests**.
The fixed ten-trial series is separate from these pilots; see the
[geometry, latency and trial evidence](validation/semantic-navigation/phase-5/runtime-report.md#support-geometry-correction-and-range-investigation-follow-up).
**Fixed-series outcome:** series 1 stopped on its first failed trial (0 successful,
1 attempted, 9 not attempted). Contact checks passed, but native lease expiry
canceled the goal. The command trace shows up to 44.53 ms between C++ observation
and the Python adapter callback; publication-to-C++ observation stayed below 1 ms.
**Callback-scheduling follow-up:** ingress, sensor/TF and task callbacks now use
separate persistent executors polled on one thread, with bounded four-poll batches
for both ingress and observation. Intermediate failed candidates exposed both
command backlog and TF backlog; their evidence is retained. Audit-hop timestamps
and capture-time TF diagnostics were added without changing authority deadlines.
Hotel 50 passed **20/20 checks**; observer-to-callback latency was
0.820/3.612/8.043 ms median/p95/max, and normal-completion revoke-to-applied-zero
was 2.238 ms. Local checks pass 124 safety tests plus ten profile/tree tests;
installed callback tests cover exact-capture TF and no latest-TF fallback.
**Baseline repeatability subgate passed:** the new frozen
[series 2](validation/semantic-navigation/phase-5/baseline-series-2-20261017/summary.json)
completed **10/10 trials**, with 20/20 goal/contact/stop checks in each and no
retries or runtime changes. Pooled observer-to-callback latency was
0.943/3.673/8.103 ms median/p95/max; normal-completion revoke-to-zero ranged
2.579–5.963 ms. These are localized Nav2 goal successes, not exact one-metre
physical travel or fault-triggered braking qualification. The private fixture
was cleaned up; canonical deployments remain unchanged. See the
[latest scheduling evidence](validation/semantic-navigation/phase-5/runtime-report.md#callback-scheduling-correction-latest-follow-up).
**Overall Phase 5 gate: CLOSED.** All four moving gates passed and the
evidence review was approved by the user on October 26, 2026, with the
caveats recorded in the
[sign-off section](validation/semantic-navigation/phase-5/runtime-report.md#phase-5-evidence-review-and-sign-off-october-26-2026).
Keep semantic costs excluded and the canonical deployment unchanged. Deterministic
guard tests do not substitute for the ten baseline trials, physical stopping
measurements, moving-frame validation or live fault injection required below.

**Work:** establish a common single-floor safety profile: verified robot footprint, geometric layers, final command routing, collision intervention, and watchdog. The canonical hotel configuration disables global obstacle/inflation layers for lift handling and disables its configured approach polygon, so do not assume these are already suitable. Apply any corrections equally to baseline and semantic arms. [Existing parameters](../config/nav2/hotel_nav2_params.yaml).

**October 23 recovery-repeatability update — subgate PASS:** the
Wait-transition stamp-lag root cause was proven from retained evidence to be
the velocity smoother's terminal deceleration ramp reusing BackUp's terminal
zero-command stamp (7 × 10 ms steps at the qualified decel, each consuming
10 ms of the terminal command's fixed source lifetime); the earlier `/clock`
hypothesis was refuted (raw behavior-server commands keep 0.4–7 ms
stamp-to-publish lag through the transition in every trial). A user-approved
coordinator change renews zero-only Wait authority at settling-tail admission
— removing the native-status confirmation round trip from the critical
authority path while the confirmed hold remains the measured Wait-interval
anchor — and a fresh GPU pilot plus the fourth frozen ten-trial series passed
**10/10 trials with all 31 checks each** (renewal margins 15.3–28.3 ms versus
0.78 ms in the failed race; zero pre-zero Wait samples; revoke-to-applied-zero
2.8–5.5 ms; independent displacement 0.288–0.301 m). This closes the
recovery-repeatability subgate only; moving fault-stop coverage, moving SAM3
registration/load and the armed semantic fault matrix keep Phase 5 HOLD. See
the [series evidence](validation/semantic-navigation/phase-5/runtime-report.md#fourth-series-attempt-1010--recovery-repeatability-subgate-passed).

**October 23 moving fault-stop update — subgate PASS:** a fault-stop probe on
the identical frozen guarded GPU profile injects one fault class at a time
after independently verified motion: collision-monitor STOP state,
supervisor-only scan-evidence cutoff, controller-server stall, native
transport-worker loss, and a physical post moved mid-trial into the Collision
Monitor stop envelope but outside the padded hull (detected by the real
monitor; no footprint contact possible). Three failed obstacle pilots were
retained with root causes — a pump-blocking subprocess call, entity creation
stalling physics 190 ms inside PreUpdate, and the gz-transport connection
handshake stalling the server 104 ms (the native-7 NodeShared-mutex lesson) —
before the persistent pre-warmed mover design passed. The frozen matrix
passed **10/10 trials** (each class twice): mode-qualified first stop reasons
in their correct latency bands, trigger-to-applied-zero 0.3–4.7 ms, sampled
stopping distances 1.7–2.3 mm at 0.15 m/s, no clock fault, no unexpected
contact, no automatic resume. This closes the second moving gate; moving
SAM3 registration/load and the armed semantic fault matrix keep Phase 5
HOLD. See the [matrix
evidence](validation/semantic-navigation/phase-5/runtime-report.md#moving-fault-stop-probe-five-fault-classes-on-the-qualified-guarded-fixture).

**October 26 moving SAM3 update — subgate PASS:** observation-only SAM3
(image `478ec…`, prompt `red mat`) runs beside the guarded baseline on the
identical frozen GPU profile, semantic costs excluded from navigation. Console
build 23+ gains the Phase 3 capture-trace override (pinned gz-sensors commit,
compiled against the image's exact installed ABI); the camera and semantic
streams are isolated on their own ROS domain (88) with the compressor and
scoped Zenoh bridge as sidecars and the observation results processed by a
separate worker sidecar with its own CPU quota. The decisive load finding
(16 retained series attempts, 11 pilots): the perception camera's gz
publications hold the console server's transport mutex long enough to delay
the watchdog's status publication itself (p95 ~575 ms), beyond the 20 ms
capture-bracket joins; the user-approved C++ remedy is a **UDP companion
path** for the watchdog — non-blocking status `sendto`, a UDP listener for
leases/arm/stop feeding the same guard with unchanged proofs, all qualified
gz paths remaining active — plus the graph audit moved off the command path
per the October 19 prescription and the guarded future-stamp check consulting
the authoritative native physics sim. The frozen ten-trial series passed
**10/10**: 52–61 moving results per trial, ~850k capture-time projected
points at **100% in-rectangle registration in every trial**, p95 capture age
187–195 ms, 6.6–7.3 results/s, all guarded goals succeeded, and the parked
demo SAM3 pod was restored on its L40S placement. This closes the third
moving gate; the armed semantic fault matrix keeps Phase 5 HOLD. See the
[series
evidence](validation/semantic-navigation/phase-5/runtime-report.md#moving-sam3-observation-registration-under-motion-and-load-on-the-guarded-fixture).

**October 26 armed semantic fault-matrix update — subgate PASS:** the
semantic-task supervisor runs armed — `SafetyGate(require_semantics=True)`
adds camera (render-time capture traces), semantic (SAM3 timing records by
capture age) and inference-heartbeat (the runtime's 20 Hz status) leases to
the unchanged 500 ms capture-age freshness, fed by the observation worker —
while semantic costs remain excluded from navigation. Five fault classes are
injected after verified semantic-armed motion (≥0.3 m with a fresh result):
camera path loss (the fixture stops the camera bridge), TF loss (AMCL
paused), hung inference (SIGSTOP of the wrapper-child process — signals to a
PID-namespace init are dropped even for SIGSTOP), process loss (SIGKILL, the
container auto-restarts) and transport loss (the SAM3 pod is force-deleted;
the repair recreates it through the live router). Every mode must stop
fail-closed with a mode-qualified first reason, zero within 100 ms of the
freshness trigger, an observed late success that does not resume motion, and
readiness requires a sustained five-second fresh-result streak (the SAM3
stream has a reproducible pre-arming burst phase). The frozen matrix
(`semantic-fault-matrix-13-20261026`) passed **10/10 trials** (each class
twice): first reasons `camera_stale`/`semantic_stale`/`command_expired`
in their correct bands, injection-to-trigger 224–1963 ms, trigger-to-zero
0.3–2.6 ms, and observed late successes with hundreds of disarmed native
samples per dwell. Twelve retained series document the infrastructure
findings fixed en route — most operationally relevant: a zenoh client
session never re-dials a lost router, so backend loss is repaired by pod
recreation, not in-place process restart alone. This closes the fourth and
final moving gate; Phase 5 acceptance awaits the evidence review. See the
[matrix evidence](validation/semantic-navigation/phase-5/runtime-report.md#armed-semantic-fault-matrix-the-supervisor-stops-on-perception-loss-while-costs-stay-excluded).

**Verification:** first run RPP with semantics excluded and prove collision intervention, cancel, restart, and command expiry. Next run perception in observation-only mode during baseline motion to verify registration under motion and its effect on compute/network load. Inject camera loss, TF loss, stale masks, and a hung inference process while the semantic-task supervisor is armed but costs remain excluded.

**October 19 TF-loss subgate PASS (private geometry-only fixture):** both an AMCL
publisher outage and TF delivery loss confined to the supervisor's dedicated
buffer pass live stopping/cancellation tests with the normal 500 ms TF freshness,
100 ms command freshness, and 80 ms maximum native lease. The publisher outage
may stop earlier on command expiry; fault observation continues until a new
capture proves the frozen map edge. The isolated supervisor-buffer test requires
`tf_stale` while the full Nav2 TF buffer can still resolve the same capture.
Both final runs restore TF, verify physical stationarity and all cancellation
acknowledgements, and demonstrate no automatic restart. Earliest verified trigger
to native applied zero was 3.185 ms for the AMCL outage and 2.293 ms for the
supervisor-only fault. The temporary 50 ms override was removed. See the
[qualification and retained evidence](validation/semantic-navigation/phase-5/runtime-report.md#october-19-tf-loss-subgate-pass-in-the-private-geometry-only-fixture).
These tests close the current TF-loss blocker; moving SAM3 and the remaining
armed semantic fault matrix are still outstanding, so Phase 5 remains HOLD.

**October 19 recovery follow-up:** live diagnostics confirmed a goal-time
mismatch: RPP saw 0.1934 m remaining, but the goal checker saw 0.2167 m because
it transformed the same fixed map endpoint at the original path timestamp.
An opt-in private controller candidate evaluates that endpoint at the robot
pose's capture timestamp instead, without relaxing the 0.20 m arrival tolerance
or changing sensor/command timestamps. Recovery probes now use a fixed 0.50 m
target; the earlier recovery-13 used 0.35 m and was not an identical repeat of
recovery-10. Synchronous graph-audit stalls, simulator capture pauses, and stale
reported post-stop angular velocity are separately evidenced blockers. Require
a passing candidate pilot before the new frozen ten-trial recovery series; no
retry-until-pass qualification. See the
[diagnosis and candidate evidence](validation/semantic-navigation/phase-5/runtime-report.md#october-19-recovery-investigation-endpoint-time-mismatch-confirmed).
The candidate compiled and its executable/library were verified in the first
live pilot, but a 156.58 ms physics pause stopped navigation before the goal
region. That pilot did not verify the correction's end-to-end effect.

**October 19 recorder isolation:** a subsequent console-only Gazebo server-API
diagnostic completed BackUp, Wait and FollowPath with the controller candidate;
the largest observed task capture gap was 16.515 ms, native zero took 3.095 ms,
and contact/stationarity checks passed. Re-enabling full-world recording through
the API reproduced a 203.784 ms pause and a failed 116.139 ms native-zero delay.
Time-aligned resource counters show no additional CPU-quota throttling around
that pause. A 3600 s recording period was ineffective: component changes still
generated a recording at effectively every physics step. See the
[paired diagnostic evidence and limitations](validation/semantic-navigation/phase-5/runtime-report.md#recording-disabled-api-diagnostic-and-recording-enabled-control).

Separate console logging from optional world recording for the private moving
fixture, retaining native command/pose/contact/stop evidence and source hashes.
The exploratory API path remains **diagnostic-only**. A separate opt-in pinned
console-only qualification candidate now verifies startup restrictions, actual
binary/source identity, absence of recording, and bounded shutdown. Default and
canonical deployments are unchanged. Its first moving pilot passed startup but
failed BackUp after a 63.083 ms Collision Monitor output gap; the watchdog stopped
within 3.070 ms, with contact/cancellation/stationarity checks passing. No
capture-clock fault or CPU-quota throttling was observed around the concurrent
48.625 ms physics gap. Internal TF-wait and scheduling contributions still need
measurement; do not relax the timing or transform requirements.

The new shutdown gate also exposed display teardown ordering and ROS-context
shutdown defects. Dependency-ordered cleanup removed the XIO error; a private
Gazebo stop-service test avoided the subsequent invalid ROS-context exception,
but still required forced termination after five seconds. Follow-up
instrumentation captured its blocking
stack in `SensorsPrivate::Stop → std::thread::join` during server destruction,
after the renderer had exited. The private launcher now owns a stop worker and
joins it before destruction; its new `/phase5/console_stop` endpoint avoids
the overlapping built-in stop/destruction path. The corrected candidate
**passed full disarmed hotel shutdown**, exiting normally and reaped 1.443 s
after acknowledgement, with no forced termination. This resolves the reproduced
teardown blocker in the private fixture, not the moving-navigation gate.
These were disarmed checks, not retries of the failed moving pilot. See the
[candidate pilot and shutdown investigation](validation/semantic-navigation/phase-5/runtime-report.md#pinned-candidate-pilot-startup-passed-moving-gate-failed).
The follow-up image (`semantic-safety-console-phase5-3`, digest
`sha256:e956a58dbd4f70dfc2e8e28c2526ea72eb91084dc48f363d0be3ebf7a0ba88eb`)
adds lifecycle markers and captures bounded thread diagnostics only after a
shutdown timeout has already failed the gate. Its first attempt initially lacked cluster
capacity and was subsequently aborted during a scheduling/cancellation race;
the fresh disarmed attempt captured the stack and failed shutdown. Both attempts
are retained, with private resources cleaned up and the running demo unchanged.
The serialized-stop correction (build `semantic-safety-console-phase5-4`, digest
`sha256:b0bcdf4700fd13fb5e9d35936f465a74b2edd8124dd30f840b687782e35b4f6c`)
passes 164 safety and 22 runner/series local tests, all 11 actual-binary
preflight checks, and the full disarmed hotel checks. See the
[verified shutdown evidence](validation/semantic-navigation/phase-5/runtime-report.md#serialized-shutdown-verified-in-the-disarmed-hotel-fixture).
An opt-in 1 ms TF-leg probe now identifies the mechanism behind the recurring
Collision Monitor stalls. The Phase 5 frame bridge publishes `odom →
base_footprint` TF only on odometry callbacks and preserves each odometry
header timestamp. As a result, the requested `curr_time` commonly leads the
newest TF sample. The disarmed 50 Hz fixture's capture-time `odom ← lidar_frame`
transform was available in a mean 0.105 ms, while the current-time base/odom
leg was first observed after lookup start in 717/778 logged calls (mean 9.793
ms). TF2 0.36.22 then polls with a fixed 10 ms sleep: 377 target transforms
arrived 5–10 ms after lookup start and all corresponding lookups completed in
the ~10 ms class; for 301/326 observed arrivals after 10 ms, lookup duration
rose to the ~20 ms class. In the controlled disarmed 200 Hz comparison, all
466 target transforms arrived after lookup start but within 5.479 ms (mean
2.053 ms), yet every full lookup still took 10.123–11.740 ms. This confirms
that 200 Hz reduces the transform-publication phase gap and removes the
observed 20 ms class, but the fixed TF2 poll leaves a ~10 ms latency floor
whenever the initial lookup misses.

The 200 Hz candidate also passed the earlier guarded moving pilot 45 (20/20
checks), but the later timing runs failed their independent
settled-support-geometry check and remain diagnostic evidence, not qualification.
The earlier 63.083 ms moving-pilot output gap and isolated ~30.3 ms lookup
events were not fully attributed by the first probe. The first matched ABBA
timing comparison did show a
77.9% median reduction, but all four runs used the default unsupported chassis
profile and failed the exact support-contact gate; those data are exploratory,
not representative of the qualified demo profile.

The follow-up repeated two ABBA sequences with the fixed-series geometry
(`--rear-casters`, 2 ms physics, 12 m virtual lidar, 200 Hz odometry), matched
1,000 μs logging thresholds, and verified stock/patched TF2 library identity.
Every one of the eight stationary, disarmed runs passed the support geometry
gate; the previous support-contact failure was a diagnostic invocation
omission, not a current model defect. A launcher guard now requires that
qualified geometry for Collision Monitor timing diagnostics. Without added
CPU workers, the overlay reduced median/P90 from 10.178/10.278 ms to
6.538/9.243 ms (35.8%/10.1%). With bounded two-worker load, median improved
only 12.5% (10.177 to 8.910 ms) and P90 was 1.5% worse (11.795 to 11.976 ms).
Thread CPU per logged lookup rose 71.9% without added load and 77.6% under
load; median scheduler slices increased from 2 to 7 and 2 to 9, respectively.
These are ≥1 ms-selected lookups, not all-call or end-to-end latency. The
overlay's gain is load-sensitive and its wakeup cost is material, so keep it
private/opt-in; it is not yet recommended as the demo fix. A follow-up
producer trace recorded ROS odometry receipt and frame-bridge TF send times:
the `/clock` age at receipt was 0–2 ms and `sendTransform` took under 0.5 ms
at the median. Stock TF2 still exhibited three ~20 ms lookups/callback gaps:
the current-time base transform arrived 10.99–11.43 ms into lookup, then the
fixed poll added about 9 ms before return. In a prior ~30 ms event, the exact
target edge arrived at 23.039 ms; lookup, `getData`, complete callback, and
next callback start took 30.412, 31.328, 31.595, and 31.674 ms. The 1 ms
overlay removed the second polling quantum in the traced arm (maximum lookup
12.375 ms), but its extra polling CPU and weak loaded P90 remain drawbacks.
This localizes the ~20–30 ms synchronous stall to waiting for a future exact
base-TF sample plus stock TF2 polling, but it does not fully account for the
historical 63.083 ms *checked-output* gap. Retrospective correlation of the
failed moving pilot shows a scan receipt inside the 63.083 ms interval and
67.696 ms of Gazebo-main-thread run-queue wait over a broader 206.389 ms
resource-sample window; this makes upstream simulator/scan scheduling a
credible contributor, but does not prove that it caused the specific gap.
The disarmed tests suppress idle zero-output heartbeats, so they cannot qualify
active output continuity. Do not substitute latest TF or reuse stale data. The
corrected one-shot moving trace directly reproduced a **53.150 ms** checked-
output gap: a 51.986 ms Collision Monitor lookup waited 44.993 ms for the exact
current-time base transform, while the frame bridge had a 55.638 ms odometry
receipt gap for 6 ms of simulation time. TF broadcast itself took 0.321 ms;
stock TF2 polling accounts for only the short tail after the edge arrived. The
trace therefore identifies late exact-time odometry/TF as the direct mechanism
for this gap class, consistent with—but not a replay of—the historical 63.083
ms event. The short recovery task then correctly failed closed: its last
admitted capture was already 86.145 ms old, the next checked command was
rejected as expired, and the watchdog applied zero within 1.936 ms. Motion was
only 0.02993 m; BackUp was canceled before Wait, so Phase 5 remains **HOLD**.

The trace ran on the same node as the persistent hotel simulator. A
post-run-only metrics snapshot showed 91% node CPU and 9.269 cores consumed by
that simulator despite its 1-CPU request; this makes shared-node load a
credible contributor, not proven event-time causality. First isolate the
simulation or size CPU requests realistically and verify real-time factor and
odometry cadence. Do not raise freshness/lease thresholds or use latest TF.
If the exact-time edge is still delayed under isolated load, prototype
nonblocking exact-time readiness with a deadline-triggered safe stop. See the
[corrected-profile comparison](validation/semantic-navigation/phase-5/runtime-report.md#october-19-corrected-geometry-stock-vs-1-ms-comparison),
[producer trace](validation/semantic-navigation/phase-5/runtime-report.md#october-19-tf-producer-trace-20-30-ms-stall-stages-localized),
the [October 20 moving trace](validation/semantic-navigation/phase-5/runtime-report.md#october-20-moving-trace-53-ms-output-gap-directly-tied-to-late-exact-time-tf),
and [archived moving-pilot correlation](validation/semantic-navigation/phase-5/runtime-report.md#archived-moving-pilot-correlation-63083-ms-output-gap-narrowed-not-closed),
plus the [full timing investigation](validation/semantic-navigation/phase-5/runtime-report.md#october-19-private-tf2-1-ms-polling-candidate-initial-timing-probe-superseded-by-matched-profile-tests-below).
The fixed ten-trial recovery series remains unstarted; the TF-loss subgate pass
is unchanged; overall Phase 5 remains **HOLD** for its other outstanding
criteria. Current local checks pass 169 safety tests and 30 Phase 5 runner/series
tests, including the moving-profile serialization regression and qualified
profile guard; Python compilation and `git diff --check` pass.
Require a fresh passing moving pilot before the fixed ten-trial recovery series.
Neither the earlier successful diagnostic nor disarmed shutdown checks establish
recovery repeatability. The series has not started; Phase 5 remains HOLD with
all original safety thresholds.

Use the test backend to simulate remote-style timeout, overload, and connection loss without deploying remote serving. Confirm these failures follow the same stop path as local inference failure, and that a late successful response cannot authorize automatic resume.

**Pass gate:** 10/10 baseline trials complete without collision; all fault tests stop motion and expose a reason. Initial stale-input trigger is 500 ms, monitored using capture age and a wall-clock heartbeat; the final command becomes zero within 100 ms of the trigger. Independently measure physical stopping distance after command zero. Verify every velocity-producing path, including recoveries, passes through the same guard. No automatic motion resume after a fault.

**Evidence and rollback:** baseline trajectories, final-command and physical-stop traces, footprint review, controller timing, and fault results. Revert to the last passing shared profile with semantics off. Stop before reverting a profile on a moving robot.

### Phase 6D User-approved demo-only track (October 20, 2026)

**Authorization and boundary:** The user approved a staged simulation demo
without waiting for the full Phase 5 safety-qualification gate or deferred
Phase 2 held-out recognition review. This waiver is only for the controlled
single-floor scene and fixed, reviewed target below. It is not evidence that
SAM3 reliably recognizes arbitrary hotel scenes, nor approval for physical
robots, canonical deployment, unattended operation, or production use.

Keep the last known-working hotel navigation behavior and its planner/controller
settings. Use one isolated Gazebo simulator and one robot; do not run a duplicate
simulator alongside the persistent demo. Add only the fixed SAM3 perception
path and the repository's semantic layer to an opt-in demo profile. Semantic
costs are additive (soft cost 200, maximum merge), applied before inflation;
they must never clear or lower geometric costs or unknown space. Retain existing
geometric obstacle handling, Collision Monitor, and stop/watchdog path. Do not
relax freshness, command-lease, collision, or stopping thresholds to make the
demo pass. Keep speed at or below 0.15 m/s and identical in both arms. Do not
change the planner, controller, replanning cadence, map, or scene between arms.

The target is one staged, visually distinctive floor mat with one frozen SAM3
prompt (the current development candidate is `red mat`). Start from a geometry
and route where the baseline demonstrably crosses the mat and a detour exists.
Do not use the ground-truth annotation as a navigation input, hand-edit masks,
or claim the development prompt sweep is a held-out recognition result. Keep
camera and inference running in both arms so the comparison includes similar
compute load. Size/reserve simulator CPU realistically, record node CPU and
Gazebo real-time factor, and stop if timing or stop behavior violates the
existing limits; the October 20 trace identifies late exact-time odometry/TF as
the direct mechanism for the reproduced output gap, with shared-node CPU load a
credible but not proven contributor.

**Sequential demo gates (verify each before proceeding):**

1. **D0 — Isolated profile preflight:** render and inspect an opt-in profile;
   prove it selects the known-working Nav2 configuration plus only the semantic
   additions; verify exactly one simulator/robot, image and model pins, prompt,
   topic/frame mappings, resource requests, and no canonical release changes.
   Run configuration/plugin-load checks without dispatching motion. If profile
   identity, plugin load, or isolation is uncertain, stop at DEMO HOLD.
2. **D1 — Perception-to-costmap smoke test:** with the robot stationary, verify
   the live SAM3 output is capture-aligned, projected into both maps at the mat,
   and adds the selected soft cost without changing geometric/unknown cells.
   Remove/occlude the mat and verify old semantic cells clear within the Phase 4
   expiry bound. Inject inference loss/staleness; the semantic-required task
   must pause/fail rather than silently continue as a geometry-only success.
3. **D2 — Paired comparison:** run three paired trials, alternating arm order,
   with the same scene, start/goal, map, speed, planner/controller parameters,
   and camera/inference load. Reset semantic state between trials. In each
   pair, semantic-off should take the intended baseline route across the mat;
   semantic-on should visibly route around the mat. Record paths, overlays,
   costmaps, goal outcomes, interventions, timing, CPU, and real-time factor.
   A collision, unexplained stop, stale-cost persistence, or failure to produce
   the intended contrast is DEMO HOLD; fix the cause and repeat the complete
   affected pair rather than selecting only successful runs.

**D0 execution update, October 20 — plugin-load subgate PASS; overall DEMO
HOLD:** an opt-in parameter candidate is generated at
[`phase6-demo-nav2-candidate.yaml`](../helm/semantic-navigation/phase6-demo-nav2-candidate.yaml)
from the existing hotel Nav2 parameters. Six local tests confirm the original
controller, planner, collision-monitor, smoother, geometric layers and inflation
settings are unchanged; the only changes are an additive cost-200 semantic
layer in each costmap before inflation, with the fixed topic/frame and expiry
settings. The original config remains unmodified. This verifies the local
parameter overlay, not the full demo profile. A read-only comparison confirmed
that the canonical hotel Nav2 parameters, launch file, and Helm values match the
`rmf-hotel-world-openshift-ai` branch, so this candidate starts from the
known-working configuration. The candidate plugin was then built against the
exact Nav2 image digest used by the running hotel deployment and tested in an
isolated pod on `ip-10-0-38-113.ec2.internal` in namespace
`semantic-navigation`. Both the controller's local costmap and planner's global
costmap logged `Using plugin "semantic_layer"`; both lifecycle nodes remained
`inactive [2]`. The pod used ROS domain 86, a disconnected velocity topic, and
0.5 CPU/1 GiB requests with 1 CPU/2 GiB limits; it completed successfully with
exit code 0. It started no simulator, activated no Nav2 server, sent no goal,
and issued no navigation command. The exact image/source/config hashes and
captured output are in the [D0 preflight record](validation/semantic-navigation/phase-6-demo/d0-nav2-plugin-preflight-20261020.md).

The first plugin image exposed one integration issue: the known-working Nav2
entrypoint sourced ROS but not the new plugin overlay. The opt-in image build
now sources the semantic workspace after the ROS underlay; the final preflight
asserted both that startup hook and that `ros2 pkg prefix` resolves the plugin
package. This change exists only in the candidate image; the canonical Nav2
deployment remains unchanged.

This closes only the plugin-load subgate. Read-only cluster inspection found
the existing isolated simulator at about **9.5 CPU cores** against a 1-core
request, while its node was at **91% CPU** (14.2 cores). The dedicated 16-core
CPU worker used for preflight was lightly loaded at the sampling time (about
7% CPU requests allocated and 120m observed), but that isolated check does not
prove capacity for Gazebo plus camera, SAM3 inference, and Nav2 together. A
different low-observed-use worker had 80% CPU requests allocated, while other
sampled general workers had 69–88% requested; placement must account for both
scheduler reservations and measured load. D0 remains HOLD until the complete
demo profile's image/model pins, topic/frame mappings, one-simulator/one-robot
topology, and integrated resource/real-time-factor plan are verified. No demo
runtime deployment or navigation command has occurred.

A topology audit found that the known-working Nav2 deployment is
`robot-nav-robot-1` in namespace `ros2-rmf-hotel`; it was not modified. The
isolated `semantic-navigation/semantic-hotel-sim` deployment runs Gazebo,
camera compression, and a ROS-Gazebo bridge, but no Nav2 controller or planner.
It connects to its own `semantic-zenoh-router`. The Phase 6 candidate does not
yet define an isolated Nav2 deployment plus a scoped bridge path for SAM3
outputs back to both Nav2 costmaps and command velocity only to that isolated
simulator. Source topic contracts are known: compressed RGB/depth, calibration,
capture/compression traces, TF, and clock feed SAM3; it publishes
`/robot_1/semantic/{mask,points,timing,label_info,status,ready}`; the costmap
layer consumes mask, points, timing, and labels. The exact cross-pod allowlist,
robot optical-frame/TF availability, and isolated Nav2 launch profile remain
D0 work. An inherited baseline Nav2 warning also reported inflation radius
0.200 m below the computed 0.225 m inscribed footprint radius; this preflight
made no changes to that baseline setting and did not test motion or collision
behavior.

**October 21 D0 completion addendum — DEMO PASS, static preflight only:** the
remaining profile-contract gaps are resolved without deploying a workload. The
isolated candidate router and scoped bridges are defined in
[`phase6-demo-topic-bridges.yaml`](../helm/semantic-navigation/phase6-demo-topic-bridges.yaml);
the full pinned image/model, topic/frame, launcher, and scheduling contract is
recorded in
[`phase6-demo-profile-draft.md`](validation/semantic-navigation/phase-6-demo/phase6-demo-profile-draft.md).
The consolidated gate evidence is in
[`d0-profile-preflight-20261021.md`](validation/semantic-navigation/phase-6-demo/d0-profile-preflight-20261021.md).
The candidate is one simulator/`robot_1` on its own Gazebo partition/router,
with ROS domains 81 (sim), 82 (SAM3), and 87 (Nav2). Simulator, camera
compressor, Nav2/plugin, SAM3 runtime, Zenoh bridge, Zenoh router, and the SAM3
checkpoint revision/hash are pinned; the prompt is fixed to `red mat`. Before
D1, source inspection caught and corrected an incompatible draft runtime pin:
the costmap requires payload hashes, so the profile now uses the Phase 4-tested
payload-bound SAM3 runtime (`478ec…`), not the earlier `e1ed…` runtime. No
workload was deployed with the incompatible pin.

Read-only topic/frame inspection verified compressed RGB/depth, camera info,
capture/compression traces, `/clock`, robot TF, `/robot_1/scan` frame
`robot_1/base_scan/lidar`, odometry frame `odom` → `base_footprint`, and the
static `camera_color_optical_frame`. The candidate preserves the working scan
rewriter and odometry TF relay and deliberately skips the canonical Nav2
entrypoint's duplicate robot-state publisher and initial-pose seed. Semantic
topics use a separate no-namespace bridge so absolute
`/robot_1/semantic/{mask,points,timing,label_info}` arrive unchanged at both
costmaps. All Nav2 publishers are disabled for D1; a separate gated config
allows only `/cmd_vel` on the isolated `robot_1` route for a later motion stage.
No action or RMF command route exists.

The resource proposal places the cloned simulator/Nav2/router group on the
sampled 16-core worker `ip-10-0-38-113` (15.5 cores allocatable, 7% CPU
requests allocated) and SAM3 on `ip-10-0-18-251` (one L40S GPU available).
Combined CPU-node requests are about 13.2 cores. The currently running semantic
simulator used 9,113m CPU against its 1-core request on a node at 89%, so the
candidate must not be co-located with it. `ip-10-0-15-146` is excluded despite
3% observed CPU because it already has 80% CPU requests allocated. D1 will
record real-time factor, inference latency, semantic age, and actual resource
use; D0 makes no performance claim.

Validation passed: 8 topology/bridge tests, 6 parameter tests, all 30 Phase 5
regression tests, `oc apply --dry-run=server` for the router/bridge manifest,
and the isolated plugin-load preflight. D1 has since completed as a stationary
demo smoke pass; its evidence and limits are recorded in
[`d1-stationary-smoke-20261021.md`](validation/semantic-navigation/phase-6-demo/d1-stationary-smoke-20261021.md).
At D0 close, before D2 was started, the Nav2 command bridge remained
unattached and no goal or motion command had been sent; the canonical hotel
deployment was unchanged. D2 was then a separate explicitly gated
paired-navigation step. The inherited 0.200 m
inflation radius vs. 0.225 m inscribed-radius warning remains unchanged and must
be kept visible in any eventual demo assessment.

**October 21 D2 update — three paired trials completed; functional DEMO PASS with evidence caveats:** the initial route-planning contrast was followed by motion only after zero-only delivery was verified on the simulator's `/robot_1/cmd_vel`. The root cause was Zenoh route expiry after Gazebo retired its subscriber; an exact-key, subscriber-only keepalive now preserves that route. Recreating the isolated simulator exposed a stale SAM3 clock/CameraInfo route; refreshing the SAM3 bridge restored fresh RGB-D/calibration/trace joins without weakening freshness checks. A first motion attempt then exposed CPU contention with Gazebo using about 11.4 cores of its 12-core limit while Nav2 shared the node; Nav2 was moved to a separate lightly loaded node. The D2-only Nav2 entrypoint now waits for `/clock`, `/odom`, `/scan_fixed`, and `/tf` samples before lifecycle startup.

Three off/on pairs used the same fixed scene, robot, start/goal, planner/controller, SAM3 prompt, and 0.10 m/s cap. Semantic-off preflights crossed the mat (36 centerline samples); semantic-on preflights routed around it (zero centerline samples). All six goal trials succeeded. Compactly retained pairs 2 and 3 show max odometry and command speed 0.10 m/s, no cap breach, no Collision Monitor events, and about 37–39 s trial duration. Pair 1's terminal success is confirmed in Nav2 logs, but the terminal wrapper did not retain the verbose per-trial summaries. Example fresh on-arm cost-200 counts at preflight were 271/198 and 267/195 (global/local). Full per-trial overlays, robust CPU/RTF sampling, and robot-hull exposure were not retained for all six runs; the D2 record discloses these gaps.

This meets the fixed-scene functional demo objective, not a collision-avoidance or safety objective. The semantic-on path centerline offset was about 0.44 m from the mat center, leaving approximate edge clearance below the 0.22 m robot radius; the staged mat has no reported collision geometry. Do not claim footprint clearance, general SAM3 recognition, statistical benefit, or physical-robot suitability. D2 static profiles continue to bake semantic state at startup because a runtime parameter flip did not reliably remove master-costmap influence. The D2-only profile enables the existing `FootprintApproach` Collision Monitor polygon with its 0.5-second horizon, and keeps Nav2 action/RMF endpoints off the bridge. See the [D2 paired-navigation record](validation/semantic-navigation/phase-6-demo/d2-pre-motion-20261021.md).

**Demo acceptance:** all three pairs are complete and interpretable; no
collision or safety-threshold violation occurs; semantic-on adds a visible
detour in the chosen scene; stale costs clear; and the recorded comparison is
reproducible enough for a clearly labeled staged demonstration. Report path
exposure and runtime descriptively, with no minimum statistical yield, 90%
benefit claim, general recognition claim, or safety qualification. If perception
or semantic costs fail, stop the semantic task and present the unchanged
geometry-only navigation baseline instead; do not represent that fallback as a
semantic-navigation success.

**Evidence and rollback:** store a separate demo report under
`docs/validation/semantic-navigation/phase-6-demo/`, including the exact profile,
source/image/model hashes, fixed prompt, three paired manifests, raw logs and
video links. Disable semantic influence, flush/reset its state, and rerun the
baseline smoke test after the demo. Keep the canonical deployment unchanged.

### Phase 6 Full qualification: demonstrate navigation with and without semantic costs

**Status: HOLD.** This remains the formal Phase 6 gate; the Phase 6D demo-only
result above does not satisfy or replace it. Phase 5 qualification is complete
and its acceptance is recorded (October 26, 2026), so the entry requirement is
satisfied; the Phase 6 gates themselves are HOLD until run under the execution
start note below.

**Work:** enable the verified layer in both maps. Start at ≤0.15 m/s and increase toward the existing 0.35 m/s only after braking, latency, and viewing-distance tests pass at each speed. Keep the same speed in both arms. See the target before dispatch and keep an alternative route available. Do not change RPP, planner, replanning cadence, or map between arms.

**Verification:** run at least 20 paired trials in alternating order for the target scene, plus target-absent, target-removal, and perception-failure cases. Keep camera/inference running in both arms so compute load is comparable. Reset all semantic state between runs using the phase 4 procedure. Measure actual robot-hull exposure to the ground-truth region, not just path-center overlap.

**Pass gate:** 20/20 completions per arm in the controlled nominal scene, no physical collisions, and ≥90% reduction in aggregate target-exposure distance for semantic-on versus semantic-off trials. Baseline exposure must be nonzero; otherwise the scene is inconclusive. Negative-scene completion must not regress. Faults must meet phase 5 stopping criteria. Report path length, completion time, minimum clearance, interventions, and runtime alongside the semantic benefit.

**Evidence and rollback:** paired manifests, metrics, bags, and synchronized camera/mask/costmap/path video. Stop, disable semantic influence, flush state, and repeat the baseline smoke test. Any geometry-only fallback completion is labeled degraded operation, not successful semantic navigation.

**Series tooling (October 23, 2026):** `scripts/semantic-navigation/run_phase6_series.py`
plans and evaluates this series. It emits an alternating paired plan (at least 20
nominal pairs plus target-absent, target-removal, and perception-failure pairs),
computes robot-hull exposure to the ground-truth region from recorded
trajectories using a conservative circumscribed-circle hull sampled at 1 cm,
evaluates the pass gate above (20/20 per arm, ≥90% exposure reduction, nonzero
baseline, negative-scene non-regression, phase 5 fault-stop criteria), and
advances the speed ladder only when braking, latency, and viewing-distance
gates pass. Execution is refused unless a recorded Phase 5 acceptance JSON
covering recovery repeatability, moving fault-stop, moving SAM3
registration/load, and the armed fault matrix is supplied, every trial is
pinned to one Ready GPU-free worker, and the operator confirms the reserved
moving window in the evidence header. Planning (`--plan-only`) is available
for review at any time. This tooling records and evaluates evidence only; it
does not itself qualify navigation or change the Phase 6 HOLD status.

**Execution start (October 26, 2026, user-approved):** Phase 5 acceptance is
recorded at
[`phase-6/phase5-acceptance.json`](validation/semantic-navigation/phase-6/phase5-acceptance.json)
(all four gates 10/10 on the frozen guarded GPU profile, sign-off commit
`d1faa7f`, the five caveats carried forward). The user approved three scoping
decisions: (1) begin with entry records, the semantic-on guarded profile and a
stationary smoke, then pilot pairs before any series; (2) reconcile the
placement contract to the **frozen guarded GPU-rendering profile** (pinned
worker `ip-10-0-44-146.ec2.internal`) — the "GPU-free worker" wording above
predated the GPU-rendering remedy, and a software-rendering placement is not
qualified for motion per the October 23 thread-probe diagnosis and sign-off
caveat 2; `run_phase6_series.py` now refuses execution without
`--gpu-rendering` on the pinned node; (3) the first frozen series runs at
**0.15 m/s only**, with the speed ladder defined and advanced only after that
series passes. Phase 6 gates remain HOLD until run.

**Pilot pair 1 outcome (October 28, 2026, user-accepted):** the pilot pair is
closed with its findings accepted; see
[`phase-6/pilot-1-20261026/README.md`](validation/semantic-navigation/phase-6/pilot-1-20261026/README.md)
for the complete attempt history. In summary: the off arm passed completely
(all 32 checks, baseline hull exposure 1.415 m); the on arm achieved the
semantic objective at this plan's lethal-cost-254 exclusion experiment (hull
exposure 0.000 m — a 100% reduction against the ≥90% gate, hull clearance
~5 cm) while the qualified soft cost 200 produced no route contrast (1.448 m;
the planner only nudged its plan ~0.4 m) — the fork this plan anticipated.
Enabling fixes along the way, each user-approved and recorded: the cyclic-GC
disable, the drain-before-tick reorder, the capture-time TF witness sidecar
(the fixture's own /tf reader saturates at mat-close), and the global-only
semantic-layer candidate (the local map's semantic subscription loaded the
controller's process past its 100 ms command authority). **The mid-route
renewal race is closed** (October 28, 2026, later the same day): the
one-shot admission-scheduling grace (25 ms, once per source, only when the
ledger holds a newer validated source) plus the rotation provenance fix
(the ledger's source record accepts pre-monitor magnitudes; the applied
bounds unchanged) took the on-arm lethal trial to a complete pass —
`pair-1-on-lethal254-grace3`, all 33 checks, `goal_succeeded`, 0.000 m
exposure. A topology creation race (the SAM3 pod's zenoh bridge dialing
before the router listens) was also root-caused and fixed. The
registration degradation on detour views proved lane-specific (99.99% on
the passing detour vs 0.688 on an earlier lane) — sub-cell edge bleed
under the standing Phase 2 recognition waiver, a variance watch item
rather than a blocker. Phase 6 gates remain HOLD pending the series.

This phase is the **first complete SAM3 semantic-navigation demonstration**. Later features are not required to accept it.

### Phase 7 Optional runtime prompt changes

**Entry:** phase 6 passes. Add an operator control limited to approved categories and fixed navigation policy. The Open Navigation node already exposes a prompt-change service, but service acceptance does not prove new results are available. [Prompt-change source](https://github.com/open-navigation/opennav_amd_semantic_navigation/blob/5e82f4a458f9e97ddd92e2cf10feb2c3552295d3/opennav_sam3_inference/opennav_sam3_inference/sam3_node.py).

**Work and verification:** qualify each new prompt through phase 2. Stop motion, begin a new policy generation, reset tracking and semantic buffers, and wait for matching fresh labels/masks before operator-authorized resume. Test 20 alternating changes, rejected prompts, restart during a change, and delayed old-generation results.

**Pass gate:** no old-generation output affects costs, no stale target costs remain, and no motion occurs during the transition. Every category meets phases 2–6 requirements. Log the selected category and policy generation. On failure, restore the last passing fixed prompt, clear state, and rerun its smoke test.

### Phase 8 Optional RMF integration

**Entry:** phase 6 passes; phase 7 is needed only if dynamic prompts are included.

**Work and verification:** first dispatch the same single-floor semantic task through RMF without changing the navigation model. Verify itinerary handling for detours, task correlation, cancel, and truthful fault/completion status. Require 10/10 nominal single-floor tasks plus passing cancellation/fault tests before attempting lifts. Then test floor switching as a separate subgate: stop, clear old floor/model state, switch maps/localization, confirm fresh TF and observations, and resume.

**Pass gate:** no bypass of RMF traffic authority, no old-floor costs after a switch, and no task reported complete after semantic failure. Require 10/10 representative multi-floor round trips and passing interrupted-transition tests before presenting multi-floor semantic capability. Evidence includes RMF task IDs, trajectories, map/policy transitions, and stop/restart logs. Roll back to the accepted single-floor demonstration if either subgate fails.

## ONNX implementation branch

ONNX is an explicit alternative, not an automatic recovery from any SAM3 failure. Camera registration, costmap clearing, and safety failures must be fixed in the shared pipeline; changing models does not fix them.

Stages O0–O3 run in order with the same report/sign-off rule. Reuse passing phase 0 baseline and phase 1 sensor evidence only when those artifacts are unchanged; otherwise repeat the affected shared gates. SAM3 recognition does not need to pass before qualifying an ONNX model.

| ONNX stage | Implementation and verification | Gate and rollback |
|---|---|---|
| O0 Select an artifact | Run the documented reference example if needed; inventory licensed indoor checkpoints and their actual label sets; verify preprocessing, input/output shapes, CPU provider, artifact hash, and memory | A reproducibly runnable model contains the target category. The outdoor example passing is not hotel acceptance. If no suitable artifact exists, hold for a separate training decision |
| O1 Qualify recognition | Run the same frozen hotel evaluation set and phase 2 scoring. If training is approved, separate training/development/test scenes and record dataset/model provenance | Meet phase 2 thresholds without using test images for training or prompt/model selection. Otherwise retain the last accepted SAM3 configuration or hold |
| O2 Implement the adapter | Use the same backend request/response envelope and mask/label/status contract; document whether confidence is per-pixel probability/logit-derived and calibrate separately | Pass phase 3 backend conformance, throughput, timing, pairing, and fault tests, plus phase 4 projection/lifecycle regression. Preserve selected runtime provider in evidence |
| O3 Compare navigation | Repeat phases 5–6 with the ONNX runtime and shared profile. Keep hardware allocation fixed when comparing efficiency, or disclose hardware differences | Pass the same navigation and stop gates. Report accuracy, latency, CPU/GPU/memory, and path outcomes; do not claim equivalence from matching label names |

The tutorial node assumes a particular preprocessing and output contract; the adapter must accommodate the selected checkpoint rather than merely changing a filename. [ONNX inference source](https://github.com/ros-navigation/navigation2_tutorials/blob/3578fa26feb2b303b7d370591c6b7dc8a7304762/nav2_semantic_segmentation_demo/semantic_segmentation_node/semantic_segmentation_node/segmentation_node.py).

SAM3-assisted annotations could reduce later labeling effort, but require human review and an independent evaluation set. No custom model training is authorized or required by this proposal. Also, SAM3's optimized implementation can itself contain ONNX artifacts: the distinction here is **promptable SAM3 versus a fixed-category model**, not two mutually exclusive file formats.

## Planned repository deliverables

These are proposed implementation targets, not files or commands already created:

| Area | Work |
|---|---|
| Robot/simulation | Extend [SDF generator](../scripts/patch_hotel_world_add_robot.py), [URDF](../scripts/turtlebot3_waffle.urdf), and simulator bridge; add isolated target-scene assets |
| Inference | New package under `apps/semantic-perception/` with a ROS-independent model runner, versioned backend schema, selected SAM3 adapter, policy normalization, health/status, bounded queues, and conformance tests; ONNX adapter under stages O0–O3 |
| Navigation | Opt-in [`phase6-demo-nav2-candidate.yaml`](../helm/semantic-navigation/phase6-demo-nav2-candidate.yaml), rendered from the existing hotel parameters; preserve canonical parameters; verify plugin load before any demo motion |
| Deployment | New inference Containerfile and opt-in Helm values/templates; explicit accelerator requests, node placement, storage, and narrow network access |
| Transport | Update [per-robot bridge template](../helm/multi-robot-demo/templates/configmap-zenoh.yaml) and Gazebo routes; verify actual rendered namespace/topic mappings |
| Verification | New scripts under `scripts/semantic-navigation/` for replay, mask metrics, backend serialization and test-double faults, projection assertions, paired navigation runs, and phase reports |
| Review | Phase evidence under `docs/validation/semantic-navigation/`, with artifact links and pass/fail records |

Use least-privileged workload permissions, offline/cached weights, versioned configurations, and readiness distinct from process liveness. Keep inference restart independent of Nav2 and require an explicit readiness handshake before semantic tasks can resume.

### Deferred OpenShift AI implementation

The [OpenShift AI serving proposal](semantic-navigation-openshift-ai-serving-proposal.md) covers a custom vision-model server, remote transport adapter, `ServingRuntime`/`InferenceService` configuration, accelerator placement, authentication, and operational verification. These are deferred deliverables. The current implementation supplies the reusable model runner, stable contract, and conformance tests needed for that work.

OpenShift AI documents custom serving runtimes and KServe resources; this provides a plausible deployment path, not a turnkey or verified SAM3 integration. Serving a segmentation model is not an OpenAI-compatible chat endpoint substitution. [OpenShift AI serving architecture](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/configuring_your_model-serving_platform/configuring-your-model-serving-platform_rhoai-admin).

Moving the same model to an on-premises OpenShift AI service does not itself require fine-tuning, but introduces network and serving latency. Require offline output qualification and repeat phases 3–6 before enabling remote results for navigation. Keep all existing freshness and stop thresholds unless a separately reviewed change is justified and revalidated. An on-premises service is still remote from the robot's sensor pipeline.

## Review outcome requested

Proceed with phases 0–6 using SAM3, one fixed category, and no fine-tuning. Include backend separation and conformance tests now; implement OpenShift AI serving only through the separate, later proposal. Preserve ONNX stages O0–O3 as the alternative path. Runtime prompts and RMF/multi-floor integration are optional gated extensions, not prerequisites for proving semantic navigation.

Phase 0 is complete with reviewer sign-off. Its technical gate verified a reproducible hotel baseline, L40S availability, local original-SAM3 inference, finite outputs, CUDA memory use, and a second successful startup with HF access disabled. It did **not** verify hotel-scene recognition: the upstream smoke image yielded no masks for `floor mat` or `person` at the default 0.5 threshold. Phase 1 sensor gates passed in the isolated `semantic-navigation` project and were reviewer-approved October 13, 2026. Phase 2 is **PASS WITH USER-APPROVED DEMO WAIVER** for progression only: the isolated depth-20 camera pairer/Zenoh/receiver path passed the proposed throughput and pairing thresholds, including a 600-second run, while the canonical deployment remained unchanged. The 31 additional development labels and held-out 50-positive/50-negative recognition evaluation remain deferred; their recognition metrics are not measured or passed. Corrected direct-Gazebo-pose captures validate the RGB-D/pose label path across translation and rotation. Reviewer JZ approved the original nine development labels on October 15, 2026. A development-only prompt sweep on those eight positives/one negative improved recall from 4/8 for `red floor mat` to 7/8 for `red mat`; three severe-occlusion views in one episode were recovered but one approximately 24%-visible view remained missed, and the recovered scores were near the 0.5 threshold. This establishes prompt sensitivity, not generalization or a supported visibility cutoff. A curated 40-row development review manifest has 20 positives and 20 negatives across six episodes and passes structural validation. The user separately approved the narrow Phase 6D simulation-demo waiver on October 20, 2026; it permits only the fixed-scene, fixed-prompt, isolated demo described above. It does not complete held-out recognition review or authorize broader navigation use.

**October 20 moving-trace root cause and demo decision:** a diagnostic-only
moving trace reproduced a 53.150 ms checked-output gap. The direct mechanism was
a 51.986 ms Collision Monitor wait for the exact current-time base transform;
the needed transform arrived 44.993 ms into lookup after a 55.638 ms odometry
receipt gap. Post-run telemetry showed high shared-node CPU use, making
contention a credible contributor but not proving event-time causality. The
user elected to proceed with the bounded staged-demo path rather than block on
full Phase 5 qualification. Do not change exact-time TF, freshness, or stop
thresholds to conceal this issue. The moving trace remains a failed qualification
result; it is not evidence of a demo pass. See the linked Phase 5 report above.

**October 19 TF-loss update:** the private TF-loss subgate now passes using two complementary tests: AMCL publisher outage with an earlier command-watchdog stop permitted, and selective TF delivery loss to the supervisor with `tf_stale` required. Both retain the normal thresholds and require actual post-injection missing-transform evidence, native zero, cancellation, stationarity, and no automatic restart after TF returns. The earlier 30 Hz trial never injected TF loss: command expiry stopped it first, and a capture-clock fault later prevented stationary verification despite completed cancellations. The earlier 50 ms override has been removed. See the [current qualification](validation/semantic-navigation/phase-5/runtime-report.md#october-19-tf-loss-subgate-pass-in-the-private-geometry-only-fixture) and [historical investigation](validation/semantic-navigation/phase-5/runtime-report.md#october-18-tf-loss-fault-injection-investigation-not-yet-qualified). Overall Phase 5 remains HOLD for its other outstanding items.

**October 18 Phase 5 recovery update:** a private, explicit recovery-profile probe
now permits only the actual Nav2 BackUp and Wait BT children. The bounded
reverse-to-zero handoff is verified: independently applied motion must be within
0.005 m/s before exact-zero normalization; only zero leases may then be renewed
while the owned Wait remains active, with sensor freshness and the native
watchdog still live. The applied-zero Wait subgate passed in two retained
trials: recovery-10 recorded 332 holds (7.40 ms maximum gap) and 205 native
applied-state samples at exactly zero after the first hold; recovery-13 recorded
349 holds (9.58 ms maximum gap) and 196 zero applied-state samples. Backup and
Wait succeeded in both. However, recovery-enabled FollowPath is not repeatable:
the 0.5 m recovery-10 task returned success, while recovery-13 (actually a
different 0.35 m target, not an identical repeat) expired the
native lease before terminal success; a 0.25 m task returned success without
meeting the independent physical-motion threshold. This remains a Wait-handoff
subgate only, **not** a repeatable recovery-enabled navigation pass. The full
Phase 5 gate remains HOLD; resolve downstream FollowPath/lease repeatability,
then continue the remaining physical fault-stop, moving-SAM3, and armed semantic-fault-matrix
qualification. No canonical deployment or semantic motion policy was changed.
