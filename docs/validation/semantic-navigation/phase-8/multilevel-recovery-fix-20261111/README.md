# Multi-level corrective validation — 2026-11-11

**PASS:** the complete RMF-dispatched, OpenShift AI served-SAM3/Nav2 run completed on 2026-11-11, followed by a passing independent physical-evidence audit. Task `patrol.dispatch-05e0441862` ran `lobby (L1) → L3_middle_hallway → lobby (L1)` and finished idle on L1. The isolated tests below are supporting checks; the sign-off is based on the full run.

## Full-run acceptance evidence

| Check | Observed result |
| --- | --- |
| RMF floor transitions | L1 → L3 → L1 |
| Nav2 actions | 16 / 16 SUCCEEDED |
| Moving plans with semantic mat costs | 141; minimum hull clearance 0.741 m |
| Actual robot mat clearance | Minimum 0.771 m; required 0.200 m |
| Semantic plans after returning to L1 | 43, after map and semantic-memory reset |
| Served model | HTTP backend, pinned `sam3-mat-v1` identity; 3,093 emitted results |
| Lift support | Both native attachment/release cycles recorded; maximum robot/platform gap 0.0101 m |
| Physical L3 navigation | Recorded outside the cabin at 16 m elevation |
| Final physical position | L1, 0.049 m from lobby target, height 0.010 m |
| Maximum fleet/physical position difference | 0.198 m, below 0.750 m limit |

See [result.json](result.json), [audit.json](audit.json), [runtime.log](runtime.log), [physics.jsonl](physics.jsonl), and [payload.jsonl](payload.jsonl). The deployed release was Helm revision 26, using the digest pinned in `helm/phase8-multilevel-demo/values.yaml` and its mounted runtime sources.

Reproduce the independent audit from the repository root:

```sh
python3 demo/phase8_multilevel_audit.py \
  docs/validation/semantic-navigation/phase-8/multilevel-recovery-fix-20261111/result.json
```

This qualifies the requested simulator demo. Localization uses measured Gazebo planar pose, floor travel uses Nav2, physical cabin boarding uses the existing lift relay, and a temporary Gazebo fixed joint supports the robot during lift travel. OpenRMF dispatches and coordinates the route; OpenShift AI serves SAM3. No pose teleportation or local inference fallback was used. This is not production navigation qualification.

## Findings and corrections

- Freshness gaps triggered the default Nav2 recovery tree to clear the remembered semantic mat. The profile now uses a planning/following tree without costmap-clearing recovery. Fresh incoming captures still have a 0.5 s admission limit. An opt-in 5 s currentness window tolerates inter-capture gaps for this fixed mat, with semantic memory retained while the robot looks away. Floor transitions explicitly reset memory.
- Fleet position based on wheel odometry concealed physical drift and a falling robot. AMCL TF also diverged against the hotel floor drawing. The simulator profile now supplies measured Gazebo x/y/yaw as planar odometry and keeps wheel odometry on a diagnostic topic. Nav2 still plans and drives; this fixture does not command motion or teleport the robot.
- The inherited lift-exit flag survived early-return paths and could misclassify the next boarding goal. It is now consumed at the outward waypoint.
- The robot physically lost contact with the lift platform during ascent at the inherited 10 ms timestep and 2 m/s cabin limit. An initial 2 ms timestep / slower-cabin test passed, but attempt 8 reproduced loss of contact. Those settings alone were not a reliable fix. The profile now uses a temporary Gazebo DetachableJoint for the wheel-driven payload, acknowledged before travel and released at an open, stopped destination. Floor motion uses a 5 ms timestep and the Phase 6 rear caster supports; lift speed is 0.5 m/s with 0.3 m/s² maximum acceleration.
- Periodic replanning reset Regulated Pure Pursuit's position-reached state during final heading adjustment. The static-scene tree now replans after 0.20 m of translation, allowing in-place turns to finish.
- The inherited map generator erased shaft walls while clearing 2 m-wide lift lanes. The Phase 8 runtime restores the lift region from Gazebo's collision meshes and adds keepouts outside the physical platform. A Nav2 backup/exit test on L3 succeeded with the corrected map; regression tests check the wall, doorway, shaft, unchanged map cells, metadata and unsupported mesh rejection.
- An independent Gazebo monitor now records actual x/y/z and attitude. The trial cancels for stale physical data, a fall, lost upright support, mat intrusion, or excessive fleet/physical disagreement. Lift boarding requires fresh physical pose, an open stationary cabin, and the robot at the correct floor elevation.

## Evidence

- `isolated-payload-check.py`, `isolated-payload.log`, `isolated-payload-physics.json`: three physical L1/L3 round trips, native attach/detach acknowledgments, no attachment pose jump, and successful Nav2 backup after each release. Maximum support gap was 0.0101 m.
- `build.log`: semantic plugin build and 32 passing gtests (colcon aggregate reports 33).
- `attempt1-*`: recovery-tree correction; run interrupted by lifecycle failure after a live parameter change.
- `attempt2-*`: apparent floor travel invalidated by physical falling; no multi-level pass.
- `attempt3-*`: AMCL/physical position divergence; stopped before lift travel.
- `attempt4-*`: measured-pose navigation held mat clearance, but the physical monitor caught loss of lift support during ascent.
- `attempt5-*`: stopped for repeated final-heading resets during periodic replanning.
- `attempt6-*`: physical ascent passed; the L3 exit hit a wall erased from the generated map. Task canceled for map correction.
- `attempt7-*`: inherited shifted approach waypoint caused repeated RMF handoffs. Phase 8 now uses the RMF waypoint itself, with Nav2 XY/yaw tolerances inside the adapter acceptance bounds.
- `attempt8-*`: confirms that contact-only support could still fail even at the smaller timestep; canceled by physical monitoring.
- `isolated-l3-exit-*`: corrected-map Nav2 backup and exit both returned SUCCEEDED while physical height remained on L3.
- `isolated-lift-check.py`, `isolated-lift.log`, `isolated-lift-physics.json`: physics-only check. Robot was spawned inside Lift2 for this test, and direct lift requests exercised ascent/descent. This was not an RMF/Nav2/semantic navigation test.

All 20 Phase 8 Python regression tests passed: 14 existing adapter/semantic tests, 3 lift-map tests, and 3 payload-gate tests. Local checks also passed for Python compilation, shell syntax, Helm lint/render, source/config copies, both early-return lift-exit paths, and planar odometry offsets, measured speed, yaw wrapping and stale-input suppression.
