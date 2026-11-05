# Navigation completion correction

## Root causes and corrections

The early stops were real command-authority expirations. Run 13's final audit
relay hop took 50–70 ms, consuming most of the original source's lifetime.
The adapter also scanned its entire growing coordinator-event history on every
guard tick and checked command, even without an active Wait action. Run 16
had over 9,000 events. Increasing polling alone did not resolve that growing
workload. The adapter now reads Wait history only for an owned nonzero Wait
command, and the pump interleaves four command polls, task/native service and
guard updates with each individual observer callback. Source freshness,
capture joins, grace limits and native watchdog deadlines remain enforced.
Run 17 reached `goal_succeeded`; relay p95 was 4.594 ms (maximum 17.736 ms).

Physical arrival was a separate problem. Run 17's wheel odometry plus the
known spawn agreed with the simulator within 0.021 m, while AMCL differed by
1.425 m. The earlier standalone demo already used fixed `map -> odom` origin
alignment with wheel odometry, as documented in
`phase-6-demo/phase6-demo-profile-draft.md`. The opt-in operator demo now
restores that arrangement: AMCL's TF broadcast is disabled and one static
publisher owns the known spawn offset. Dynamic odometry and capture-time
sensor transforms remain live. This is a simulation-demo localization mode,
not a hardware localization solution or AMCL qualification.

An exploratory low-noise AMCL run (19) tracked physical pose more closely but
overshot and aborted. The position was approached while final heading remained
outside the goal checker's tolerance and rotate-to-heading was disabled. The
user requested a position across the mat, so the operator demo now accepts
any final heading and uses a 0.10 m XY goal tolerance. The discarded AMCL noise
tuning is not in the final configuration.

The goal is `(19.4008, -31.594)`, the reflection of spawn `(15.402, -31.594)`
across the mat center `(17.4014, -31.594)`. The wider 1.2 by 1.95 m mat remains.
The wrapper now requires successful navigation, a stationary disarmed robot,
physical distance at most 0.20 m, and a hull clear of the mat's far edge before
reporting success. An AMCL-only success can no longer hide a physical miss.

## Verification

- 238 safety unit tests passed, including scheduler backlog and short-lease
  scheduling regressions. The backlog regression fails with the old scheduler.
- The installed ROS adapter checks passed all 11 tests, including a history
  sentinel that rejects an unnecessary Wait-history scan during navigation.
- Five physical endpoint checks passed, including rejection of run 17's
  successful Nav2 result with its 1.456 m physical goal error.
- Run 20: fixture PASS, `goal_succeeded`, physical endpoint
  `(19.337374, -31.535040)`, goal distance **0.086598 m**, stationary, cleanup PASS.
  Full evidence is in `navigation-demo-on-20/`.
- Run 21 (same final configuration): fixture PASS, `goal_succeeded`, physical
  endpoint `(19.337159, -31.534839)`, goal distance **0.086892 m**, stationary,
  cleanup PASS. Both runs used OpenShift AI serving and semantic-on costmaps.
- `verification.json` records both physical endpoints, goal results, native
  stop metrics, relay latency and conservative clearance. Post-cleanup state
  is recorded in `../preflight-after-navigation-completion-fix.json`.

All exploratory attempts are retained: 14 and 16 stopped on leases; 15 and 18
were blocked before setup by a terminating temporary router; 17 completed in
Nav2 but missed the physical goal; 19 aborted after overshoot.

Minimum conservative hull clearance in run 20 was 0.0467 m, without mat
overlap. This is below the historical 0.10 m clearance target. These results
verify demo goal arrival and do not promote G5 acceptance or requalify its
fault matrix. G5 remains HOLD.

Both runs recorded `native_capture_stale` only in the idle tail after goal
success and the stationary window. Their active-motion capture-mapping checks
passed without a clock fault. The late events are retained in each run's
`clock-events.json`; they did not interrupt navigation.
