# Phase 1 amended-B semantic repeatability development attempts

These attempts are not counted in the accepted amended-B series. All are
preserved under `failed-attempts/` in this directory.

1. **B-up r2, first attempt (`semantic-320-B-up-r2-costmap-timeout`):** a
   transient Nav2 global-costmap update timeout at the final goal
   (`transfer`), with the robot already past the ramp and the red mat —
   `GridBased plugin failed to plan from (0.00, 0.00) to (14.00, 0.00):
   "Costmap timed out waiting for update"`. Same infrastructure flake as the
   original series; not a fixture or semantic failure. Excluded and re-run.
2. **B-down r2, first attempt (`semantic-320-B-down-r2-costmap-timeout`):** a
   costmap-update timeout early in the ramp descent (`b_top` to `b_bottom`
   goal), far from the red mat. Excluded and re-run.
3. **B-down r2, second attempt (`semantic-320-B-down-r2-retry1-costmap-timeout`):**
   a costmap-update timeout at the very first goal (`transfer` to `b_exit`),
   95 simulation-seconds into the run. Excluded and re-run after a longer
   settle period.

All three exclusions reproduce the costmap-update timeout flake documented in
the original series; none is a planner block at the red mat, and none is an
end-of-trial 429 status race.
