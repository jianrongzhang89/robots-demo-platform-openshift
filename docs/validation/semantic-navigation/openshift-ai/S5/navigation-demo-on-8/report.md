# Navigation presentation run 8

Status: fixture **PASS**, cleanup **PASS**, restored-state preflight **PASS**.
This was one user-released semantic-on presentation. It is not G5 acceptance or
a new navigation qualification.

## Navigation and safety result

- Fresh operator token `a4f740c0-6fa7-4225-ada0-e666b65dac1e` was released
  from a disarmed native state at spawn, with zero received motion packets.
- The goal was `(19.2, -32.4)`, beyond the enlarged mat's far x edge at
  `18.0014`. Nav2 returned `SUCCEEDED` (`goal_succeeded`). The guarded command
  chain and native stop checks passed; applied zero followed the completion
  trigger in 2.73 ms, and stationary was confirmed within 531 ms.
- Contact audit passed with no unexpected contacts. The physical trajectory's
  minimum hull clearance from the mat was 0.152 m, above the 0.10 m target.
- Semantic target costs remained contained: all 883 value-254 cells were
  inside the ground-truth mat region; none appeared in the local costmap.
- **Localization caveat:** at Nav2's “Reached the goal” timestamp, the native
  physical pose was `(19.205, -33.135)`, about 0.735 m from the requested goal.
  It ended at `(19.206, -33.135)`. Nav2's success reflects its AMCL belief; this
  presentation does not demonstrate physical arrival within the goal tolerance.
- A `native_capture_stale` clock event was recorded at sim time 286.348 s,
  after the task had succeeded and the contact/stationary window had ended.
  The active-motion command mapping recorded no clock fault, the action
  terminal reason remained `goal_succeeded`, and the overall fixture passed.
  This late idle-tail event did not stop the navigation.

## Cleanup and evidence

The fixture pod and ConfigMap, noVNC Service/Route, and temporary G4 topology
were removed; the rendering reservation was restored. The post-run G5 preflight
returned PASS. Evidence is in `trial/runtime/summary.json`, `trace.jsonl`,
`clock-events.json`, `guard-events.json`, and `stage-timings.json`, plus
`result.json` and `../preflight-after-navigation-demo-on-8.json`.

The run exercised the lease-renewal correction without reproducing the run 5/6
short-lease stop. G5 remains HOLD; the physical goal/localization divergence
needs to be resolved before describing this as a completed physical arrival.
