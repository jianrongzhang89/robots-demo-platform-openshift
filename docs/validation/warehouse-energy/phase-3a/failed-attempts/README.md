# Stage 3A failed and preserved attempts

## First sweep launch: scripted-A-up-p0-v0.06-s0 (2026-11-17 12:42 UTC)

The first sweep launch stalled on its opening trial. `stage3_trial.py` set
`GZ_PARTITION=warehouse_stage3_trial` only in the Gazebo server environment;
the trial process's Gazebo transport node remained on the default partition,
so wheel command publications never reached the server and pose messages
never reached the trial. The robot stayed stationary while the
observation-only plugin kept sampling (179,362 actuator rows, zero pose
rows), and the trial ended on its wall deadline with no nonzero actuator
effort observed.

The attempt is preserved in the pod at
`/work/stage3-raw-failed-attempts/scripted-A-up-p0-v0.06-s0/` (its
`result.json` is retained here as `first-launch-result.json`). It produced
no dataset row. The fix removed the partition override so scripted trials
use the default partition exactly like the Phase 0 physics trials, matching
the trial-process node.

A second, independent infrastructure observation: the original foreground
`oc exec` sweep session was killed when its long-silent streaming connection
dropped, orphaning the stuck Gazebo server. The relaunched sweep runs
detached (`setsid nohup`) with a separate completion watcher, which survived
for the full two-hour sweep.

## Dataset build iterations

The first dataset build produced inverted mission windows for all 36
scripted descending runs (ramp-boundary crossings collected in ascending
order, so the ramp segment spanned a negative time interval and observed Wh
went negative). The independent audit caught all 36 before any use; a
synthetic perfect-observation descending-run unit test now guards the fix.
The first build also assigned per-segment physics to the wrong x-intervals
for descending runs (empty interval filter). Both defects were fixed before
the audited dataset was frozen; the raw evidence was never affected.
