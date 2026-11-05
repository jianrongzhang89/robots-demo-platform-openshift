# User-viewed navigation demo rerun 23

The demo was staged at the noVNC route and held disarmed until the user
explicitly released the fresh operator token. Navigation then completed with
`goal_succeeded` at the far-side goal `(19.4008, -31.594)`. Independent physical
endpoint acceptance passed: the robot stopped at `(19.33727, -31.53497)`,
0.08672 m from the goal, stationary and clear of the far mat edge.

The demo wrapper returned 0. Cleanup passed: the fixture pod and noVNC route
were removed, the G4 topology was taken down, and the rendering reservation
was restored and Ready. The immediate post-run preflight briefly reported
HOLD because G4 pods were still terminating; after teardown settled, the
read-only preflight passed at
`preflight-after-navigation-demo-on-23-settled.json`. G5 overall remains HOLD
pending its broader acceptance criteria. No demo or noVNC resources remain
active.

Evidence: `result.json`, `physical-endpoint.json`,
`operator-ready-before-user.json`, `operator-release.json`, and the full run
record under `trial/`.
