# Phase 1 semantic repeatability development attempts

These attempts are not counted in the accepted repeatability series. All three
are preserved under `failed-attempts/` in this directory. The accepted series
itself is one clean run per repeat index (`semantic-320-<route>-<direction>-r<N>`)
with every attempt, passing or failing, recorded here.

1. **A-up r3, first attempt (`semantic-320-A-up-r3-http429`):** the route,
   RGB-D transport, energy trace, and SAM3 labels all passed; all four Nav2
   goals succeeded. The independent semantic audit failed because the trial's
   final semantic status snapshot caught a transient inference HTTP 429. The
   pinned model server admits one inference at a time and rejects concurrent
   arrivals immediately (`apps/semantic-model-server/server.py`, overload path);
   with 10 Hz arrivals against roughly 125 ms inference, the instantaneous
   end-of-trial status can record a rejected request even though valid results
   flowed throughout the run. The attempt is excluded and r3 was re-run.
2. **B-up r3, first attempt (`semantic-320-B-up-r3-planner-blocked`):** a
   genuine navigation failure. Nav2's global planner aborted the goal toward
   `b_top` — `Failed to create a plan from potential when a legal potential was
   found` from (6.15, 5.79) to (22.00, 6.00) — with the robot stopped on the B
   ramp immediately before the red-mat lethal region at `[7.0, 6.3]` m. This
   reproduces, on route B, the failure mode documented for the early A-down
   attempt (mat at `[4.5, 0.3]` m): the semantic lethal projection sometimes
   leaves no legal corridor on the ramp. The attempt is excluded from the
   series and counted as a B-up repeatability failure in the report; it was
   not re-interpreted as a pass.
3. **B-up r3, second attempt (`semantic-320-B-up-r3-retry1-http429`):** the
   route passed completely, including all six Nav2 goal terminals and the
   semantic detour; the semantic audit failed for the same end-of-trial 429
   status race as attempt 1. Excluded and re-run.
4. **B-up r3, third attempt (`semantic-320-B-up-r3-retry2-http429`):** the
   route passed completely, including all five Nav2 goal terminals and the
   semantic detour; the semantic audit failed again on the same end-of-trial
   429 status race. Excluded and re-run.
5. **B-down r1, first attempt (`semantic-320-B-down-r1-costmap-timeout`):** a
   transient simulation-load failure at ramp entry. Nav2 aborted the second
   goal (`b_exit` to `b_top`) with `GridBased plugin failed to plan from
   (0.00, 0.00) to (22.00, 6.00): "Costmap timed out waiting for update"` —
   the global costmap missed its update deadline while the planner still held
   a default pose, roughly nine seconds into the run. The red mat was never in
   view (`nonempty_target_masks: 0` is expected for the truncated route). This
   is a costmap/planner timing flake under load, not a semantic or
   navigation-logic failure. Excluded and re-run.
6. **B-down r2, first attempt (`semantic-320-B-down-r2-costmap-timeout`):** the
   same transient costmap-update timeout, this time late in the route. The
   robot had already passed the red-mat region on the descending B ramp and
   Nav2 aborted the `b_top` to `b_bottom` goal with `GridBased plugin failed
   to plan from (0.00, 0.00) to (2.00, 6.00): "Costmap timed out waiting for
   update"`. Excluded and re-run.
7. **B-down r2, second attempt (`semantic-320-B-down-r2-retry1-http429`):** the
   route passed completely, including all five Nav2 goal terminals and the
   semantic detour; the semantic audit failed on the same end-of-trial 429
   status race. Excluded and re-run.
8. **B-down r3, first attempt (`semantic-320-B-down-r3-costmap-timeout`):** the
   third occurrence of the transient costmap-update timeout, again aborting
   the `b_top` to `b_bottom` goal with `GridBased plugin failed to plan from
   (0.00, 0.00) to (2.00, 6.00): "Costmap timed out waiting for update"`,
   midway down the B ramp before the red mat entered the camera's detectable
   range. Excluded and re-run.
9. **B-down r3, second attempt (`semantic-320-B-down-r3-retry1-costmap-timeout`):**
   the fourth costmap-update timeout, failing at nearly the same ramp position
   as attempt 8. Investigation of the pod during this attempt found that each
   trial leaves unreaped zombie process entries (the container's PID 1 does
   not reap), but zombies consume no CPU or memory and were ruled out as a
   cause; the timeout remains a transient simulation-timing flake at RTF 3.
   Excluded and re-run.
10. **B-up r3, fourth attempt (`semantic-320-B-up-r3-retry3-costmap-timeout`):**
    the fifth costmap-update timeout, aborting the very first goal
    (`loading` to `fork`) 61 simulation-seconds into the run. The runtime
    container showed no resource pressure (434 MiB of 8 GiB, no OOM, no CPU
    throttling), so the flake is attributed to node-level contention. A
    two-minute settle period was added before the next retry. Excluded and
    re-run.
11. **B-up r3, fifth attempt (`semantic-320-B-up-r3-retry4-planner-blocked`):**
    a second genuine mat-corridor planner block, with the same signature and
    ramp position as attempt 2 (`Failed to create a plan from potential when
    a legal potential was found`, planner start `(5.42, 5.92)`, goal
    `b_top`). Two genuine planner blocks in seven B-up route attempts
    establish that the B-route red-mat position `[7.0, 6.3]` m is not
    robustly repeatable; this is reported as a repeatability finding and is
    not resolved by retrying. Excluded and re-run.
12. **B-up r3, sixth attempt (`semantic-320-B-up-r3-retry5-planner-blocked`):**
    a third genuine mat-corridor planner block at the same position (planner
    start `(5.62, 5.92)`, goal `b_top`). With three genuine planner blocks in
    six attempts at this slot, the series was stopped with the user's
    approval and B-up is reported as 2 of 3 audited passes; the slot is not
    re-rolled further. The B-route red-mat position remains the documented
    blocker for closing the B-up repeatability gate.

The accepted repeatability series therefore contains eleven passing trials:
three per route/direction for A-up, A-down, and B-down, and two for B-up. The
twelve preserved attempts above are not counted as PASS evidence and are not
used to reinterpret any modeled Wh result.

The inter-trial cooldown in the series driver (90 s) was added after attempt 1;
it reduces background contention but cannot eliminate the end-of-trial status
race, which is intrinsic to the single-admission server design and the
10 Hz request rate of the qualified configuration.
