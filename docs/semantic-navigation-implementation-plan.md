# Semantic navigation implementation plan

Date: October 13, 2026. Status: proposed implementation; all phase gates are pending.

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

Start with SAM3, not an unqualified mix of SAM3 and SAM3.1 checkpoints or exports. The upstream repository contains both versions; pin the model and compatible code explicitly. Measure memory demand instead of promising a GPU size from model parameter count. Model access and license acceptance are phase 0 prerequisites. [Upstream version and access guidance](https://github.com/facebookresearch/sam3).

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

The semantic plugin consumes aligned masks/clouds and label metadata; inference remains external. Its optional-confidence behavior and clearing risks require tests below. [Layer interface](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/README.md), [implementation](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/src/semantic_segmentation_layer.cpp).

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

Each phase requires a stored report with `PASS`, `FAIL`, or `HOLD`, the exact inputs/configuration, raw evidence, measured values, and reviewer sign-off. **Do not activate the next phase until all mandatory checks pass.** Phase status is currently pending; a documented test is not an executed test.

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

**Work:** add an RGB-D sensor to the robot SDF, matching URDF camera/optical frames, and Gazebo-to-ROS bridges. Extend the rendered per-robot Zenoh allowlists for the required data. Build the mat scene and record robot-perspective views while autonomous commands are inhibited. Select sensor resolution/rate after verifying the runtime's input requirements.

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

### Phase 4 Verify projection and semantic map lifecycle

**Work:** load the semantic layer into isolated test costmaps, with robot motion inhibited. First feed deterministic synthetic masks/clouds, then the phase 3 model output. Synthetic inputs verify integration only; they are not AI results. Fix or select a layer revision that passes lifecycle tests before proceeding.

**Verification:** assert exact costs on a small known grid; test maximum merging against occupied and unknown geometric cells. Test target removal, observation expiry, clear/reset, deactivate/reactivate, rolling-window motion, out-of-order data, and simulation clock reset. Inspect the layer's raster and observation buffers, not only its visible overlay.

Delay an inference result across a reset and verify it cannot repopulate cleared costs. Invalidate pending requests whenever clearing establishes a new observation epoch; only captures from the new epoch may rebuild the map.

**Pass gate:** every deterministic test passes. Expired or explicitly cleared target observations cannot reappear without a fresh observation; static obstacles remain occupied. For a configured observation lifetime T, obsolete semantic cells disappear by T plus two measured costmap update periods. An explicit reset clears both raster and temporal state. Capture-to-costmap p95 age is ≤300 ms in the live path.

**Evidence and rollback:** automated grid assertions, before/after maps, lifecycle logs, selected plugin commit and any patch tests. Keep semantic layers disabled outside the isolated test profile. Restart the test process to remove stale state if rollback requires it; an `enabled: false` toggle alone is not proof of clearing.

### Phase 5 Validate the shared navigation and stop configuration

**Work:** establish a common single-floor safety profile: verified robot footprint, geometric layers, final command routing, collision intervention, and watchdog. The canonical hotel configuration disables global obstacle/inflation layers for lift handling and disables its configured approach polygon, so do not assume these are already suitable. Apply any corrections equally to baseline and semantic arms. [Existing parameters](../config/nav2/hotel_nav2_params.yaml).

**Verification:** first run RPP with semantics excluded and prove collision intervention, cancel, restart, and command expiry. Next run perception in observation-only mode during baseline motion to verify registration under motion and its effect on compute/network load. Inject camera loss, TF loss, stale masks, and a hung inference process while the semantic-task supervisor is armed but costs remain excluded.

Use the test backend to simulate remote-style timeout, overload, and connection loss without deploying remote serving. Confirm these failures follow the same stop path as local inference failure, and that a late successful response cannot authorize automatic resume.

**Pass gate:** 10/10 baseline trials complete without collision; all fault tests stop motion and expose a reason. Initial stale-input trigger is 500 ms, monitored using capture age and a wall-clock heartbeat; the final command becomes zero within 100 ms of the trigger. Independently measure physical stopping distance after command zero. Verify every velocity-producing path, including recoveries, passes through the same guard. No automatic motion resume after a fault.

**Evidence and rollback:** baseline trajectories, final-command and physical-stop traces, footprint review, controller timing, and fault results. Revert to the last passing shared profile with semantics off. Stop before reverting a profile on a moving robot.

### Phase 6 Demonstrate navigation with and without semantic costs

**Work:** enable the verified layer in both maps. Start at ≤0.15 m/s and increase toward the existing 0.35 m/s only after braking, latency, and viewing-distance tests pass at each speed. Keep the same speed in both arms. See the target before dispatch and keep an alternative route available. Do not change RPP, planner, replanning cadence, or map between arms.

**Verification:** run at least 20 paired trials in alternating order for the target scene, plus target-absent, target-removal, and perception-failure cases. Keep camera/inference running in both arms so compute load is comparable. Reset all semantic state between runs using the phase 4 procedure. Measure actual robot-hull exposure to the ground-truth region, not just path-center overlap.

**Pass gate:** 20/20 completions per arm in the controlled nominal scene, no physical collisions, and ≥90% reduction in aggregate target-exposure distance for semantic-on versus semantic-off trials. Baseline exposure must be nonzero; otherwise the scene is inconclusive. Negative-scene completion must not regress. Faults must meet phase 5 stopping criteria. Report path length, completion time, minimum clearance, interventions, and runtime alongside the semantic benefit.

**Evidence and rollback:** paired manifests, metrics, bags, and synchronized camera/mask/costmap/path video. Stop, disable semantic influence, flush state, and repeat the baseline smoke test. Any geometry-only fallback completion is labeled degraded operation, not successful semantic navigation.

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
| Navigation | New `config/nav2/hotel_nav2_semantic_params.yaml` and explicit profile selection; preserve canonical parameters; pin/test semantic-layer patches |
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

The first implementation checkpoint is phase 0: a reproducible baseline and a working SAM3 runtime on verified hardware. Until that passes, no assumption about cluster GPU availability, achieved frame rate, or successful hotel recognition is accepted.
