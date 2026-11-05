# Phase 6D isolated demo profile (D0 candidate)

Date: October 21, 2026  
Status: **D0 static profile passed; isolated D1 has demonstrated semantic-cell application in both costmaps and clearing after target removal. The stationary gate remains open for inference-loss expiry verification.** See [D1 evidence](d1-stationary-smoke-20261021.md).

## Scope and isolation

This is a new, opt-in single-floor demonstration profile. It is not the
canonical hotel deployment and does not modify the currently running
`semantic-navigation/semantic-hotel-sim` Deployment. The candidate profile has
exactly one simulator replica and one `robot_1`, uses a private Gazebo
partition (`semantic_navigation_phase6_demo`) and a dedicated
`semantic-phase6-router` on port 17448. The existing Phase 1 simulator remains
separate and untouched. The Phase 6 router is not connected to the canonical
`ros2-rmf-hotel` router or RMF command/action bridges.

The transport candidate is
[`phase6-demo-topic-bridges.yaml`](../../../../helm/semantic-navigation/phase6-demo-topic-bridges.yaml).
Its stationary profile has separate sensor, semantic, and clock bridges. All
Nav2-side publishers are disabled for the D1 stationary smoke; the only
velocity route is a separate, gated config carrying `/cmd_vel` for `robot_1`.
That gated config must not be mounted for D1. It is only a candidate for a
later, reviewed motion stage. There are no Nav2 action, RMF, lift, door, or
initial-pose routes in this profile.

Use ROS domains 81 (simulator and camera compressor), 82 (SAM3 runtime and its
bridge), and 87 (Nav2 and its bridges). The Nav2 container uses
[`entrypoint_phase6_nav2.sh`](../../../../scripts/semantic-navigation/entrypoint_phase6_nav2.sh):
it sources the ROS underlay and semantic overlay, then launches the existing
federated hotel Nav2 launch file with the candidate map/parameters. It does not
run the canonical entrypoint, which starts a second robot-state publisher and
seeds AMCL with a pose. The simulator supplies robot-state TF; the existing
odometry relay supplies `odom→base_footprint` and the fixed `map→odom` offset.
The scan-frame rewriter remains a separate sidecar (`/scan` to `/scan_fixed`).
Set `INITIAL_X=15.402` and `INITIAL_Y=-31.594` on the odometry-TF adapter for
the current hotel map alignment; keep AMCL's `tf_broadcast` disabled so there
is only one `map→odom` authority.

## Pinned inputs

| Component | Candidate reference |
|---|---|
| Simulator | `semantic-hotel-sim@sha256:d417c9f252d1f89dd859290a4bca1f634bcfd7d3cde6d1702c409d432bd48894` (capture-trace instrumented) |
| RGB-D compressor | `semantic-hotel-sim@sha256:c3ba94bbcbbe2283f1c46ea0f2baba398da313ffe83d2b59a63272ef91d95ebf` (compression tracing enabled) |
| Nav2 + semantic plugin, D0 preflight | `semantic-nav2@sha256:578f86b69f11b064887028af2f347aaac2d72682bfa934db59fc3ab231933a90` |
| Nav2 + semantic plugin, D1 accept/reject diagnostics | `semantic-nav2@sha256:5d80c9af5d3c8487eaf49f6d23ac37762212d4a5ec9f1157276eb404d6bc721d` |
| Nav2 + semantic plugin, D1 merge diagnostics | `semantic-nav2@sha256:d23d20a8decdd9a6cc0f9419874c1b610333e033867e579aeb022a5bb1b97b0e` |
| Nav2 base image | `ros2-rmf-nav2@sha256:fcf66afcc12e213bc13ee8a50eb6b141b4a9af3b4a4b86123421e58624ec54b6` |
| SAM3 runtime | `sam3-runtime@sha256:478ec01a7a47fbb0c862fbbef495c71b4a512ff59ed8d6ed5b7234422cc35686` (Phase 4 payload-bound runtime) |
| SAM3 checkpoint | HF revision `3c879f39826c281e95690f02c7821c4de09afae7`; SHA-256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e` |
| Zenoh bridge | `eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18` |
| Zenoh router | `eclipse/zenoh@sha256:137310456cc7a75d955063513207c737f25071fbb74fd7641835c50ab8e3369f` |

SAM3 prompt is fixed to `red mat`. Candidate Nav2 parameters are
[`phase6-demo-nav2-candidate.yaml`](../../../../helm/semantic-navigation/phase6-demo-nav2-candidate.yaml),
rendered from the existing hotel Nav2 parameters; the plugin-load report
records their hash. The plugin adds cost 200 to semantic target cells in both
costmaps, before inflation; the ordinary obstacle/voxel and static-map layers
remain in place.

## Verified message and frame map

The live simulator graph was read-only inspected on October 21. It publishes
`/robot_1/{scan,odom,tf,tf_static}`, compressed color/depth images, camera info,
camera capture/compression traces, and `/clock`. The observed odometry headers
are `frame_id=odom`, `child_frame_id=base_footprint`; the scan frame is
`robot_1/base_scan/lidar`. The static transform stream contains
`camera_color_optical_frame`.

| Producer → consumer | Route/mapping | Purpose |
|---|---|---|
| Simulator → SAM3 | Compressed RGB/depth, camera info, `/robot_1/tf`, `/robot_1/tf_static`, camera traces and `/clock` | RGB-D inference and capture-time/frame context |
| Simulator → Nav2 | `/robot_1/scan`, `/robot_1/odom`, `/robot_1/tf`, `/robot_1/tf_static`; bridge namespace `/robot_1` maps these to local `/scan`, `/odom`, `/tf`, `/tf_static` | Existing Nav2 sensor and transform inputs |
| Scan adapter → Nav2 | `/scan` → `/scan_fixed`; rewrite `robot_1/base_scan/lidar` to `base_scan` | Preserves the established hotel Nav2 scan-frame fix |
| Odometry adapter → Nav2 TF | Local `/odom` drives `odom→base_footprint` and the configured fixed hotel map offset drives `map→odom` | Keeps TF authority singular; do not start a second robot-state publisher in the Nav2 pod |
| SAM3 → Nav2 | `/robot_1/semantic/{mask,points,timing,label_info}` on a no-namespace bridge | Exact plugin subscriptions at `/robot_1/semantic/...` |
| Nav2 → simulator (later motion gate only) | Separate bridge maps local `/cmd_vel` to the isolated `robot_1/cmd_vel` route; simulator side accepts only `/robot_1/cmd_vel` | Not mounted for stationary D1; no Nav2 command or action can leave D1 |

The sensor and semantic routes are split so the `/robot_1` namespace rewrite
used for Nav2 sensor inputs cannot accidentally double-prefix the plugin's
absolute `/robot_1/semantic/...` topics. `tf_static` from the simulator's
robot-state publisher supplies the verified camera optical transform; the
candidate Nav2 process must not start another robot-state publisher.

## Resource placement proposal

Current measurements show why the profile must not be co-located with the
existing semantic simulator: its simulator container used 9,113m CPU against a
1-core request, while its node (`ip-10-0-53-174`) was at 89% CPU. This is a
resource observation, not a real-time-factor measurement.

For the isolated candidate, use the currently lightly used 16-core
CPU-tainted worker `ip-10-0-38-113` for the one simulator, Nav2, and the small
router/bridge processes. Its observed CPU was 0% and allocated CPU requests
were 1,119m (7%) of 15,500m. Do not select `ip-10-0-15-146` based on its 3%
observed CPU: its CPU requests were already 12,544m (80%). Use the L40S worker
`ip-10-0-18-251` for SAM3; at sampling, it exposed one allocatable GPU and had
zero GPU requests.

Proposed requests/limits for the candidate are:

| Workload | Requests | Limits |
|---|---:|---:|
| Simulator | 10 CPU, 4 GiB | 12 CPU, 8 GiB |
| Camera compressor | 250m CPU, 512 MiB | 2 CPU, 2 GiB |
| Nav2 stack | 2 CPU, 2 GiB | 4 CPU, 4 GiB |
| Nav2 bridges and two frame/odom adapters | 750m CPU total, about 576 MiB | 2 CPU total, about 1.4 GiB |
| Private router | 100m CPU, 128 MiB | 500m CPU, 512 MiB |
| SAM3 inference and sensor/output bridge | 3.1 CPU, 12 GiB, 1 GPU | 6.5 CPU, about 16.5 GiB, 1 GPU |

The CPU-node profile sums to about 13.2 requested CPU before platform/system
headroom, below 15.5 allocatable; the GPU inference pod is scheduled separately.
Use node tolerations/selection for the CPU-tainted and L40S workers, plus a
preflight check of current allocatable requests before deployment. These are
proposed requests, not observed Phase 6 usage. Capture Gazebo real-time factor,
SAM3 inference latency, semantic observation age, and per-container CPU during
D1; if data is stale or the sim falls materially behind, lower camera
resolution/rate before motion trials. No real-time performance claim is made
from D0.

## D0 boundary and next gate

D0 covers the pinned profile, static topic/frame contract, resource placement
proposal, semantic-plugin image startup hook, and no-motion bridge topology. It
does not prove live SAM3-to-costmap delivery, semantic cell updates, planner
response, trajectory safety, or real-time factor. D1 is the next gate: deploy
only this isolated profile, leave the motion bridge unmounted, and verify
camera → SAM3 → semantic topics → both costmaps while stationary. Preserve
before/after costmap and inference/age logs. Do not start the paired navigation
comparison until D1 is reviewed.
