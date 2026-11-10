# Phase 7 live simulator watchdog smoke — November 10, 2026

**Result: PASS for native watchdog loading and disarmed actuator rejection.**
This is a separate simulator pod with its own private Gazebo partition and ROS
domain. It did not mount the Phase 6 checkpoint PVC or connect to the Phase 6
Zenoh router.

## Candidate and runtime

- Simulator image: `semantic-hotel-sim@sha256:23b186a20fb2860ec7332fb3e6b2c7b02efb1fe9c821dab9fa8273e5f7ffa78c`.
- Base simulator: `semantic-hotel-sim@sha256:d417c9f252d1f89dd859290a4bca1f634bcfd7d3cde6d1702c409d432bd48894`.
- Smoke pod: `semantic-phase7-watchdog-simulator-smoke`.
- ROS domain: 181.
- Gazebo partition: `phase5-watchdog-phase7-topology-smoke`.
- The world patch routes the Gazebo DiffDrive input through the native watchdog
  plugin and updates the private robot description. The candidate image copies
  native plugins from the pinned Phase 5 safety image.
- The pod was deleted after evidence capture because it shared a node with the
  accepted Phase 6 simulator and consumed 5.6 CPU during the smoke, avoiding
  continued resource contention with the accepted workload.

## Checks

- Gazebo published `/phase5/drive/status` as `gz.msgs.StringMsg` and provided
  `/phase5/drive/stop` as `gz.msgs.StringMsg -> gz.msgs.Boolean`.
- The status stream reported a valid physical sample, `armed=false`, zero
  applied linear/angular velocity, and measured speed below 0.000001 m/s.
- The simulator exposed `/clock`, `/robot_1/odom`, `/robot_1/scan`, camera
  image/info topics, and capture trace topics in its private ROS domain.
- A 20 Hz raw-command injection sent 80 nonzero `Twist` samples directly to
  `/phase5/internal_drive` while the watchdog was disarmed. Peak observed speed
  was below 0.000001 m/s and robot x-pose delta was 0 m.

This confirms the native layer loads and clamps raw actuator input in the
actual hotel world. It does not qualify the ROS-domain proxy, production
adapter/model server connection, operator credentials, or supervised motion
path. The Phase 7 topology remains under construction and the overall phase
remains HOLD.
