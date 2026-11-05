# Phase 6D D0 — Isolated Nav2 semantic-plugin preflight

Date: October 20, 2026  
Result: **Nav2 plugin-load subgate PASS; overall D0 remains HOLD.**

## Scope

Verify that the opt-in Phase 6 semantic costmap plugin can be loaded by the
Nav2 servers that own the local and global costmaps. This check was deliberately
isolated from the running hotel simulator and did not activate Nav2 or exercise
navigation. It is not evidence of semantic-message ingestion, cost updates,
planning behavior, collision performance, or end-to-end demo capacity.

## Configuration and artifacts

- Namespace: `semantic-navigation`.
- Test pod: `semantic-phase6-nav2-plugin-preflight-7`; completed with exit code
  0 on `ip-10-0-38-113.ec2.internal`.
- ROS domain: `86`; controller velocity output was remapped to
  `/phase6_demo/disconnected_cmd_vel`.
- Both Nav2 servers were configured but left in lifecycle state `inactive [2]`.
  No simulator, bridge, action goal, or motion command was started.
- Test pod resources: request 500m CPU / 1 GiB memory; limit 1 CPU / 2 GiB.
- Nav2 base image (pinned to the known-working hotel deployment):
  `quay.io/jianrzha/ros2-rmf-nav2@sha256:fcf66afcc12e213bc13ee8a50eb6b141b4a9af3b4a4b86123421e58624ec54b6`.
- Built plugin image (`semantic-nav2:phase6-plugin-entrypoint`):
  `image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-nav2@sha256:578f86b69f11b064887028af2f347aaac2d72682bfa934db59fc3ab231933a90`.
- Parameters came from the opt-in candidate at
  [`phase6-demo-nav2-candidate.yaml`](../../../../helm/semantic-navigation/phase6-demo-nav2-candidate.yaml).

## Observed result

The final preflight emitted `PHASE6_NAV2_PLUGIN_PREFLIGHT=PASS` and exited
successfully. The controller server's local costmap logged
`Using plugin "semantic_layer"`; the planner server's global costmap logged
the same. Both server lifecycle states were `inactive [2]`. The final pod
reached Kubernetes phase `Succeeded`, exit code 0, and cleanup terminated the
Nav2 processes. The test also verified that the candidate image's real
`/entrypoint-nav2-federated.sh` sources the overlay after the ROS underlay, and
that `ros2 pkg prefix demo_semantic_costmap` resolves to the installed overlay.

This startup check was added after inspection showed the base entrypoint
sources `/opt/ros/jazzy/setup.bash` and launches Nav2 without sourcing the new
workspace. The isolated image build now inserts the overlay source after the
ROS underlay; the canonical image and deployment were not changed.

The test harness initially exposed its own issues (a combined-log assertion
that did not account for each server owning a different costmap, then process
wrapper/log-path cleanup defects). Those were corrected; the final run checked
each server independently and completed cleanly. These harness iterations were
not plugin-load failures.

## Local verification and reproducibility

- Phase 6 parameter tests: 6/6 passed.
- Existing Phase 5 profile/resource/launcher/series regression tests:
  30/30 passed.
- `bash -n` passed for the isolated preflight script.
- Base image digest: `fcf66afcc12e213bc13ee8a50eb6b141b4a9af3b4a4b86123421e58624ec54b6`.
- Built plugin image digest: `578f86b69f11b064887028af2f347aaac2d72682bfa934db59fc3ab231933a90`.
- Candidate parameters SHA-256:
  `259ee0d4d4267021c58432e55fd512c95fc36c017582cf098b2ffa6ce67ac57d`.
- Semantic layer source SHA-256:
  `6dbf7739e214e07eb8d1e14df1d1c83531c7a4fbe459c90380d5e736e77110da`.
- Semantic layer header SHA-256:
  `05d539d24f470d41052570634405ba4068346c31666539d0311960408bb2cc4b`.
- Preflight script SHA-256:
  `d056b4ba93167bd8bdc81c06d615f54d93b0aa1be623ca6bcb4cb277ce47f85b`.
- Containerfile SHA-256:
  `458678f386928baa713566d9e328f42b819d0293df86ac51d63dbcbcbd3ce251`.

## Runtime topology audit

The known-working hotel Nav2 deployment is `robot-nav-robot-1` in namespace
`ros2-rmf-hotel`, using the pinned base image above. It was not changed. The
isolated `semantic-navigation/semantic-hotel-sim` deployment is a separate
three-container Gazebo/camera-compressor/ROS-Gazebo-bridge stack and has no
Nav2 controller or planner process. It connects to its own
`semantic-zenoh-router`; the current Phase 6 candidate does not yet provide a
Nav2 deployment or an end-to-end bridge allowlist for semantic outputs back to
that isolated Nav2 instance. The running semantic simulator was left intact.

The source-level message path is identifiable: the simulator side publishes
compressed RGB/depth, camera calibration, capture/compression traces, TF, and
clock; the SAM3 node consumes those inputs and publishes
`/robot_1/semantic/{mask,points,timing,label_info,status,ready}`; the costmap
layer consumes mask, points, timing, and labels. D0 still needs an isolated
Zenoh configuration that carries only the required sensor/TF/clock inputs to
SAM3, carries semantic outputs back to the isolated Nav2 costmaps, and routes
Nav2 command velocity only to the isolated simulator.

## Limits and next D0 work

The isolated preflight worker was a 16-core CPU-tainted node sampled at about
7% CPU requests allocated and 120m observed. That supports this small preflight
only; it does not establish capacity for Gazebo, camera transport, SAM3, and
Nav2 together. The existing simulator was observed using about 9.5 CPU cores
against a 1-core request on a node at 91% CPU. Do not add the semantic stack to
that deployment without a resource plan and timing observation.

An inherited Nav2 configuration warning reported inflation radius 0.200 m below
the computed 0.225 m inscribed footprint radius. This test did not alter that
baseline value and did not activate navigation; collision behavior remains
untested.

Overall D0 stays **HOLD** until the complete opt-in demo profile verifies its
image/model pins, topic and frame mappings, exactly one simulator/robot, and
resource placement/real-time-factor plan, including the isolated Nav2 and
SAM3-to-costmap bridge topology. The next permitted check after D0 is complete
is D1's stationary perception-to-costmap smoke test. No D1 work or
navigation/motion test is authorized by this preflight result.
