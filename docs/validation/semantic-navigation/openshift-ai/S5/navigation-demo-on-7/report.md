# Navigation presentation run 7

Status: navigation **FAIL**, cleanup **PASS**, restored-state preflight
**PASS**. This was an explicitly released, single semantic-on presentation;
it is not G5 acceptance or a new navigation qualification.

## Result

- Operator release token `392aee97-e208-4284-98cb-32fff08f10b3` was accepted
  while the native fixture was disarmed with zero packets and zero velocity.
- Setup, semantic wiring, target cost containment, and the planned crossing
  passed. Semantic inference p95 capture age was 252.90 ms against the 500 ms
  limit. The viewer ran at about 21 FPS after startup.
- During navigation the native clock latched `native_capture_stale` at
  simulation time 230.294 s. The capture was fresh at native publication and
  10.44 ms old when its observer callback ran, but 107.41 ms old when the
  fixture processed it. The 100 ms processing-age safety limit therefore
  stopped motion. The guard reported `native_session_lost`; the navigation
  action ended stopped. This is a fail-closed capture-processing backlog, not
  the run 5 invalid-packet or run 6 lease-expiry signature.
- Final physical position was `(19.1859, -32.5435)`. The staged mat ends at
  `x=18.0014`, so the robot had reached the far x side from its spawn at
  `(15.402, -31.594)`. It stopped before reaching the old goal
  `(19.402, -31.594)`. A separate narrow target placement now sets the G5
  presentation goal to `(19.2, -32.4)`, near the observed landing point and
  still 1.20 m beyond the mat's far x edge. This change does not relax any
  safety limits or alter general Phase 6 trial defaults.

## Cleanup and retained evidence

All run-owned pod, ConfigMap, viewer Service/Route, and temporary G4 topology
resources were removed. Rendering reservation restoration succeeded. The
read-only G5 preflight then returned PASS. See `result.json`,
`trial/runtime/summary.json`, `trial/runtime/clock-events.json`,
`trial/runtime/stage-timings.json`, and
`../preflight-after-navigation-demo-on-7.json`.

The lease-renewal correction prevented the earlier short-lease failure from
being the observed stop in this run, but this attempt did not finish navigation.
The separate processing backlog must be addressed and another run requires a
fresh viewing-ready notice and explicit operator release.
