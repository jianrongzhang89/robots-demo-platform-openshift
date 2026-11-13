# Phase 8 isolated RMF demo profile

Phase 8 uses the accepted Phase 6 D2 semantic-on renderer, pinned Nav2/plugin
image, and fixed map-to-odom transform. SAM3 inference runs in the OpenShift AI
KServe `sam3-mat-v1` model service; a bounded ROS adapter in the Phase 8 pod
consumes synchronized RGB-D input and publishes semantic outputs for Nav2. It
does not inherit arbitrary parameters from a live Nav2 pod. The fixed red mat retains
observed semantic cells for 300 seconds; capture freshness, policy/epoch/reset
clearing, global inflation, final-heading rotation, and the original clearance
limits are preserved.

The isolated single-floor topology adds an RMF schedule, dispatcher, and fleet
adapter. RMF owns task dispatch and cancellation. The adapter submits Nav2 goals
for RMF itinerary segments and verifies terminal success plus a fresh stopped
pose before completing the activity. The ROS adapter uses mutual TLS and checks
the pinned OpenShift AI deployment identity before accepting results. No
RMF/Nav2 actions cross ROS domains.

## Start and validate

From the repository root:

```sh
python3 scripts/semantic-navigation/phase8_topology.py up --evidence-dir <new-directory>
```

Startup saves the Phase 6 simulator, Nav2 and local inference pods, recreates
the simulator to reset world pose and wheel odometry together, waits for its
clock, and starts Phase 8. It replaces local SAM3 inference with the qualified
OpenShift AI HTTP adapter while preserving the semantic ROS topic contract. It
creates a private copy of the accepted navigation configuration. Its bridge clone retains
Phase 8's demonstrated matching velocity-subscriber rule; the shared Phase 6
bridge configuration is unchanged. It
requires the Phase 6 epoch-aware inference wrapper and runs the same stationary
profile, served model identity, fresh semantic-cell, AMCL, transport-reader,
and planned-clearance checks.
Startup sends no RMF task or navigation goal. It waits for active Nav2 lifecycle
nodes before preflight. If the pinned motion bridge has no DDS reader, startup
restarts that container once with the same image digest and repeats all gates;
other preflight failures restore Phase 6 and retain failure logs.

After reviewing noVNC, run the monitored task:

```sh
oc exec -n semantic-navigation semantic-phase8-nav2 -c nav2 -- bash -lc \
  'source /opt/ros/jazzy/setup.bash; source /opt/rmf_demos_ws/install/setup.bash; python3 /phase8/phase8_semantic_trial.py --trial phase8-semantic'
```

This dispatches an RMF go-to-place task to `phase8_dropoff` at `(19.5, -31.594)`.
The shared Phase 6 monitor enforces the 0.10 m/s speed cap (0.005 m/s measurement
tolerance), 0.20 m preflight hull clearance, and 0.10 m live hull clearance. It
checks every global replan and independent Gazebo body trajectory, and cancels
through RMF on failure. Evidence includes the correlated RMF request/task ID,
Nav2 goal IDs and terminal statuses, fleet idle state, every moving global plan,
semantic-cell history, and the full physical trajectory. A stationary preflight
alone is never a semantic-avoidance pass.

Completion requires successful Nav2 goals, the correlated task observed in the
fleet state and then idle, and the physical robot at the requested endpoint.
The dispatcher task-history view is recorded separately when needed; an assigned
entry alone is not used as proof of completion.

To restore the saved Phase 6 topology:

```sh
python3 scripts/semantic-navigation/phase8_topology.py down --evidence-dir <same-directory>
```

The demo is limited to one robot, one floor, and a fixed scene. It does not
qualify shared-space traffic conflicts, moving semantic obstacles, lifts,
availability, or production operation.
