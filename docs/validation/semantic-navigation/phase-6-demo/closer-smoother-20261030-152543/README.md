# Closer/smoother standalone candidate — navigation pending

Historical preparation snapshot. The subsequent viewer-authorized run16
completed with 0.2818 m independently measured hull clearance and no
detected overlap. Results are in the sibling directory
`closer-smoother-run16-20261030-162738/`; readiness values below describe
the state before that run.

The enlarged mat remains 1.2 × 1.95 m at (17.4014, -31.594). The conservative
0.10 m hull-clearance envelope was not weakened. Changes are standalone D2
only, not changes to the signed-off private fixture.

## Discovery and correction

- The old preparation turned wheel odometry to about 0.52 rad, but Gazebo's
  model yaw stayed near zero. Old standalone clearance/overlap values are
  odometry-derived, not independently measured physical clearance.
- `preflight13.json` planned 1.0348 m hull clearance despite the closer
  waypoint. `costmap-diagnostics.json` records the misregistered mat:
  semantic cells extended roughly to Y=-29.475, north of the actual
  mat's north edge at Y=-30.619.
- D2-only rear supports were installed using the existing private support
  helper. The read-only `demo-ground-truth` sidecar observes Gazebo model
  poses independently of wheel odometry and publishes telemetry to Nav2.
  It is not a new TF authority or command path.
- The first telemetry launch exposed the transport13 subscription argument
  order mismatch; `truth-subscription-fix.json` fixed it. The five initial
  sidecar restarts predate that fix. A regression test now checks the call.

## Verified preparation, not a navigation run

- `truth-turn.json`: guarded preparation turn, stopped with body yaw
  0.520490 rad and wheel yaw 0.522281 rad. Maximum disagreement during the
  turn: 0.005249 m and 0.008248 rad. Final zeros were published.
- `aligned-costmap-diagnostics.json`: semantic projection moved back toward
  the visible mat. This does not establish full camera calibration.
- `aligned-preflight14.json`: 0.4670 m planned hull clearance, no envelope
  intersection. No navigation goal sent.
- `ready-preflight15.json`: final recheck with the updated pose guards;
  0.4730 m planned hull clearance, body-wheel errors 0.0053 m / 0.0018 rad,
  no envelope intersection. No navigation goal sent.
- `ready-metadata.json`: geometry, route, test counts, pending-run status.

Controller candidate: lookahead 0.5 m, desired speed 0.12 m/s, angular cap
0.45 rad/s, angular acceleration/deceleration 0.4/0.6 rad/s², inflation
0.60 m. Semantic obstacles remain lethal and global-only. The runner uses
body-pose clearance/steering samples, rejects invalid/replayed/stale input,
checks agreement again after planning and immediately before dispatch,
and cancels on pose loss, excessive disagreement, or envelope entry.

The route is explicitly waypoint-guided: via (15.402, -29.95), finish
(19.402, -29.95). Actual navigation clearance and reduced oscillation
remain **unverified until the viewer says “go” and a monitored trial runs**.

Tests: 51 semantic-demo tests plus 2 existing support-geometry tests passed;
`git diff --check` passed. noVNC HTTP 200. Simulator/Nav2/SAM3 ready; only
the simulator and Nav2 were recreated, SAM3/router left running.
