# Hotel Nav2/RMF Continuation Handoff

**Date:** 2026-09-22
**Base commit:** `41b3107`
**Status:** Navigation path is functional; noVNC camera behavior remains unconfirmed for the user.

## Objective

Continue the single-pod OpenRMF + Nav2 hotel multi-level demo in
`/Users/zhangj/devt/src/robots-demo-platform-openshift`.

The intended architecture is one OpenShift pod, one ROS 2 Jazzy DDS domain,
Gazebo Harmonic, Nav2, OpenRMF traffic/task/lift/door nodes, and one local
EasyFullControl adapter. Do not reintroduce Zenoh, domain splitting, sidecars,
teleportation, or large navigation tolerances.

## Current Runtime

- Namespace: `ros2-rmf-hotel`
- Deployment: `hotel-nav2-rmf`
- Helm release: `multi-robot-demo`
- Image repository: `quay.io/jianrzha/ros2-rmf-hotel-nav2-rmf`
- Current deployment tag: `multilevel-stabilized`
- Current observed image digest: `sha256:3a9cd03bfee90265c8a2dcc4ec398474b0601ffa286b778f1b20519d7fcbe327`
- noVNC URL: `https://hotel-nav2-rmf-novnc-ros2-rmf-hotel.apps.ai-dev02.kni.syseng.devcluster.openshift.com/vnc.html`

Always verify the live image digest and runtime file hashes before assuming the
pod contains current source. Tags have been retargeted during this work.

The latest runtime verification showed:

- Pod running with zero container restarts.
- Gazebo GUI/server, Xorg, x11vnc, and websockify alive.
- `/clock` advancing.
- noVNC HTTP route returns `200 OK`.
- Gazebo camera follow is activated through the `/gui/follow` service and logs
  `Gazebo camera following robot_1`.
- `/gui/currently_tracked` reports `FOLLOW_LOOK_AT`, target `robot_1`, and
  overhead offset `(0, 0, 5)`.
- `/gui/camera/pose` changes continuously while the robot navigates, including
  during lift approach and return.

## Functional Navigation Result

The intended route is:

`L1 lobby -> L3_middle_hallway -> L1 lobby`

The navigation behavior has repeatedly reached the following milestones:

1. Robot navigates to Lift2 on L1.
2. Robot enters the lift and travels upward.
3. Robot exits on L3.
4. Robot reaches the explicit `L3_middle_hallway` waypoint.
5. Adapter holds there for 10 seconds.
6. Robot returns to Lift2, descends to L1, and returns to the lobby.

When successful, final fleet state is idle at L1 lobby with empty `task_id`,
empty path, and no active lift session. The overhead-camera acceptance run
completed both lift crossings without a camera pose failure and left the pod
healthy and idle at L1.

## Preserved Uncommitted Source Changes

Do not revert or overwrite these existing worktree changes:

- `config/nav2/hotel_nav2_params.yaml`
- `demo/dispatch_multilevel_task.py`
- `entrypoints/entrypoint-hotel-nav2-rmf.sh`
- `scripts/local_nav2_fleet_adapter.py`
- `scripts/lift_request_relay.py`
- `scripts/prepare_hotel_baseline.py`

The important fixes in those files are:

- Real Nav2 lift-entry goals with pose and velocity validation; no false
  completion while the robot is still outside the cabin.
- Nav2 lifecycle reset and costmap-shape synchronization after `LoadMap`.
- Explicit 10-second `L3_middle_hallway` dwell before requesting the return
  lift.
- Lift relay filtering for empty end-session requests, duplicate suppression,
  and stateful L3 exit/return proximity checks before descent.
- Removal of lift-door collision geometry, wider lift-cabin graph corridors,
  and generated graph place name `L3_middle_hallway`.
- Global dynamic obstacle and inflation layers disabled while local safety
  layers remain enabled.
- `GZ_IP=127.0.0.1` and `GZ_PARTITION=hotel_nav2_rmf` exported to avoid
  Gazebo Transport discovery crashes.
- Dispatch default route is `lobby`, `L3_middle_hallway`, `lobby`.

## Camera-Follow Root Cause and Fix

The world derivative adds this CameraTracking configuration:

```xml
<follow_target>robot_1</follow_target>
<follow_offset>-6 0 3</follow_offset>
```

The previous entrypoint waited for a subscriber on `/gui/track` and sent
`FOLLOW_FREE_LOOK`. Gazebo's CameraTracking implementation uses
`FOLLOW_FREE_LOOK` to clear the camera's track target, so transport status could
show `robot_1` while the actual camera remained fixed. Sending the topic message
also raced the GUI scene initialization.

The fixed entrypoint waits for the `/gui/follow` service provider, calls it with
`robot_1`, sets the offset through `/gui/follow/offset`, waits for the tracking
topic subscriber, and publishes a bounded retry sequence:

```text
service: /gui/follow
request: data: "robot_1"
service: /gui/follow/offset
request: x: 0 y: 0 z: 5
topic: /gui/track
mode: FOLLOW_LOOK_AT
follow_target: robot_1
track_target: robot_1
follow_pgain: 0.02
track_pgain: 0.02
```

`FOLLOW_FREE_LOOK` followed position but left the camera orientation fixed;
robot yaw and lift transitions could move the robot out of view. Plain
`FOLLOW` kept the target visible but could rotate too aggressively and had
unstable behavior during floor transitions. `FOLLOW_LOOK_AT` keeps the robot
centered while the lower gains smooth camera rotation. The final default uses
an overhead offset of `(0, 0, 5)` rather than the yaw-dependent `(-6, 0, 3)`
offset. This removes fast horizontal camera swings and keeps the camera bounded
during vertical lift movement.

The deployed fix reports `FOLLOW_LOOK_AT` and a valid robot-relative camera
pose at startup. A bounded watchdog polls `/gui/camera/pose` and reinitializes
the follow service only when the pose has a negative Z, which occurs during
some lift transforms. The full acceptance route completed with recovery logs,
bounded camera poses, and an idle L1 robot. Manual zoom/pan behavior should
still be checked in the user's noVNC session.

## Lift Request and Exit Fixes

The relay's `/lift_states` subscription uses reliable volatile QoS, matching
the simulator publisher. The previous transient-local subscription received
no lift states, so its session guard never ran. The relay now latches a real
L3-to-L1 descent and rejects stale ascent requests for the remainder of that
session. The adapter also waits five seconds after destination-floor
localization before releasing the lift exit phase, allowing RMF to observe the
new floor state before replanning.

## Required Verification Commands

Run from the repository root. Use a fresh pod before navigation tests.

```bash
oc get deploy hotel-nav2-rmf -n ros2-rmf-hotel \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\\n"}'
oc get pod -n ros2-rmf-hotel -l app=hotel-nav2-rmf \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}{"\\n"}'

POD=$(oc get pod -n ros2-rmf-hotel -l app=hotel-nav2-rmf \
  -o jsonpath='{.items[0].metadata.name}')
oc exec -n ros2-rmf-hotel "$POD" -- sha256sum \
  /entrypoint-hotel-nav2-rmf.sh \
  /opt/ros2-demo/scripts/lift_request_relay.py \
  /opt/ros2-demo/scripts/local_nav2_fleet_adapter.py

oc exec -n ros2-rmf-hotel "$POD" -- bash -lc \
  'export GZ_PARTITION=hotel_nav2_rmf; gz topic -i -t /gui/track; \
   timeout 10 gz topic -e -t /gui/currently_tracked -n 1'

oc exec -n ros2-rmf-hotel "$POD" -- bash -lc \
  'export HOME=/tmp/ros-home; source /opt/ros/jazzy/setup.bash; \
   timeout 8 ros2 topic echo /clock --once'

curl -k -I --max-time 15 \
  'https://hotel-nav2-rmf-novnc-ros2-rmf-hotel.apps.ai-dev02.kni.syseng.devcluster.openshift.com/vnc.html'
```

For a clean test:

```bash
oc rollout restart deployment/hotel-nav2-rmf -n ros2-rmf-hotel
oc rollout status deployment/hotel-nav2-rmf -n ros2-rmf-hotel --timeout=10m
```

Dispatch only after the camera path has been confirmed:

```bash
oc cp demo/dispatch_multilevel_task.py \
  "ros2-rmf-hotel/${POD}:/tmp/dispatch_multilevel_task.py"
oc exec -n ros2-rmf-hotel "$POD" -- bash -lc \
  'export HOME=/tmp/ros-home; export ROS_LOG_DIR=/tmp/ros-home/.ros/log; \
   source /opt/ros/jazzy/setup.bash; source /opt/rmf_demos_ws/install/setup.bash; \
   python3 /tmp/dispatch_multilevel_task.py robot_1 lobby L3_middle_hallway'
```

Monitor adapter logs, lift states, fleet state, Nav2 errors, map/costmap
switches, Gazebo processes, `/clock`, and the actual noVNC viewport. If the
run stalls or Gazebo crashes, restart the deployment and leave it healthy and
idle at L1 lobby.

## Editing and Deployment Constraints

- Use `apply_patch` for source/config edits.
- Do not commit changes unless explicitly requested.
- Preserve unrelated worktree changes.
- Do not use teleportation or broad tolerances to hide navigation failures.
- Verify runtime hashes and image digest after every image deployment.
- Prefer an immutable hotfix image tag for deployment experiments.
- Do not assume the public `jazzy` tag points to the current source.
- Keep the single-pod, one-domain architecture.
