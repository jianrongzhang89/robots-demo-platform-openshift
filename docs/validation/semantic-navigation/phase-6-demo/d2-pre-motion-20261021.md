# Phase 6D D2 — paired navigation evidence

Date: October 21, 2026  
Status: **DEMO PASS for the fixed, isolated simulation comparison** (three off/on pairs completed). This is not Phase 5 qualification, a general safety claim, or physical-robot authorization.

## Scope and candidate state

- The test used one isolated Gazebo `robot_1`, fixed `red mat` SAM3 prompt, fixed start near `(15.402, -31.594)`, fixed goal `(19.5, -31.594)`, identical planner/controller parameters, and a 0.10 m/s absolute cap.
- Semantic-off and semantic-on were selected by separate static Nav2 startup profiles. Simulator, map, scene, camera, SAM3 process, router, and motion-safety profile were shared. Nav2 was restarted between arms; no canonical hotel or Phase 1 resource was touched.
- Current candidate: simulator `semantic-phase6-simulator` (3/3), SAM3 `semantic-phase6-sam3` (2/2), and semantic-on Nav2 `semantic-phase6-nav2` (8/8, on `ip-10-0-39-214.ec2.internal`). The robot is simulated and stationary at the goal. The current isolated simulator accepts only `/robot_1/cmd_vel`; the Nav2 motion bridge exports only that velocity topic. No Nav2 action, RMF command, or physical robot route is bridged.

## Root causes found and D2-only corrections

1. **Command route discovery was not data delivery.** After the Gazebo subscriber retired, Zenoh retained route declarations but stopped delivering `cmd_vel` payloads. The exact-key `cmd_vel-route-keepalive` sidecar now holds only the private-router subscriber `robot_1/cmd_vel`; it has no publishers. Two simulator-side zero-only probes then received full zero Twist samples, including one more than 90 seconds after startup. This passed the transport subgate before any nonzero goal was retried.
2. **Simulator restarts left stale cross-pod clock/calibration routes.** SAM3 had RGB/depth but could not join them to live clock/capture/calibration context. Recreating the isolated simulator bridge and then the SAM3 bridge restored `/clock`, `CameraInfo`, RGB, depth, and capture/compression traces. SAM3 returned to `ready:true` with fresh results; capture age stayed within its configured 500 ms admission bound. Freshness checks were not weakened.
3. **Co-location starved Nav2.** While simulator and Nav2 shared `ip-10-0-38-113`, Gazebo consumed about 11.4 of its 12 CPU-limit cores and Nav2 about 1 core. Local costmap update timeouts aborted an initial semantic-on attempt. Nav2 was moved to the lightly loaded 8-vCPU node `ip-10-0-39-214` (with an explicit toleration for its `g5-gpu` taint; Nav2 requests no GPU). The simulator stayed on its original CPU node.
4. **Nav2 startup raced TF/input readiness.** Starting Nav2 before `/clock`, `/odom`, `/scan_fixed`, and `/tf` were flowing caused lifecycle activation failures and inactive costmaps. The D2-only rendered entrypoint now waits for samples on those four topics and a short settling interval before launching Nav2. The subsequent controller, planner, and both costmaps reached `active [3]`.

These fixes are isolated to the Phase 6D candidate renderer/profile. The D1 profile and canonical hotel configuration are unchanged.

## Preflight route contrast

At the fixed start, both semantic-on costmaps received fresh cost-200 cells and the planner succeeded. Across preflights, semantic-off produced **36 centerline samples** through the staged mat; semantic-on produced **0 centerline samples** in the mat rectangle. Example fresh semantic-on preflight counts were global/local **271/156**, **271/198**, and **267/195**. Semantic-on detoured laterally around the mat; semantic-off followed the direct route.

This is a visible planning contrast, not a footprint-clearance result. Earlier path inspection measured only about 0.44 m lateral offset from the mat center; the resulting clearance beyond the approximate mat edge is smaller than the robot's 0.22 m radius. The mat has no reported collision geometry. The robot hull may visually skim/overlap the marked mat even when the path centerline does not. Treat this as an illustrative semantic-cost demo, not validated collision avoidance.

## Paired motion results

Every compactly recorded goal trial below returned NavigateToPose status `4` (SUCCEEDED), stayed at or below the **0.10 m/s** cap, reported no cap breach, and recorded no Collision Monitor intervention.

| Pair / arm | Centerline samples through mat | Max odom / cmd speed (m/s) | Max angular (rad/s) | Duration (sim / wall s) | Final map pose |
|---|---:|---:|---:|---:|---|
| Pair 1 — off | 36 | Compact runner summary not retained; Nav2 logged goal reached | — | — | — |
| Pair 1 — on | 0 | Compact runner summary not retained; Nav2 logged goal reached | — | — | — |
| Pair 2 — off | 36 | 0.100 / 0.100 | 0.0372 | 37.45 / 37.40 | `(19.3063, -31.5707)` |
| Pair 2 — on | 0 | 0.100 / 0.100 | 0.2161 | 39.37 / 38.27 | `(19.3233, -31.6701)` |
| Pair 3 — off | 36 | 0.100 / 0.100 | 0.0385 | 37.41 / 37.35 | `(19.3070, -31.5708)` |
| Pair 3 — on | 0 | 0.100 / 0.100 | 0.2140 | 39.01 / 38.02 | `(19.3205, -31.6671)` |

Pair 1's terminal success is confirmed by Nav2's `Reached the goal!` log for both arms, but the terminal wrapper did not retain those two verbose runner summaries. Pairs 2 and 3 were captured with the new `--summary-only` option. Their runner output additionally confirms `collision_monitor_events: []`, `cap_breach: false`, and 390–393 speed-cap publications per semantic-on trial (374 per semantic-off goal trial). This evidence gap is disclosed rather than backfilled with estimates.

## Assessment and limitations

- The staged demo gate is met: three fixed-scene comparisons completed, all six goals succeeded, the intended route contrast was repeatable, and no speed-cap breach or Collision Monitor event was observed.
- The result is descriptive only. It does not establish statistical benefit, robust SAM3 recognition, obstacle/collision avoidance, safety certification, multi-robot/RMF operation, sustained-load performance, or production suitability.
- The semantic-on path's centerline avoidance does not establish robot-footprint clearance; the staged mat lacks collision geometry. Preserve this caveat in any presentation and avoid describing the behavior as safety-qualified.
- Do not use these results to authorize a physical robot or remove the geometry-only fallback. The deferred recognition-label review and held-out evaluation remain open.

## Implementation and validation record

The D2 renderer and runner are in [`render_phase6_demo_d2.py`](../../../../scripts/semantic-navigation/render_phase6_demo_d2.py) and [`run_phase6_demo_d2_trial.py`](../../../../scripts/semantic-navigation/run_phase6_demo_d2_trial.py). The renderer now has a separate Nav2-node selector and D2-only sensor/TF startup wait; the runner supports compact auditable summaries. Tests cover exact-key keepalive scope, static arm profiles, startup wait topics, and clock QoS.

Validation on October 21: all 25 D2/D1/topology tests passed, Python compilation passed, and `git diff --check` passed. Server-side dry-run accepted the separate-node Nav2 candidate. No commit or push was performed.
