# Phase 8 demo-scoped sign-off record

**Current disposition (2026-11-13): PASS for the selected Phase 8 demo use
cases.** The completed OpenRMF-dispatched, OpenShift AI-served SAM3/Nav2 run
covered L1 semantic-mat avoidance and the single-robot L1 → L3 → L1 lift
transition. Task `patrol.dispatch-71ef8eb28b` passed the independent audit,
returned to `phase8_spawn` within 0.019 m, retained 0.625 m minimum physical
mat clearance, and recorded moving semantic plans that cleared the mat by at
least 0.651 m. The audit also passed floor-transition and lift-support checks.
See the [current Phase 8 demo guide](../phase-8-demo/README.md) for the run
summary and the demonstrated OpenRMF, Nav2, and served-SAM3 roles.

This is a demo-scope pass only. It does not qualify production operation,
general multi-floor behavior, multiple robots, delivery handoffs, or
fleet-wide reliability. The November 10 observations below are retained as
historical findings and were superseded by the passing run above.

**Update (2026-11-11):** The Phase 6 fix has now passed an RMF-dispatched live
semantic-avoidance run with 0.8105 m physical hull clearance. See the
[current carryover validation](phase6-fix-carryover-validated-20261111/README.md).
The results below preserve the earlier November 10 investigation.

**Historical disposition (2026-11-10):** RMF task dispatch and
moving-cancellation demos were ready for reviewer sign-off. Semantic-obstacle
avoidance was not demonstrated by that live motion run.

## Demonstrated scenarios

1. **RMF go-to-place with Nav2.** RMF accepted task `compose.dispatch-9df0ddaafa`.
   Nav2 drove from the west staged pose to the east waypoint. Nav2 reported `Goal succeeded`,
   and the adapter logged that the RMF activity finished after Nav2 success and
   pose validation. The simulator ground-truth pose sampled immediately after
   completion was `(19.205, -31.598)`, about 0.20 m from the requested
   `(19.402, -31.594)` waypoint. See `navigation-task-response.json`,
   `navigation-moving.json`, `adapter-live-run.log`, and `nav2-live-run.log`.
2. **Cancel while moving.** RMF accepted task `compose.dispatch-1523bca378`.
   The monitor observed an executing Nav2 goal and odometry speed of 0.12 m/s.
   Cancellation returned success; afterward Nav2 was inactive and measured
   speed was 0.0 m/s. The adapter log records confirmation of terminal Nav2
   cancellation and zero measured velocity. See `cancellation-task-response.json`,
   `cancellation-moving.json`, `cancellation-response.json`,
   `cancellation-stopped.json`, and `adapter-live-run.log`.
3. **Semantic path preflight.** The live no-motion Nav2 preflight passed with a
   5.673 m planned route around the staged mat, compared with a 4.0 m direct
   route. Its minimum sampled clearance to the semantic mat region was 0.433 m.
   This is a map-path check, not a physical-contact or footprint-safety result.

## Semantic-obstacle result

Nav2 logs show semantic observations accepted and semantic cells merged into the
global costmap. The separate no-motion path preflight produced a detour around
the staged mat. However, the actual moving Nav2 plan/trajectory was not captured,
and the viewer observation was that the robot crossed the red mat directly.
Therefore the live motion run does **not** demonstrate semantic-costmap
avoidance. The active costmap layer and preflight are not enough to claim the
moving route used those costs. A future run must capture the moving plan against
the semantic costmap before making that claim.

## Issue fixed

The original Phase 8 clone published Nav2 velocity on the Zenoh route but did not
accept the matching remote subscriber on that same bridge. As a result, Nav2
produced velocity samples while Gazebo received none. Phase 8 now clones the
bridge ConfigMap and enables the matching command subscriber only in the isolated
Phase 8 pod. A bounded command moved the simulator from x=15.402 m to x=15.601 m;
the scene was reset before the RMF scenarios. The Phase 6 bridge ConfigMap was
left unchanged. The clone and before/restore pod manifests are retained beside
this record.

## Observability limit

The `/dispatch_states` sample after the navigation activity finished still
included the task as assigned, while the fleet monitor showed no active robot
task, Nav2 was inactive, odometry speed was zero, and the adapter logged
successful activity completion. Therefore this sign-off uses the Nav2 result,
adapter completion/stop logs, robot pose, and cancellation monitor as the
completion evidence. It does not claim that the dispatcher task-history view
cleanly transitioned to a terminal state.

## Restore and reproduction

The Phase 8 pod and temporary ConfigMaps were removed, and the saved Phase 6
Nav2 and simulator pods were restored. Evidence includes the pre-demo pod
manifests, Phase 8 bridge ConfigMap clone, live pod/log snapshots, and task
responses in this directory. Re-run `scripts/semantic-navigation/phase8_topology.py
up --evidence-dir <new-empty-evidence-directory>` to recreate the isolated demo;
run its `down` command with the same evidence directory to restore Phase 6.
