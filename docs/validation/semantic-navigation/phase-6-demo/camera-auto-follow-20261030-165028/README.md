# Gazebo/noVNC robot auto-follow

Restored the viewing-camera startup sequence supported by
`rmf-hotel-world-openshift-ai`, specifically
`entrypoints/entrypoint-hotel-nav2-rmf.sh`. The standalone entrypoint already
ran the camera recovery supervisor, but omitted initial follow attachment.

## Changes

- `scripts/semantic-navigation/entrypoint-phase1.sh`: bounded GUI readiness
  handshake, acknowledged robot target and overhead offset, tracking
  subscriber readiness, then three FOLLOW_LOOK_AT messages.
- `render_phase6_demo_d2.py`: embed and mount the entrypoint for new D2 pods
  without changing the pinned image or qualified fixture.
- Tests exercise successful command order and bounded failure when services,
  positive responses or the subscriber are missing; renderer checks cover
  the entrypoint mount and unchanged image.

## Live activation and verification

The exact initializer was run against the existing simulator's private
Gazebo partition. The simulator UID did not change; the robot was not reset
or commanded to move. The initializer only addresses GUI camera endpoints.

- Before: FOLLOW, legacy (-6, 0, 3) offset and 0.01 gain.
- After: **FOLLOW_LOOK_AT**, both targets **robot_1**, offset **(0, 0, 5)**,
  follow and track gains **0.02**.
- Settled camera (19.368004, -31.451754, 5.009994), independently observed
  body (19.368120, -31.451961, 0.010006): horizontal centering error 0.237 mm.
- Separate body-pose samples confirmed the robot stayed stopped.
- noVNC HTTP 200. No navigation run or moving-target acceptance trial was
  dispatched for this camera change.

The ConfigMap was updated. **The new entrypoint mount is for the next pod
deployment from the updated renderer**; the current GUI was enabled in
place rather than recreating its simulator. `d2-with-camera-auto-follow.yaml`
records the rendered resources; do not deploy/reset them during a viewer's
session without notice. A uniquely named server dry-run verified the mount.

## Evidence

- `tracking-before.txt`, `tracking-after.txt`: Gazebo camera mode/target telemetry.
- `camera-pose-*.txt`: actual GUI camera poses before/after settling.
- `stationary-body-check.json`: independent post-activation robot samples.
- `live-enable-camera.sh`, `live-enable.stdout`, `live-enable.stderr`: exact live initialization.
- `verification.json`: summary, centering error, no-restart/no-navigation checks.
- Simulator before/after snapshots and the exact ConfigMap patch.

54 unit tests passed; `bash -n` and server mount dry-run passed. No route,
speed, safety, RGB-D sensor, canonical RMF entrypoint or fixture changes.
