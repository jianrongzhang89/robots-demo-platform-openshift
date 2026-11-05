# G5 navigation demo run 13

## Outcome

The noVNC viewer was verified ready while the robot was disarmed, and the user
released the fresh operator token. The robot moved, then navigation failed with
guard reason `command_expired`; the native status subsequently reported
`lease_expired`. Final settled physical pose was approximately
`(18.591, -33.336)`, 1.116 m from the requested goal `(19.2, -32.4)`.
Nav2 terminated with status 5. This run is not a G5 pass.

Native stop metrics passed: zero was applied 1.910 ms after the native watchdog
trigger, and the robot became stationary about 1.103 s after the trigger. The
clock mapping had no fault, contact audit was clear, and the other fixture
checks passed. Cleanup removed the demo pod and noVNC route and restored the
rendering reservation. Settled G5 preflight passed at
`preflight-after-navigation-demo-on-13.json`.

The bounded ingress drain correction was active. The saved joiner diagnostics
show the final raw capture was joined, but the trace still ends in
`command_expired`; this run does not validate the correction as a fix for the
stopping issue. Full runtime evidence is retained under `trial/runtime/`.
