# Phase 6D D0 — static isolated-profile preflight

Date: October 21, 2026  
Result: **DEMO PASS (static profile preflight only); D1 not started.**

## What this gate establishes

D0 establishes a reproducible, opt-in profile contract and confirms the semantic
costmap plugin can be loaded by both Nav2 costmaps. It does not establish live
SAM3 delivery, semantic cell updates, planner response, navigation quality,
collision performance, or real-time factor. The candidate router/profile has
not been deployed. The canonical hotel release and the existing
`semantic-navigation/semantic-hotel-sim` Deployment were not modified.

## Candidate profile

- Profile details: [`phase6-demo-profile-draft.md`](phase6-demo-profile-draft.md).
- Router and topic bridges: [`phase6-demo-topic-bridges.yaml`](../../../../helm/semantic-navigation/phase6-demo-topic-bridges.yaml).
- Nav2 semantic parameters: [`phase6-demo-nav2-candidate.yaml`](../../../../helm/semantic-navigation/phase6-demo-nav2-candidate.yaml).
- Candidate Nav2 entrypoint: [`entrypoint_phase6_nav2.sh`](../../../../scripts/semantic-navigation/entrypoint_phase6_nav2.sh).
- Profile topology: one simulator replica and one `robot_1`, private Gazebo
  partition, private Zenoh router on port 17448, and ROS domains 81 (sim), 82
  (SAM3), and 87 (Nav2).
- Stationary D1 bridge: Nav2-side publisher lists are empty; sensor, semantic,
  and clock inputs are allowlisted separately. No Nav2 action/RMF/lift/door or
  initial-pose routes are defined. A separate config permits only local
  `/cmd_vel` to be exported for a later motion stage; no workload consumes it
  in D0 or D1.
- Nav2 launch: source ROS Jazzy and the semantic overlay, then launch the
  existing hotel federated Nav2 launch file using the candidate params. Do not
  run the canonical entrypoint: the simulator is the TF authority, and the
  candidate does not need its duplicate robot-state publisher or pose seed.
  Keep the established scan-frame rewriter and odometry TF relay.

## Pinned inputs

| Component | Image/model pin |
|---|---|
| Simulator | `semantic-hotel-sim@sha256:d417c9f252d1f89dd859290a4bca1f634bcfd7d3cde6d1702c409d432bd48894` (capture-trace instrumented) |
| Camera compressor | `semantic-hotel-sim@sha256:c3ba94bbcbbe2283f1c46ea0f2baba398da313ffe83d2b59a63272ef91d95ebf` (compression tracing enabled) |
| Nav2 + semantic plugin | `semantic-nav2@sha256:578f86b69f11b064887028af2f347aaac2d72682bfa934db59fc3ab231933a90` |
| SAM3 runtime | `sam3-runtime@sha256:478ec01a7a47fbb0c862fbbef495c71b4a512ff59ed8d6ed5b7234422cc35686` (Phase 4 payload-bound runtime) |
| SAM3 checkpoint | HF revision `3c879f39826c281e95690f02c7821c4de09afae7`; SHA-256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e` |
| Zenoh bridge | `eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18` |
| Candidate router | `eclipse/zenoh@sha256:137310456cc7a75d955063513207c737f25071fbb74fd7641835c50ab8e3369f` |

The fixed prompt is `red mat`. The plugin adds cost 200 in both local and global
costmaps, before inflation; the rest of the known-working hotel Nav2 parameters
are unchanged. The candidate image is based on the same Nav2 image digest as
the running canonical deployment; the candidate image alone adds and sources
the semantic overlay.

## Live topic and frame evidence

Read-only inspection of the existing simulator showed one `robot_1` graph with
`/robot_1/scan`, `/robot_1/odom`, `/robot_1/tf`, `/robot_1/tf_static`, compressed
RGB/depth, camera info, capture/compression traces, and `/clock`.

- Scan header: `robot_1/base_scan/lidar`; candidate rewriter maps it to
  `base_scan` on `/scan_fixed`.
- Odometry header: `odom` → `base_footprint`; the existing relay can provide
  `odom→base_footprint` plus the configured fixed `map→odom` transform.
- Static transform stream contains `camera_color_optical_frame`, matching the
  costmap layer's optical-frame parameter.
- SAM3 publishes `/robot_1/semantic/{mask,points,timing,label_info,status,ready}`;
  the layer consumes the first four. A no-namespace semantic bridge preserves
  the absolute topic names; the namespaced Nav2 sensor bridge cannot
  double-prefix them.

## Resource placement proposal

At sampling, the existing simulator container used 9,113m CPU against a 1-core
request; its node was at 89% CPU. Do not co-locate the candidate profile with
that workload. Proposed placement is the 16-core CPU-tainted worker
`ip-10-0-38-113` for the candidate simulator/Nav2/router group and the L40S
worker `ip-10-0-18-251` for SAM3. The CPU worker had 15,500m allocatable and
1,119m requested (7%); the GPU worker had one allocatable L40S and zero GPU
requests. The CPU profile requests approximately 13.2 cores total. Node
`ip-10-0-15-146` is not selected despite low observed CPU: CPU requests were
already 12,544m (80%). These are scheduling estimates, not a performance
result. D1 must record actual resource use, Gazebo real-time factor, inference
latency, and semantic age before motion trials.

## Verification

- Isolated plugin-load preflight: PASS; both costmap servers loaded
  `semantic_layer`, remained lifecycle-inactive, and the pod exited 0. See the
  [October 20 preflight evidence](d0-nav2-plugin-preflight-20261020.md).
- Phase 6 bridge/topology tests: 8/8 passed.
- Phase 6 parameter tests: 6/6 passed.
- Phase 5 regression tests: 30/30 passed.
- `bash -n scripts/semantic-navigation/entrypoint_phase6_nav2.sh`: passed.
- `oc apply --dry-run=server` accepted the candidate ConfigMap, Service, and
  router Deployment; nothing was created.
- No runtime profile was deployed; no Nav2 goal or motion command was issued.

### Reproducibility hashes

SHA-256 of the static candidate artifacts reviewed for this gate:

| Artifact | SHA-256 |
|---|---|
| Bridge/router manifest | `b77cdba1d91b1d9b7ef79aec9d46f83c429ffa73c57cd27e8525e5bc9e5efcaa` |
| Candidate Nav2 entrypoint | `e4272bdf582a075da177580299660abca7a9831144f429a2d2cb66b75c0a904d` |
| Bridge/topology tests | `b629086d60d70525cd23eb2ec784c05b8d44ad2b32edfb1ef07c413b66503013` |
| Profile contract | `451dbc825e258881c56cd3954d404b5c0906b26ef96e064fbbc30ef518a3b704` |
| Candidate Nav2 parameters | `259ee0d4d4267021c58432e55fd512c95fc36c017582cf098b2ffa6ce67ac57d` |

### Pre-D1 image-compatibility correction

Before D1 deployment, source inspection found that the earlier draft's SAM3
runtime pin (`e1ed…`) did not emit the payload digests required by the semantic
costmap plugin. The layer rejects each observation unless `mask_sha256` and
`cloud_sha256` match the exact mask and point-cloud payloads. The candidate is
therefore corrected to the Phase 4 payload-bound runtime `478ec…`, whose
compatibility was exercised in the Phase 4 runtime pilot. Inspection of the
first live D1 startup then found the simulator pin also lacked the capture-trace
library (SAM3 reported `capture trace/calibration timing missing`). D1 now uses
the Phase 4 exercised trace-instrumented simulator and compressor pins
(`d417…` and `c3ba…`) with capture/compression tracing enabled. No inference was
admitted and no motion occurred before this correction.

## Limits and next gate

D0 is a static profile/plugin preflight pass only. Proceed to D1 as a separately
verified, stationary smoke: deploy the isolated candidate, leave all Nav2
publishers and the gated motion bridge disconnected, and verify sensor → SAM3 →
semantic topics → both costmaps, including expiry after target removal and a
stale/lost inference condition. Preserve raw costmap and timing evidence. D1
must be reviewed before attaching the motion-only bridge or starting paired
navigation trials.

The inherited Nav2 warning remains: inflation radius 0.200 m is below the
computed 0.225 m inscribed footprint radius. D0 made no change to this baseline
and provides no collision or movement evidence. General-use recognition and
full Phase 5 safety qualification remain incomplete.
