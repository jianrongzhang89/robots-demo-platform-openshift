# Semantic navigation demos

Two ways to demo the Phase 6 capability (language-prompted obstacle
avoidance with a fail-closed safety chain). Phase 6 was signed off
October 30, 2026 — see
`docs/validation/semantic-navigation/phase-6/sign-off-review-20261030.md`.

## 1. Fixture demo (the qualified configuration) — `demo/semantic_navigation_demo.sh`

Runs the exact series-23 configuration (image `348fc584`, lookahead 0.5,
AMCL 2000–8000/0.1, endpoint-capture overlay, pose-delta stationary
predicate) through the private guarded fixture, one full trial per act
(~9–11 min each):

```bash
demo/semantic_navigation_demo.sh all            # baseline + semantic + faultstop
demo/semantic_navigation_demo.sh semantic       # just the detour act
demo/semantic_navigation_demo.sh --take-over-gpu all
```

- **baseline** (off-arm): the robot drives straight across the red mat
  (~1.4 m hull exposure).
- **semantic** (on-arm, lethal-254): SAM3 segments the mat from the
  prompt "red mat", the semantic costmap marks it, and the robot detours
  around it completely (0.000 m exposure).
- **faultstop** (on-arm): the camera path is cut mid-route; the guarded
  chain stops the robot fail-closed.

Each act prints a narrated summary (exposure contrast, clearance,
arrival divergence — belief-frame completions land ~0.4–1.2 m from the
goal; recorded per the sign-off). Evidence lands under
`docs/validation/semantic-navigation/phase-6/demo-runs-<timestamp>/`
(demo evidence, not qualification evidence).

**GPU note**: the fixture SAM3 and the standalone demo SAM3 share the
single GPU on `ip-10-0-18-251`. If the standalone demo is up, pass
`--take-over-gpu` (it deletes `semantic-phase6-sam3` for the demo
window).

## 2. Standalone demo (browser view) — the `semantic-phase6-*` pods

The isolated single-floor demo topology (private Gazebo partition,
noVNC browser view at the `semantic-phase6-novnc` Route). It shows the
live loop in a browser: the camera view, SAM3's mask, and the robot
navigating. **It runs a D1/D2-derived, demo-only configuration**, with
October 30 standalone changes described below. The fixture script above
is what represents the qualified behavior.

**Current standalone status:** the viewer-authorized camera-auto-follow
run20 completed with Nav2 SUCCEEDED, 0.2900 m independently measured minimum
hull clearance and no detected overlap. The robot is stopped on the opposite
side of the mat. Its actual target distance is 0.2150 m, slightly outside
the unchanged 0.20 m position tolerance despite belief-frame success; do not
treat action success as independent endpoint-tolerance proof. Camera follow
remained active. The corrected route below supersedes run16's bypass-only
endpoint. Await a new viewer “go” before another navigation run.

Revival steps (done October 30; repeat if it degrades again):

1. The SAM3 pod occasionally disappears / its zenoh bridge never
   re-dials. Recreate it from the manifest:
   `helm/semantic-navigation/phase6-demo-d1.yaml` (the `semantic-phase6-sam3`
   Pod document — needs ConfigMap `semantic-phase6-demo-bridge-config`
   and PVC `sam3-checkpoint`, both persistent).
2. If the GPU is held by the fixture SAM3 (`semantic-phase5-sam3`),
   delete that pod first (the fixture recreates it on demand).
3. Recreate the simulator pod for a fresh robot at the start pose facing
   the mat — after long runs the robot is elsewhere and the mat is out
   of camera view. **Use the MOTION bridge: patch the simulator pod's
   `sim-zenoh-bridge` arg from `sim-bridge-d1.json5` (the D1 stationary
   config, no velocity route — cmd_vel never reaches the robot) to
   `sim-bridge.json5` (identical publishers plus the `robot_1/cmd_vel`
   subscription). Both live in the `semantic-phase6-demo-bridge-config`
   ConfigMap.**
4. Set AMCL's initial pose (the demo Nav2 deliberately does not seed
   it):
   `ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped
   "{header: {frame_id: map}, pose: {pose: {position: {x: 15.402, y: -31.594}}}}"`
   Re-seed after EVERY simulator or Nav2 pod recreation (an odom reset
   leaves AMCL's estimate mid-route).
5. Open the noVNC Route in a browser and dispatch goals from inside the
   nav2 pod (the local machine has no rclpy):
   `ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose
    "{pose: {header: {frame_id: map}, pose: {position: {x: 19.402, y: -31.594}, orientation: {w: 1.0}}}}"`

## The paired demo acts on the standalone topology

The two arms are selected by the nav2 pod's config:
- **baseline**: ConfigMap `semantic-phase6-d2-nav2-config-off`
- **semantic**: ConfigMap `semantic-phase6-d2-nav2-config-on`
  (semantic layer enabled at soft cost 200)

To flip arms, recreate the nav2 pod from its live spec
(`oc get pod semantic-phase6-nav2 -o json`, strip `status`/`metadata`
runtime fields) with BOTH the volume's `configMap.name` AND the nav2
container's `PHASE6_PARAMS` env changed
(`/phase6-nav2-config/phase6-demo-nav2-on.yaml` — flipping only the
volume crash-loops the nav2 container on the missing off-yaml), then
re-seed the AMCL initial pose. Reset the simulator (step 3) to put the
robot back at the start, and dispatch the same goal.

**Scoping note (October 30, observed live)**: at the demo config's soft
cost 200 the planner nudges the route (~0.4 m on this scene) rather
than fully detouring — the same behavior the qualification pilot
recorded (`pair-1-on-globalonly`). The FULL detour with 0.000 m
exposure is the lethal-254 arm: set the on-config's
`semantic_layer.target_cost` to 254 (ConfigMap
`semantic-phase6-d2-nav2-config-on`, key `phase6-demo-nav2-on.yaml`) and
recreate the nav2 pod — or run the fixture demo
(`demo/semantic_navigation_demo.sh semantic`), which is the qualified
configuration with the recorded numbers.

**Lethal-254 gotcha (October 30, observed live)**: the D2-era on-config
carries the semantic layer in the LOCAL costmap as well — at lethal 254
this makes RPP's collision-ahead check abort on the marked cells and
the robot stops AT the mat with the recoveries failing
("RegulatedPurePursuitController detected collision ahead!" → "Costmap
timed out waiting for update" → goal ABORTED). The qualified
architecture is GLOBAL-ONLY: disable the local costmap's
`semantic_layer` (`enabled: false`) in the same configmap key before
running the lethal arm. A `SUCCEEDED` action status is not proof of
footprint clearance: the user observed the robot touch the mat.

### Earlier standalone no-touch candidates — October 30, 2026 history

**Measurement correction:** all standalone trial clearance/overlap figures
below, including runs 5 and 9–12, were calculated from wheel odometry plus
the fixed map offset, not independent Gazebo body poses. A subsequent
preparation check found wheel yaw near 30° while body yaw remained near 0°.
Those figures are retained as historical odometry-derived results, **not
physical clearance proof**. Their old tuning/preparation instructions are
superseded by the current candidate at the end of this document.

Read-only inspection of the live D2 pods found why the previous settings
did not guarantee clearance:

- The staged mat is a visual-only slab; it has no collision shapes. The
  semantic-on path was historically evaluated by centerline intersection,
  not robot-hull clearance.
- The live global semantic layer is lethal-254 and global-only, but the
  global inflation layer was disabled, so its configured radius had no
  effect. The controller can cut the corner into the visual mat even when
  the planned centerline avoids it.

The candidate was then deployed to the live D2 pods and motion-tested
(five measured trials, every failure retained): the prepared 2.7 m mat
left only 0.30 m between the start and the clearance envelope's west
edge — the >65° escape turn is kinematically infeasible for RPP, which
cut the corner every time and was fail-canceled by the monitor at
0.091 m hull clearance. The deployed revisions (all in
`render_phase6_demo_d2.py`, `install_phase1_camera.py`,
`demo_target_geometry.py`, and `phase6-demo-topic-bridges.yaml`, with
tests updated):

- **Mat 2.7 → 1.2 m** (~1.05 m of runway; the direct route stays blocked).
- **Inflation 1.0 m** global and local (0.45/0.60 measured insufficient:
  planned clearances 0.086/0.182 m, inside the corner envelope).
- **RPP lookahead 0.3 m** and **use_rotate_to_heading disabled** (the
  documented goal-checker deadlock; the envelope swing engages rotate
  mode on the base params and stalls at zero velocity).
- **Motion bridge allow regex anchored to `^/cmd_vel$`**: in the pinned
  zenoh-bridge version, a publisher route created from a remote
  subscriber announcement never creates its local DDS reader, so nav2's
  commands never left the pod (route shell, subscription count 0). The
  anchored regex forces local-publisher-side route creation; the sim-side
  bridge still receives via zenoh key matching.
- **Trial procedure** (per run, like AMCL seeding): pre-rotate the robot
  to ~0.52 rad (30°, toward the exit diagonal — past ~35° SAM3 loses the
  mat at the FOV edge), re-seed AMCL with that yaw, and dispatch the
  north-biased goal `(19.402, -31.2)` so the plan matches the heading.

**Measured passing trial** (`notouch-run5`, October 30): goal SUCCEEDED,
minimum hull clearance 0.2751 m (requirement 0.10 m), zero mat overlap,
clearance monitor never triggered, 0.15 m/s cap held, no collision
monitor events, 67 s. The no-motion preflight and the live trajectory
monitor both passed; the preflight plan cleared by 0.7525 m.

**Subsequent width change (October 30, user request):** the standalone
mat's across-route Y dimension is now **1.95 m**, three times the previous
0.65 m. Its X length remains 1.2 m, center `(17.4014, -31.594)` and
thickness 0.012 m are unchanged, and the distractor is unchanged. The
clearance monitor uses the same enlarged rectangle. The earlier passing
trials above used the narrower mat; their clearance numbers and the
30° preparation procedure do not validate navigation around this wider
geometry. Re-run the no-motion preflight before dispatching another goal;
no navigation was started as part of this size change.

**Wider-mat route adjustment:** changing only the final goal to
`(19.402, -30.2)` passed the plan preflight but did not complete the
live trial (`wide-mat-run9`): the conservative square-envelope monitor
canceled at the upper-left corner, with measured circular-hull clearance
0.1791 m and no recorded overlap. The square-envelope gate intentionally
remains stricter than the Euclidean clearance number; neither was relaxed.

The runner now accepts repeatable `--via X Y` approach waypoints. This is
an **explicitly waypoint-guided demo route**, not evidence of unconstrained
semantic avoidance. Preflight uses `ComputePathThroughPoses` and motion
uses `NavigateThroughPoses` with the identical ordered waypoints. The full
planned path and live trajectory retain the same clearance checks, and
the semantic-state check and speed cap remain enabled. Without `--via`,
the existing single-goal behavior is unchanged.

The first waypoint trial (`wide-mat-run10`) went north to
`(15.402, -29.0)`, crossed to `(19.402, -29.0)`, then returned to
`(19.402, -31.2)`. It held 0.5559 m measured minimum hull clearance, with
no overlap or clearance intervention, but **timed out after 240 s** while
circling at the final approach. It is not a passing navigation trial.

The revised candidate ends eastbound at `(19.402, -29.0)` after the single
northward waypoint `(15.402, -29.0)`, so the final approach matches the
requested east-facing goal heading. Goal tolerances remain unchanged.
After the usual fresh simulator, ~30° preparation and AMCL seed, run
inside the Nav2 container:

```bash
python3 /tmp/run_phase6_demo_d2_trial.py \
  --trial wide-mat-preflight --semantic-arm on \
  --expected-start-x 15.402 --expected-start-y -31.594 \
  --via 15.402 -29.0 \
  --goal-x 19.402 --goal-y -29.0 --preflight-only
```

Use the current runner and `demo_target_geometry.py` in `/tmp` (re-copy
after a Nav2 pod reset). The eastbound-finish preflight measured 1.1554 m
minimum hull clearance. After preflight passes, remove `--preflight-only`
to dispatch the monitored route.

**Measured widened-mat pass** (`wide-mat-run11`, October 30): navigation
SUCCEEDED in 85.45 s, with **1.0241 m minimum hull clearance**, no recorded
mat overlap, no clearance intervention, the 0.15 m/s speed cap held, and
no Collision Monitor events. The final recorded odometry-derived map
pose was `(19.2123, -28.9591)`. This is one passing waypoint-guided demo
trial with the 1.2 × 1.95 m mat, not a new semantic-navigation qualification.

Route diagnostics, the canceled single-goal trial, the timed-out waypoint
trial, and the passing eastbound-finish trial evidence
are retained under
`docs/validation/semantic-navigation/phase-6-demo/wide-mat-adjustment-20261030-143202/`.
The passing result and full trajectory are in `trial11-result.json` there;
`run11-metadata.json` records the geometry and route.

The signed-off fixture and its evidence remain unchanged.

### Current closer/smoother standalone candidate — first measured run completed

The user's October 30 request was to reduce the large mat standoff and
the visible left/right corrections. The 1.2 × 1.95 m mat remains centered
at `(17.4014, -31.594)`, and the conservative 0.10 m hull-clearance envelope
is unchanged. This remains an **explicitly waypoint-guided demo**, not a
new qualification or unconstrained semantic-avoidance result.

Changes confined to D2 (`render_phase6_demo_d2.py`):

- Lookahead 0.3 → **0.5 m**, desired speed 0.15 → **0.12 m/s**;
  regulated minimum 0.06 m/s, approach minimum 0.04 m/s, stateful pursuit
  disabled. Rotate-to-heading remains disabled.
- Smoother angular limit 0.8 → **0.45 rad/s**, angular acceleration/deceleration
  **0.4/0.6 rad/s²**; inflation 1.0 → **0.60 m** in both costmaps.
- D2-only rear ball supports reused from the private support helper;
  canonical assets and the signed-off fixture are untouched.
- Read-only `demo-ground-truth` sidecar publishes actual Gazebo model poses
  and finite-difference body velocity at 20 Hz. The bridge carries these to
  Nav2 as `/demo/ground_truth`; this is **not** a replacement odometry/TF
  authority or a command publisher.
- The runner measures clearance and steering using body poses, rejects
  stale/replayed/invalid pose input, checks body/wheel agreement before
  dispatch, and cancels on >0.5 s pose loss or >0.15 m / >0.15 rad disagreement.
  The existing rectangle preflight and live clearance envelope remain active.

The guarded preparation turn reached body yaw **0.52049 rad** and wheel yaw
**0.52228 rad**. Maximum discrepancies during that turn were **0.0053 m** and
**0.0083 rad**. The former metre-north semantic projection moved back toward
the visible mat after that physically verified turn; this is not a full
camera calibration claim.

No-motion preflight `closer-smoother-preflight14` passed for the waypoint
`(15.402, -29.95)` and eastbound finish `(19.402, -29.95)`: **0.4670 m planned
minimum hull clearance**, no envelope intersection. This is a closer plan,
**not yet measured physical navigation clearance or proof of smoother motion**.
The final readiness recheck (`closer-smoother-ready15`, updated runner)
also passed: **0.4730 m planned clearance**, 0.0053 m / 0.0018 rad body-wheel
disagreement, navigation not dispatched. noVNC returned HTTP 200.

With current runner and geometry copied into the Nav2 container, use the
corrected opposite-side route (the earlier bypass-only goal is superseded):

```bash
python3 /tmp/run_phase6_demo_d2_trial.py \
  --trial opposite-side-preflight --semantic-arm on \
  --expected-start-x 15.402 --expected-start-y -31.594 \
  --via 15.402 -29.95 --via 19.402 -29.95 \
  --goal-x 19.402 --goal-y -31.594 --goal-yaw -1.5707963267948966 \
  --speed-limit 0.12 --preflight-only
```

Only after a fresh preflight and the viewer's “go”, remove `--preflight-only`
and use a new trial ID to run navigation. Retain the full trajectory and
steering metrics (do not use `--summary-only` for evidence). After any reset,
repeat physical preparation/body-wheel agreement checks; the old wheel-only
`pre_rotate.py` procedure is insufficient.

Snapshots, the original misregistered preflight, costmap diagnostics,
guarded turn samples, and aligned preflight are retained under
`docs/validation/semantic-navigation/phase-6-demo/closer-smoother-20261030-152543/`.

**First measured navigation run (`closer-smoother-run16`, after viewer “go”):**

- Navigation **SUCCEEDED** in **50.751 s**, with **0.2818 m minimum measured
  hull clearance** from independent Gazebo model poses. No mat overlap or
  conservative-envelope entry was detected; no Collision Monitor events.
- Maximum measured body speed **0.1207 m/s**, within the 0.12 m/s cap's
  existing 0.005 m/s measurement tolerance. Peak body yaw rate **0.2391 rad/s**.
- Body/wheel agreement stayed within **0.0187 m / 0.0144 rad**; neither
  pose stream went stale and no cancellation guard triggered.
- The steering trace contains the two main route turns plus two small
  corrective phases (about +0.0455 and -0.1081 rad above the 0.05 rad/s
  reporting deadband). Some correction remains; this is not a claim of
  completely eliminated oscillation. Absolute body-yaw travel was 3.4217 rad.
  The path-direction proxy was 3.2578 rad versus the earlier 10.602 rad
  wheel-odometry proxy, not a controlled physical before/after comparison.
- A separate five-second body-pose observation confirmed the robot stopped
  near **(19.2160, -30.0001)**. No second navigation run was started.

Full result, 967 trajectory samples, steering phase analysis, Nav2 logs,
and independent stop confirmation are retained under
`docs/validation/semantic-navigation/phase-6-demo/closer-smoother-run16-20261030-162738/`.
This is one waypoint-guided demo pass, not a new qualification.

**Endpoint correction after run16:** the user expected the robot directly
opposite spawn across the mat, not to finish in the north bypass lane.
The corrected goal is **(19.402, -31.594)**, on the original spawn Y
centerline and beyond the mat's east edge. The route keeps the north bypass,
adds `(19.402, -29.95)` as a second waypoint, then approaches the goal
southbound. The new `--goal-yaw` option applies the same finish heading to
planning and navigation; setting it to -π/2 matches that final leg rather
than forcing an east-facing goal orbit. The default remains east, and goal
tolerances and clearance checks are unchanged.

The simulator and Nav2 were reset for the full demonstration. The first
guarded preparation turn stopped on a startup telemetry gap; evidence was
retained. After startup settled, the guarded retry passed (body yaw
0.52049 rad, wheel yaw 0.53428 rad). No navigation was dispatched.
`opposite-side-preflight17` passed with **0.4730 m planned hull clearance**,
no envelope intersection, body/wheel position error 0.0053 m and yaw error
0.0138 rad. At that preparation checkpoint the corrected endpoint had
not yet been motion-tested.

Preparation and full preflight path:
`docs/validation/semantic-navigation/phase-6-demo/opposite-side-preparation-20261030-163315/`.
The prepared robot then awaited a new viewer “go”.

**Corrected opposite-side run18 (after that “go”):** navigation SUCCEEDED
in **64.001 s**, with **0.2980 m minimum body-pose-measured hull clearance**,
no detected mat overlap, no clearance-envelope entry and no Collision
Monitor events. Maximum body speed 0.1228 m/s stayed within the unchanged
0.12 + 0.005 m/s allowance. Body/wheel differences remained below 0.0575 m
and 0.0279 rad; neither pose stream went stale.

The independent five-second stop observation confirmed the robot stopped at
**(19.36812, -31.45196)**, beyond the mat's east edge and within its Y span:
the intended opposite side of spawn. Actual distance to the requested
`(19.402, -31.594)` target is **0.1460 m**, within the unchanged 0.20 m
position tolerance. Terminal measured linear and angular speeds were zero.

There was only **one steering-direction change above the 0.05 rad/s
reporting deadband**: the initial left turn followed by the route's right
turns. No repeated left/right hunting appeared above that threshold;
smaller-rate corrections are not excluded by this metric. Peak body yaw
rate was 0.2392 rad/s. This remains one waypoint-guided demo pass, not a
new safety or semantic-navigation qualification.

Full result, 1,223 trajectory samples, steering/endpoint analysis, runtime
logs and independent stop confirmation:
`docs/validation/semantic-navigation/phase-6-demo/opposite-side-run18-20261030-163949/`.

### Gazebo/noVNC robot auto-follow

The standalone viewing camera now uses the behavior from
`rmf-hotel-world-openshift-ai`: **FOLLOW_LOOK_AT**, following and looking at
`robot_1` from an overhead offset of **(0, 0, 5 m)**, with follow/track gains
of **0.02**. This is the Gazebo browser viewing camera, not a change to the
robot's RGB-D sensor, perception pipeline, navigation or safety settings.

The missing startup handshake was added to `entrypoint-phase1.sh`: wait for
the GUI follow service, confirm the target/offset requests, wait for the
tracking subscriber, then send three bounded follow-mode requests. The
existing camera supervisor still handles recovery. Startup does not
continuously reassert tracking, so subsequent manual pan/zoom is not
repeatedly overridden by this initializer.

D2 embeds and mounts this entrypoint through its existing private ConfigMap
volume; no shared simulator-image rebuild or fixture change was needed.
**Use the updated D2 renderer when recreating the simulator.** The startup
mount takes effect on that next deployment; the current simulator was not
restarted. Its live GUI was attached in place, preserving the robot's stopped
position after run18. Gazebo reports the expected mode and both targets,
and the settled camera is centered above the actual body within 0.3 mm.

Validation: 54 tests passed, including bounded failure retries and the
service/subscriber/mode sequence; shell syntax and API mount dry-run passed.
noVNC returned HTTP 200. No navigation was dispatched to test moving-target
following; the robot remained stopped. Evidence:
`docs/validation/semantic-navigation/phase-6-demo/camera-auto-follow-20261030-165028/`.

**Subsequent demo preparation:** after the user requested another demo and
a notice before viewing noVNC, only the standalone simulator/Nav2 were
recreated. The new camera-startup entrypoint mount is now installed, and
its startup log and `/gui/currently_tracked` confirm automatic
FOLLOW_LOOK_AT attachment to `robot_1`. The guarded preparation turn and
`auto-follow-preflight19` passed: 0.4392 m planned clearance, 0.0029 m /
0.0048 rad body-wheel disagreement. noVNC HTTP 200, both pods ready.
Navigation remains stopped at the prepared spawn awaiting viewer “go”.
Evidence:
`docs/validation/semantic-navigation/phase-6-demo/auto-follow-demo-preparation-20261030-165858/`.

**Viewer-authorized auto-follow run20:** the corrected route completed in
**64.202 s**, with **0.2900 m minimum measured hull clearance**, no detected
overlap, no envelope entry and no Collision Monitor events. Maximum body
speed was 0.1229 m/s, within the unchanged 0.12 + 0.005 m/s allowance.
Body/wheel differences stayed below 0.0372 m / 0.0242 rad; neither pose
stream went stale. There was one steering-direction change above 0.05 rad/s.

Independent observation confirmed a stopped body at **(19.375669, -31.380661)**
on the east side of the mat, **0.214958 m from the requested target**.
This is a slight physical endpoint-tolerance miss, not an independently
verified 0.20 m arrival, even though Nav2 returned SUCCEEDED. No tolerances
were relaxed and no corrective run was dispatched automatically.

The read-only camera observer retained 677 fresh camera/body samples over
67.6 s, including 641 moving samples. Camera poses stayed finite near 5.01 m
height; moving horizontal follow lag peaked at 0.5562 m (95th percentile
0.5058 m). The GUI still reported FOLLOW_LOOK_AT for robot_1 at the finish
and settled above the stopped body. The auxiliary observer exited 134 after
writing its complete JSON output; stderr and data are retained. Simulator
and Nav2 remained healthy. This is a waypoint-guided demo result, not new
qualification evidence.

Full trajectory, camera/body recording, tracking telemetry, stop check and
observer diagnostic:
`docs/validation/semantic-navigation/phase-6-demo/auto-follow-run20-20261030-170611/`.
