# G5 navigation demo run 10

## Outcome

Navigation did not reach the requested far-side goal `(19.2, -32.4)`. The run
stopped with `command_expired`; the final physical pose was approximately
`(18.203, -33.422)`, 1.427 m from the goal. The native watchdog applied zero
within 0.687 ms of its trigger. The closed-graph, capture-mapping, independent
motion, contact, cancellation, and cleanup checks passed. The run is not a G5
qualification pass. Cleanup and the settled post-run preflight passed.

## Root cause

The ingress callback received a raw command with ROS capture stamp 70.930 s.
Its first join attempt found the native clock bracket not yet available. The
next join attempt occurred 21.6 ms after arrival, beyond the joiner's unchanged
20 ms wait bound, so the raw capture was discarded. Its matching checked
command consequently had no raw ledger entry and also expired. A later valid
checked command was processed 2.8 ms after the one-shot gate grace deadline.
The gate then stopped with `command_expired`; this was a command processing
latency failure, not a native clock fault or a physical collision.

## Correction

`HotelGuardAdapter.command()` now drains the bounded capture joiner immediately
after each provenance-validated raw or checked command arrives. The normal
observer tick retains its drain as a fallback. The existing 20 ms join limit,
capture-based ledger validity, publication-time check, and gate freshness
deadlines are unchanged. Since ingress and observer callbacks are serialized
by the single-threaded pump, the immediate drain does not introduce concurrent
joiner access.

No new navigation run was started after this code change. `git diff --check`
passed; tests and live demo were not run.
