# User-viewed navigation demo rerun 24

The noVNC route returned HTTP 200 and the fixture remained disarmed at spawn
until the user released its fresh operator token. Navigation then completed
with `goal_succeeded` at the far-side goal `(19.4008, -31.594)`. Independent
physical endpoint acceptance passed: the robot stopped at
`(19.33718, -31.53489)`, 0.08684 m from the goal, stationary and clear of the
far mat edge.

The wrapper returned 0. Cleanup passed: the fixture and noVNC route were
removed, the G4 topology was taken down, and the rendering reservation was
restored and Ready. An early settled preflight saw the G4 router pod still
terminating; after it disappeared, the final read-only preflight passed at
`preflight-after-navigation-demo-on-24-final.json`. G5 overall remains HOLD
pending broader acceptance criteria. No demo or noVNC resources remain active.

Evidence: `result.json`, `physical-endpoint.json`,
`operator-ready-before-user.json`, `operator-release.json`, and the full run
record under `trial/`.
