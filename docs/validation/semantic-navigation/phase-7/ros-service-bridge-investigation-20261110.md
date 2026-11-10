# Phase 7 ROS action bridge investigation — November 10, 2026

## Result

**Bridge fixture and actual Nav2 cancellation subgate PASS; overall Phase 7 remains HOLD.** The first bridge runs found that the runtime's direct clients for Nav2's `/_action/cancel_goal` services do not become ready across Zenoh, even when the Nav2 action servers are allowlisted. The ordinary-service cancellation proxy now runs as its packaged process. It passes both the three-domain action fixture and a separate simulator topology with actual Nav2 nodes and native watchdog status. No Phase 6 workload was changed.

## Evidence

- Verifier source: `apps/semantic-safety/verify_phase7_ros_service_bridges.py`.
- Final runtime candidate: `semantic-safety@sha256:d153b717d2d6656d0b656c1c0080012213e8d85e3aca463c1f44df56b2683a77` (build #44; 17 tests passed).
- Bridge/router images are digest-pinned in
  `helm/semantic-navigation/openshift-ai/phase7-ros-service-bridge-test.yaml`.
- Job: `semantic-phase7-ros-service-bridge-test`, passing pod
  `semantic-phase7-ros-service-bridge-test-c8lg2`; six of six containers exited
  zero.
- Three isolated ROS domains were used: Nav2 187, adapter 188, operator 189.
- The fixture accepted active goals on both Nav2 actions. Both cancellation
  calls returned `return_code: 0` with one goal in each `goals_canceling` list;
  both action results reached `STATUS_CANCELED` (5). The operator atomically
  applied `blue crate`, and three adapter status messages arrived.
- The packaged proxy runner is verified under a read-only root filesystem; it
  places ROS logs in writable `/tmp` and shuts down cleanly. Raw logs and pod
  exit evidence are archived under
  [`ros-service-bridge-packaged-proxy-pass-20261110`](ros-service-bridge-packaged-proxy-pass-20261110/).
- The verifier now shuts down its executors before destroying ROS nodes, avoiding
  a native teardown crash after it writes its successful result.
- Earlier failing iterations are retained under
  [`ros-service-bridge-run-20261110`](ros-service-bridge-run-20261110/).
- The candidate image build passed Python compilation and all 17 Phase 7
  runtime unit tests.

## Evidence: actual Nav2 cancellation and native no-motion

The packaged proxy was deployed beside the accepted Nav2 image in the isolated
Phase 7 watchdog simulator topology. The verifier retried startup rejections
until Nav2 accepted a goal (attempt 4), then required one proxy acknowledgement
for the active `/navigate_to_pose` goal and a `STATUS_CANCELED` result. Across
422 post-settling native samples, the watchdog remained disarmed with zero
applied linear/angular commands and maximum measured speed 0.0010041143 m/s.
All 11 pod containers exited zero on runtime candidate #51
(`sha256:47c8424498ca3bd15975fa29d8912d0373d8d3de5476fd742f1e58071fce90d6`).
Raw logs and pod evidence are archived under
[`live-nav2-cancel-pass-20261110`](live-nav2-cancel-pass-20261110/).

## Required follow-up

Repeat the native-stop, cancel-ack, transition, restart, stale-result, and
no-motion checks with the production adapter and model service in the complete
Phase 7 topology. Qualify production identities, permit-key provisioning and
rotation, identity administration, and network policy. Complete the additional
object recognition held-out and applicable Phases 3–6 qualification. Keep
Phase 6 unchanged.

The actual Nav2 cancel/no-motion subgate now passes in simulation. The
production adapter/model service and production operator identities are still
absent from this topology; isolated fixture success does not qualify them.
