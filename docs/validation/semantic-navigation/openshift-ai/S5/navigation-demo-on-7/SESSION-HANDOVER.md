# Lease-fix validation — run 7

Wrapper shell session 55158. Readiness/connection check session 89266.
No start release sent. User requested implementing the lease fix; prior viewing
workflow requires notice before navigation and a fresh “go”. Token/release path
are in trial/operator-demo.json. Verify fresh waiting/disarmed/zero-packet state
before atomically writing the exact matching token/action start request.

See ../lease-renewal-fix/report.md: 237 local tests pass, 4 targeted failures
reproduced on old code and pass on new code. Same-source grace preserved;
existing grace applied before checked forward; inadmissible lease causes explicit
stop; full guard runs before observer batch; finer timing instrumentation.
Safety constants, native receiver and serving runtime unchanged. Wider-mat
clearance remains a separate unresolved validation item. G5 remains HOLD.

Wait for connection verification before readiness notification. The viewing
hold is 600 seconds; never release stale/expired sessions or reset a clock.
After user release, monitor original fixture outcome and collect timing/clearance;
let wrapper clean up and restore reservation, then run settled preflight.
