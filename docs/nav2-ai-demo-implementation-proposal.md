# Nav2 AI integration research and demo proposal

Research date: October 12, 2026. Implementation direction updated October 13, 2026. Status: proposal for review, not an implemented or benchmarked integration.

## Recommended direction

Build two independent, single-floor experiments on the hotel robot:

1. **Semantic navigation:** retain NavFn and Regulated Pure Pursuit (RPP), add registered RGB-D perception, and compare the same route with semantic costs disabled and enabled. Start with pretrained SAM3 and one fixed prompt to avoid beginning with custom training. Retain a fixed-category ONNX model as the alternative; the tutorial's outdoor checkpoint is not a hotel-floor classifier.
2. **Learned control:** retain the robot, task, localization, planner, sensors, and common safety configuration, then compare RPP with the third-party NeuPAN controller. Train or validate the geometry-specific DUNE checkpoint and establish runtime deadlines before adding RMF or lifts.

The October 13 [semantic navigation implementation plan](semantic-navigation-implementation-plan.md) defines the authoritative phase gates for both model options. SAM3 recognition and runtime must pass before enabling navigation influence; changing prompts at runtime is a later optional phase. Neither experiment needs an LLM or Nayantra in its navigation loop. Keep the existing multi-floor demonstration intact until these experiments pass their own acceptance tests.

The main integration risks are concrete: missing camera transport, semantic-map clearing, mismatched robot geometry, and controller frame handling. Successful upstream videos do not establish that these are resolved for our deployment.

## Existing examples and what they establish

| Integration | Reusable example | What it establishes | Fit for this demo |
|---|---|---|---|
| Fixed-class segmentation with ONNX Runtime | [Official Nav2 tutorial](https://docs.nav2.org/jazzy/tutorials/general_tutorials/navigation2_with_semantic_segmentation/navigation2_with_semantic_segmentation/) and [tutorial packages](https://github.com/ros-navigation/navigation2_tutorials/tree/3578fa26feb2b303b7d370591c6b7dc8a7304762/nav2_semantic_segmentation_demo) | Baylands world, TurtleBot4, supplied sidewalk/grass/background checkpoint, CPU inference option, semantic costmaps | Alternative with simpler runtime; hotel deployment needs appropriate labels/model |
| Text-prompted segmentation with SAM3 | [Open Navigation implementation and videos](https://github.com/open-navigation/opennav_amd_semantic_navigation/tree/5e82f4a458f9e97ddd92e2cf10feb2c3552295d3) and [Nav2 tutorial](https://docs.nav2.org/rolling/tutorials/general_tutorials/navigation2_with_sam3_semantic_segmentation/navigation2_with_sam3_semantic_segmentation/) | Outdoor terrain and indoor office demonstrations, with runtime text-defined segmentation | Selected first path to test recognition without fine-tuning; accelerator and runtime compatibility are initial gates |
| NeuPAN algorithm | [Paper](https://arxiv.org/abs/2403.06828v4), [author videos](https://hanruihua.github.io/neupan_project/), and [examples](https://github.com/hanruihua/NeuPAN/tree/main/example) | Learned/model-based planning with simulation and real robots, including differential-drive examples | Evidence for the algorithm, not proof of this Nav2 wrapper on our TurtleBot |
| NeuPAN inside Nav2 | [Controller plugin](https://github.com/LihanChen2004/nav2_neupan_controller/tree/acf2f05ea4efef9dac1a9ebb86b37c10477387f6) | Actual `nav2_core::Controller` implementation; README reports Jazzy/Python 3.12 testing, shows Ackermann demo, and leaves differential/omni demos pending | Appropriate experimental interface, with source-audit issues to resolve first |

ONNX is a model format/runtime choice, not a model architecture. The tutorial lists architectures such as U-Net, DDRNet, and SegFormer as examples; that does not identify its checkpoint as any one of them. SAM3 is a promptable segmentation foundation model. NeuPAN is a specialized motion-planning system, not a vision-language-action model or a general language model.

## Our actual baseline

The canonical federated deployment is selected by [the Makefile](../Makefile) and [hotel values](../helm/multi-robot-demo/values-hotel-nav2.yaml). It separates Gazebo, robot navigation, RMF, and Zenoh. The relevant Nav2 image is built through [Containerfile.nav2](../Containerfile.nav2), inheriting the canonical Jazzy hotel image; historical Lyrical and SLAM experiments are not the baseline for this proposal.

| Area | Repository configuration | Consequence |
|---|---|---|
| Navigation | RPP at 20 Hz, desired speed 0.35 m/s; NavFn with A* enabled | Keep both unchanged for the semantic A/B test |
| Local map | 4 × 4 m rolling map, 0.05 m cells, radius 0.22 m; LiDAR voxel layer and inflation | Camera semantics must augment geometric observations |
| Global map | Static layer; obstacle and inflation layers explicitly disabled for lift-corridor handling | Do not assume the hotel profile is a general obstacle-avoidance benchmark |
| Command limits | Smoother max `[0.5, 0, 0.8]`, min `[-0.2, 0, -0.8]`; RPP reversing disabled | Use a common documented motion envelope for controller comparison |
| Collision monitor | Only configured approach polygon has `enabled: false` | Node presence does not establish an active independent collision intervention |
| Camera | Canonical robot definition and Gazebo bridge provide no RGB-D perception pipeline | The GUI follow-camera is not the robot sensor required by the semantic layer |
| Nav2 resources | Hotel values request 1 CPU/1 GiB and limit 2 CPU/2 GiB; no accelerator request | Neither SAM3 nor NeuPAN is demonstrated to fit the current allocation |

Sources: [Nav2 parameters](../config/nav2/hotel_nav2_params.yaml), [robot SDF generator](../scripts/patch_hotel_world_add_robot.py), [simulator entrypoint](../entrypoints/entrypoint-hotel-sim-federated.sh), [federated Nav2 entrypoint](../entrypoints/entrypoint-nav2-federated.sh), and [deployment template](../helm/multi-robot-demo/templates/deployment-nav2.yaml). These are source settings, not a fresh inspection of the running cluster.

Create a separate single-floor evaluation profile. Validate its common footprint, global geometric layers, velocity limits, collision monitor, and command watchdog with RPP first. Apply those same settings to every experimental arm. Keep results from this normalized profile distinct from an unchanged hotel-baseline run; otherwise a shared safety correction could be mistaken for an AI improvement.

## Semantic navigation solution

### Sensor and inference pipeline

Add a forward/downward-looking RGB-D sensor to `robot_1` in Gazebo, with a matching camera mount and optical-frame transform in the URDF. Confirm that its view contains the floor far enough ahead to replan or stop. Use simulator depth initially; adding learned monocular depth would introduce a second model and a scale/alignment problem.

The processing chain should be RGB image to segmentation, combined with a pixel-aligned organized point cloud, then a semantic costmap layer in Nav2. The available plugin is `semantic_segmentation_layer::SemanticSegmentationLayer`. It consumes a class-ID mask, aligned cloud, label metadata, and optionally a confidence image. It does not run the neural network itself. [Layer interface](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/README.md).

Proposed integration contracts:

| Data | Contract to verify |
|---|---|
| RGB and calibration | `sensor_msgs/Image` plus `CameraInfo`; correct optical frame and sensor capture time |
| Registered cloud | `sensor_msgs/PointCloud2`; one point per mask pixel in the same order, valid depth or explicit invalid values |
| Label mask | `mono8`, integer IDs, not a colored overlay; nearest-neighbor resizing when necessary |
| Confidence | ONNX confidence map is `mono8`, 0–255; do not silently equate missing confidence with calibrated certainty |
| Label metadata | `vision_msgs/LabelInfo`, reliable/transient-local; stable class-to-cost policy |
| Timing and TF | Preserve capture timestamps through inference; transform observations at capture time; all ROS nodes use simulation time |

RGB quality alone is insufficient: an accurately classified pixel with invalid depth cannot be projected into this costmap. Test depth coverage of flat and thin targets before choosing the demonstration object.

For the first implementation, isolate SAM3 inference in a separately budgeted workload on verified accelerator hardware. Use a sidecar only when its placement is compatible with the simulator and resource isolation. Carry aligned masks, optional confidence, metadata, and cloud to the Nav2 pod. Measure image/cloud bandwidth and downsample the cloud and masks together if necessary. Keep debug video out of the critical transport path. The ONNX alternative can use a CPU sidecar close to image production after its runtime is qualified.

Update both the Gazebo bridge and the **rendered per-robot Zenoh allowlists** in [configmap-zenoh.yaml](../helm/multi-robot-demo/templates/configmap-zenoh.yaml), plus [gazebo-bridge.json5](../helm/multi-robot-demo/files/gazebo-bridge.json5). Editing only the legacy `files/nav2-bridge.json5` would miss the per-robot configuration used by the current template. Preserve robot namespacing, label durability, and late-joiner behavior; do not expose all DDS topics as a shortcut.

### ONNX alternative without overstating model readiness

If evaluating the ONNX alternative, reproduce the supplied Baylands/TurtleBot4 example in an isolated environment as needed. This is not a prerequisite for the selected SAM3 path. The documented launch is `ros2 launch semantic_segmentation_sim segmentation_simulation_launch.py`. Use the Jazzy semantic-layer branch, a pinned tutorial revision, and CPU ONNX Runtime. Keep this reproduction separate from claims about hotel navigation. The reference tutorial uses a simplified static map-to-odom transform; our hotel trial should retain its localization path. [Tutorial](https://docs.nav2.org/jazzy/tutorials/general_tutorials/navigation2_with_semantic_segmentation/navigation2_with_semantic_segmentation/).

Next use a broad, visually distinctive floor mat or surface patch in a spacious L1 area. It should be traversable geometrically, with an unobstructed route around it. Keep the same geometry and map in both arms. Do not add an invisible collision obstacle or a prepainted occupancy restriction to make the semantic arm appear successful.

For an indoor fixed-category demonstration, look for a suitable pretrained model first. If none qualifies, training/fine-tuning a compact model for categories such as `floor`, `restricted_mat`, and `background` becomes a separately scoped decision, followed by ONNX export and validation. Collect representative camera views, distances, lighting, and occlusion. Split training and evaluation by scene/layout, not neighboring frames. A manually generated or simulator-ground-truth mask is useful for testing projection, but must be labeled as a plumbing test, not AI perception. Replacing the names in the outdoor ontology does not teach its checkpoint indoor categories.

The tutorial node loads its model and ontology from package-share paths and assumes RGB ImageNet normalization, input name `input`, and class logits shaped `[1,C,H,W]`. It preserves the incoming header. It also uses a depth-10 default image subscription, so verify compatibility with a best-effort camera and bound queued frames. A replacement checkpoint needs an explicit preprocessing/output contract; arbitrary ONNX files are not drop-in equivalents. [Inference source](https://github.com/ros-navigation/navigation2_tutorials/blob/3578fa26feb2b303b7d370591c6b7dc8a7304762/nav2_semantic_segmentation_demo/semantic_segmentation_node/semantic_segmentation_node/segmentation_node.py).

### Cost policy and planner behavior

Retain static/geometric obstacle protection. Add semantic costs to **both global and local maps**, before inflation, using `combination_method: 1` for maximum merging. This prevents a traversable semantic label from lowering an existing lethal obstacle. Confirm unknown-space behavior separately. [Merge implementation](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/src/semantic_segmentation_layer.cpp).

Suggested experiment policy, subject to calibration:

- Floor contributes no additional cost; it does not erase geometric obstacles.
- The target surface contributes a soft penalty, initially 200 on Nav2's cost scale. Tune against the alternative route and record the selected value.
- A separate variant uses lethal cost 254 to demonstrate exclusion rather than preference. Keep it distinct from the soft-cost result.
- Background/no detection contributes no new terrain assertion, not proof of free space. When reliable semantics are required for the task, stale or insufficient perception pauses the task rather than silently declaring the target absent.

RPP follows a supplied path and checks collisions; it is not an optimizer that independently routes around a low-cost semantic patch. Make the semantic evidence available to the global planner, with a fixed replanning policy in both arms. A local-only soft layer can produce a compelling overlay but little route change. Nav2 distinguishes path-following RPP from obstacle-avoiding controllers such as DWB and MPPI. [Nav2 plugin guidance](https://docs.nav2.org/jazzy/configuration_and_development/first_time_robot_setup_guide/navigation_plugins/setup_navigation_plugins/).

Do not use this perception experiment as the sole enforcement of a real prohibited area. A mandatory restriction needs an independently specified keepout policy and appropriate system safety measures. Its deterministic restriction should not be fed to only one arm of a test claiming to isolate semantic perception.

### Source audit issues to resolve

The inspected Jazzy layer has two important lifecycle risks. `updateBounds()` purges expired observation queues but does not visibly clear the old raster cells belonging to removed tiles. `reset()` resets the raster maps without explicitly emptying the semantic tile buffers. This suggests stale costs after decay, or costs reappearing after a clear. These are static-code findings requiring a ROS reproduction, not measured failures. Test removal, timeout, reset, and reactivation before trusting either A/B resets or dynamic prompts. [Layer source](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/src/semantic_segmentation_layer.cpp), [tile-buffer source](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/include/semantic_segmentation_layer/segmentation_buffer.hpp).

Also verify these interfaces rather than relying on topic presence:

- Pixel correspondence, image row layout, valid XYZ values, and geometric alignment throughout projection. The buffer iterates image pixels and cloud points together; equal element counts do not prove correspondence. [Projection source](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/src/segmentation_buffer.cpp).
- Capture-to-costmap age and pairing under slow inference. Start with a single synchronized RGB-D sensor, bounded queues, and an explicit stale-data watchdog.
- Label startup and class-policy consistency, plus a negative test in which a confidently mislabeled floor pixel overlaps a known obstacle.

### SAM3 first with fixed and runtime categories

Begin the selected SAM3 implementation with a fixed validated prompt such as a particular floor mat. Keep the camera, projection layer, scenario, planner, and controller common to both model options. Only after the fixed-prompt navigation gates pass, optionally demonstrate changing to a second visible category. A detected wet-floor sign identifies the sign, not the extent of a wet region: expanding its mask into a restricted area would be a separate explicit policy.

The Open Navigation node provides `~/change_prompt`, `~/label_mask`, and `~/label_info`. Its source warns that a prompt update takes effect on subsequent frames. Add a policy adapter that maps authorized prompts into stable navigation labels, rather than assuming arbitrary new label names already have costs. Pause navigation, change the prompt, flush old tracking and semantic state, wait for fresh correctly mapped observations, then resume. [SAM3 node](https://github.com/open-navigation/opennav_amd_semantic_navigation/blob/5e82f4a458f9e97ddd92e2cf10feb2c3552295d3/opennav_sam3_inference/opennav_sam3_inference/sam3_node.py).

The published Strix Halo measurements report 154.6 ms for one prompt with detection every frame, versus 103.8 ms with periodic detection and tracking; four prompts report 305.6 and 211.3 ms respectively. Those are author-reported results on their hardware, not budgets for our cluster or end-to-end navigation latency. [Benchmark table](https://github.com/open-navigation/opennav_amd_semantic_navigation/blob/5e82f4a458f9e97ddd92e2cf10feb2c3552295d3/README.md).

The reference setup installs ROCm/MIGraphX, builds model artifacts, and uses a separate Python environment. Treat porting to our OpenShift accelerator/runtime as a work item, not a generic CPU installation. Provision licensed model access and pin artifacts before deployment; do not download weights during demo startup. [Setup instructions](https://github.com/open-navigation/opennav_amd_semantic_navigation/blob/5e82f4a458f9e97ddd92e2cf10feb2c3552295d3/opennav_sam3_setup/README.md).

SAM3's public output contract does not include the ONNX node's per-pixel confidence image. When confidence is omitted, the semantic layer synthesizes maximum confidence. Therefore, calibrate the detector threshold and temporal policy independently; an identical costmap confidence setting does not imply equivalent uncertainty handling. [SAM3 interfaces](https://github.com/open-navigation/opennav_amd_semantic_navigation/blob/5e82f4a458f9e97ddd92e2cf10feb2c3552295d3/README.md), [layer confidence handling](https://github.com/kiwicampus/semantic_segmentation_layer/blob/cf85d3e499af4d389f2aac31e6c8409b424fa417/src/semantic_segmentation_layer.cpp).

## Learned controller solution

### Model and integration boundary

NeuPAN combines a learned distance representation with optimization-based motion planning. Its DUNE component uses a robot-geometry-dependent neural encoder; the implementation includes an MLP over obstacle points. This is not simply a pretrained velocity policy that can be moved between arbitrary robot sizes. [Paper](https://arxiv.org/abs/2403.06828v4), [DUNE implementation](https://github.com/LihanChen2004/NeuPAN/blob/145ed48cb34cac804b2308eb0f42da081037f550/neupan/blocks/dune.py), [network implementation](https://github.com/LihanChen2004/NeuPAN/blob/145ed48cb34cac804b2308eb0f42da081037f550/neupan/blocks/obs_point_net.py).

Use `nav2_neupan_controller::NeuPANController` under the existing `FollowPath` plugin ID in an alternate configuration, with `robot_type: diff`. Keep RPP in a separate launch profile for clean runs; do not switch controllers halfway through a scored trial. The wrapper embeds Python in `controller_server` and its installation instructions select the maintainer's NeuPAN fork. Pin the wrapper and that fork together rather than assuming upstream and fork are interchangeable. [Wrapper instructions](https://github.com/LihanChen2004/nav2_neupan_controller/blob/acf2f05ea4efef9dac1a9ebb86b37c10477387f6/README.md).

Crucially, this wrapper extracts **costmap cells with costs 253 or 254**, ignoring unknown cells and lower soft costs. It does not feed raw LiDAR point clouds to NeuPAN. Our experiment therefore evaluates the Nav2/costmap integration, not the paper's complete direct-point pipeline. It also cannot directly optimize a soft semantic penalty of 200. Keep semantics off in the controller comparison. [Obstacle extractor](https://github.com/LihanChen2004/nav2_neupan_controller/blob/acf2f05ea4efef9dac1a9ebb86b37c10477387f6/src/obstacle_extractor.cpp).

### Establish the robot geometry before training

The canonical SDF body is a 0.28 × 0.31 m rectangle centered at x = −0.032 m. Its body-only XY bounds are therefore x = [−0.172, 0.108], y = [−0.155, 0.155]. The rear corner is approximately 0.232 m from the origin, already beyond the configured 0.22 m radius. These calculations flag a footprint audit; they are not a complete validated robot hull. Include wheels, collision geometry, any camera mount, frame offsets, and a documented margin. [SDF generator](../scripts/patch_hotel_world_add_robot.py), [URDF](../scripts/turtlebot3_waffle.urdf), [Nav2 radius](../config/nav2/hotel_nav2_params.yaml).

Create one agreed convex polygon in `base_footprint` coordinates. Use it consistently for Nav2, collision monitoring, DUNE training, and independent clearance measurement. Rerun the RPP baseline with that same geometry before comparing NeuPAN. Otherwise a smaller NeuPAN footprint could look like improved narrow-passage performance merely by accepting more risk.

The supplied differential-drive training example is **1.6 × 2.0 m**, not our robot. Its checkpoint must not be reused by just changing the YAML dimensions. Generate geometry-specific training samples, hold out boundary/corner points for distance-error validation, and record the polygon, sampling range, seed, checkpoint hash, and error distribution. [Training configuration](https://github.com/LihanChen2004/NeuPAN/blob/145ed48cb34cac804b2308eb0f42da081037f550/example/dune_train/dune_train_diff.yaml), [upstream training guidance](https://github.com/hanruihua/NeuPAN#dune-model-training).

Require a valid checkpoint before lifecycle configuration. Missing weights can enter the DUNE training/prompt path; training must be a separate offline job, never an accidental controller-startup operation. [Checkpoint-loading implementation](https://github.com/LihanChen2004/NeuPAN/blob/145ed48cb34cac804b2308eb0f42da081037f550/neupan/blocks/dune.py).

### Wrapper hardening gates

These source findings must be addressed or explicitly disproved by targeted tests before scored motion:

| Finding | Required test or change |
|---|---|
| Path handler transforms the path to the local costmap frame, but the controller caches its recovery goal from the original input path | Test non-identity `map → odom`; ensure robot state, obstacles, normal path, and recovery goal use the same frame |
| A path-transform exception returns the original path | Reject an untransformable path instead of interpreting its coordinates in another frame |
| The wrapper ignores the supplied measured velocity and goal-checker pointer; Python executes synchronously | Verify acceleration behavior, final heading, cancellation, goal completion, and deadline failures end to end |
| Output clamps are symmetric, whereas our RPP path tracking disallows reversing | Enforce the same forward/reverse policy in optimization and command handling; clipping reverse output alone can create stalls |
| Python initialization includes a hard-coded x86_64 Python 3.12 library path | Build and import-test inside the exact target image, with matching Python/NumPy ABI; do not infer portability from a host test |

Sources: [controller](https://github.com/LihanChen2004/nav2_neupan_controller/blob/acf2f05ea4efef9dac1a9ebb86b37c10477387f6/src/neupan_controller.cpp), [path handler](https://github.com/LihanChen2004/nav2_neupan_controller/blob/acf2f05ea4efef9dac1a9ebb86b37c10477387f6/src/path_handler.cpp), [Python bridge](https://github.com/LihanChen2004/nav2_neupan_controller/blob/acf2f05ea4efef9dac1a9ebb86b37c10477387f6/src/python_bridge.cpp), and [robot constraints](https://github.com/LihanChen2004/NeuPAN/blob/145ed48cb34cac804b2308eb0f42da081037f550/neupan/robot/robot.py).

Use a separate command watchdog and validated collision intervention downstream of both controllers. Zero output on a returned Python error does not protect against a call that never returns. Test process failure and stale command expiry, not only an orderly ROS cancellation. Reject non-finite outputs and log any safety intervention as part of the result.

### Runtime performance and fair comparison

The present controller period is 50 ms. Measure the whole plugin call, not just neural inference: costmap extraction, Python conversion, DUNE, optimization, visualization, and scheduling. The upstream optimization stage is CPU-bound; adding a GPU alone is not a solution. [NeuPAN runtime guidance](https://github.com/hanruihua/NeuPAN#real-world-deployment).

Start with a benchmark allocation large enough to load the dependencies without competing with Gazebo, then measure CPU time, throttling, RSS, and latency under the intended pod quota. Cap numerical-library thread pools to avoid oversubscription. The hotel profile's 2 CPU/2 GiB limit is a constraint to test, not an established operating point for this package.

Use matching maximum forward speed, angular speed, acceleration, goal tolerances, planner, replanning cadence, and safety margins. Align NeuPAN's `step_time` with the selected controller period and explicitly choose its prediction horizon. The upstream example uses a different timing/speed scale; do not copy it unchanged. If NeuPAN cannot meet 20 Hz, report that and run a separate comparison with **both** controllers at the same lower frequency. Do not quietly compare 20 Hz RPP with 10 Hz NeuPAN.

RPP is a practical incumbent baseline, but a NeuPAN advantage over it would not isolate the value of learning versus optimization. If results are promising, add MPPI as a non-learned optimization-based control. An optional fixed-path `FollowPath` test can isolate tracking; the primary demo should still use the same goal and global-planning workflow in both arms. [Nav2 controller selection](https://docs.nav2.org/jazzy/configuration_and_development/first_time_robot_setup_guide/navigation_plugins/setup_navigation_plugins/).

## Evaluation plan and acceptance gates

### Scenarios and controlled variables

| Trial | Change | Hold fixed | Observable result |
|---|---|---|---|
| Semantic A/B | Semantic layer disabled/enabled | Camera and inference running in both arms; same robot, scene, start, goal, model, planner, RPP, safety profile | Route changes in response to the visible target surface |
| SAM3 category change | Authorized prompt and its mapped category | Model weights, sensor pipeline, scene, navigation algorithms | New target gets costs after a fresh observation; previous target state is cleared |
| Controller A/B | RPP/NeuPAN | Semantics off; same geometry, map, LiDAR, goal, planner, motion envelope, resources | Completion, tracking, clearance, and timing differences |

For semantics, place the patch in view before the initial goal and offer a clear alternative route. Include a no-target negative scene, partial occlusion, target removal, camera interruption, and an object already detected by LiDAR. The last case prevents attributing ordinary obstacle avoidance to AI. Inspect both the planned path and actual robot footprint; RPP corner cutting can invalidate an apparently safe global route.

For control, progress from an open route to bends, a narrow-but-feasible passage, and then a reproducible moving obstacle. Keep obstacle geometry, trajectory, speed, and trigger time fixed within paired runs. Do not start with lift entry or a deliberately impossible passage.

Use at least 20 paired runs per initial scenario, alternate run order, fix/reuse seeds, and report all failures. Separate warm-up/model-loading results from steady state. A small demo sample is not a production safety claim. Use recorded sensor replay for perception regression, but closed-loop simulation for navigation comparisons: replaying a bag from the baseline trajectory cannot measure the new controller's physical behavior.

### Measurements and proposed thresholds

The following are proposed engineering targets, not achieved results. The [October 13 semantic implementation plan](semantic-navigation-implementation-plan.md) refines these into sequential pass/fail gates; use that plan for semantic phase acceptance and this section for the separate learned-controller experiment.

| Gate | Measurement | Initial acceptance condition |
|---|---|---|
| Perception integrity | Mask/cloud registration, capture timestamps, TF, class metadata | No unresolved alignment, namespace, or label-policy errors; held-out masks and projected boundaries pass review |
| Semantic latency | Capture-to-costmap age, inference rate, simulation real-time factor | Target ≥5 Hz updates and p95 age ≤300 ms in the selected profile; stale data triggers the configured pause |
| Semantic effect | Footprint time/distance inside independently annotated target area; path length and completion | At least 90% lower target exposure in paired soft-cost trials, no collision, and no lower completion count; baseline must actually encounter the target |
| Costmap lifecycle | Remove target, expire observations, restart nodes, clear maps, change prompt | No old costs or labels reappear after the specified reset/expiry policy |
| Controller deadline | Whole-call wall-time distribution and missed cycles | For 20 Hz, initial target p99 <40 ms and ≥99.9% calls below 50 ms over a sustained ≥10-minute run; report worst case and every miss |
| Motion outcome | Success/timeouts, endpoint error, path tracking, velocity/acceleration, minimum hull clearance | No collision; no degradation of the agreed clearance requirement or completion count; disclose watchdog interventions |
| Fault handling | Frozen inference, missing checkpoint, failed TF, controller exception/hang, camera loss | Predictable stop and explicit task state; no stale command continuation |

At 0.35 m/s, 300 ms of perception age corresponds to 0.105 m of travel before planning or braking. Use measured braking and planning delay to set viewing distance, stop distance, and watchdog thresholds; the latency target alone is not a safety argument. Track simulation time for observation age and wall-clock time for compute deadlines, particularly when Gazebo runs slower than real time.

Save a run manifest with image digests, package versions, model/checkpoint hashes, geometry, full parameters, BT XML, seeds, node hardware, and resource limits. Record RGB/overlay, aligned cloud, semantic and geometric costmaps, global path, TF, odometry, raw/smoothed/final velocity commands, action outcomes, safety state, and latency/resource metrics. Ground-truth region labels and contact/clearance measurements belong in the evaluator, not the navigation input.

If a fault causes fallback to RPP or geometry-only navigation, label it as degraded operation and an experimental failure where appropriate. Do not count fallback completion as successful AI-controlled navigation.

## Delivery sequence and repository changes

| Workstream | Proposed work | Exit condition |
|---|---|---|
| SAM3 semantic navigation | Follow phases 0–6 of the semantic implementation plan: runtime, camera, recognition, live inference, costmaps, safety, A/B | Each phase passes before the next; repeatable single-floor semantic benefit |
| ONNX alternative | Follow stages O0–O3 using the same interfaces and evaluation | Suitable artifact, recognition, runtime, and navigation gates all pass |
| Learned controller | Separately validate common geometry/safety, train/validate DUNE, harden NeuPAN, benchmark, and compare against RPP | Frame, geometry, cancellation, runtime, and comparison gates pass; not a dependency of semantic navigation |
| Optional extensions | Semantic phase 7 for prompts and phase 8 for RMF/lifts | Fresh policy/floor state and verified traffic, cancellation, and fault behavior |

Implementation would touch the robot SDF/URDF, simulator sensor bridge, per-robot Zenoh configuration, dedicated inference packaging, Nav2 image/launch parameter selection, and Helm resources. Add new evaluation configs rather than overwriting `hotel_nav2_params.yaml`. The current federated entrypoint hard-codes that filename, so profile selection needs an explicit launch/entrypoint change. Add isolated benchmark scripts and validation results under `docs/validation/`; no such implementation is included in this proposal.

Before reintroducing RMF, coordinate semantic detours with the fleet adapter and itinerary expectations. A locally valid detour is not automatically a fleet-traffic-authorized route. On a floor transition, stop, change the map/localization state, clear all semantic buffers, reset the controller path, wait for fresh observations in the new frame, and only then resume. This is a separate integration test, not part of the controller benchmark.

## OpenShift AI and fleet copilot boundaries

Keep the initial perception process close to its sensor and NeuPAN embedded locally in the Nav2 controller process. OpenShift AI can be evaluated later for training, model lifecycle, or a separately served perception model, but remote serving adds serialization, transport, and deadline handling. It does not replace the ROS image/TF/costmap adapter. NeuPAN's synchronous optimization loop is not a suitable first remote model-serving experiment.

Nayantra or the existing fleet copilot could later select a preapproved semantic policy, request a demonstration task, and explain the recorded outcome. Keep arbitrary prompts away from unrestricted cost assignments, velocity control, and collision-monitor settings. The related [model-serving assessment](nayantra-openshift-ai-model-serving.md) addresses the orchestration layer; it is not evidence that a vision or controller model is already served through the same endpoint.

## Reproducibility and adoption review

Source snapshots inspected for this proposal:

| Component | Revision |
|---|---|
| This repository baseline | `56c6668e9e5babdab7e831edf7f40d36a9a0d9db` plus existing uncommitted research documents |
| Nav2 tutorials | `3578fa26feb2b303b7d370591c6b7dc8a7304762` |
| Semantic layer Jazzy | `cf85d3e499af4d389f2aac31e6c8409b424fa417` |
| Open Navigation SAM3 integration | `5e82f4a458f9e97ddd92e2cf10feb2c3552295d3` |
| SAM3 repository's semantic-layer submodule | `3c1b1c3c648cfd0b36b1c1b2e3ea7c68d90877cc` |
| Nav2 NeuPAN wrapper | `acf2f05ea4efef9dac1a9ebb86b37c10477387f6` |
| Wrapper maintainer's NeuPAN fork | `145ed48cb34cac804b2308eb0f42da081037f550` |

The SAM3 example pins a different layer revision from the Jazzy head audited above. Select and test one layer version explicitly; the audit findings must not be assumed identical across revisions. The tutorial's checked-out `model.onnx` has SHA-256 `698517be0848147c466e4b2a7e36037e23e1a32ed3b258aa383c3fb6266ce17c`; the hash establishes artifact identity, not accuracy or runtime suitability.

Review dependency and model licenses before distributing images. The Nav2 NeuPAN wrapper declares Apache-2.0 while the underlying NeuPAN project declares GPL-3.0; review the combined distribution rather than relying on the wrapper badge. SAM3 weights have their own access/license terms. Pin Python and numerical dependencies in reproducible images and keep model-download credentials out of images and run logs. [Wrapper license](https://github.com/LihanChen2004/nav2_neupan_controller/blob/acf2f05ea4efef9dac1a9ebb86b37c10477387f6/LICENSE), [NeuPAN license](https://github.com/LihanChen2004/NeuPAN/blob/145ed48cb34cac804b2308eb0f42da081037f550/LICENSE), [SAM3 model access](https://huggingface.co/facebook/sam3).

**Decision updated October 13:** proceed first with pretrained SAM3 and a fixed prompt, retaining fixed-category ONNX as an alternative. Use the [semantic implementation plan](semantic-navigation-implementation-plan.md) for phase-by-phase acceptance. NeuPAN remains a separate feasibility track. Promote neither into the multi-floor demonstration solely on the strength of a successful upstream example.
