# G5 navigation demo run 12

## Outcome

The noVNC route returned HTTP 200, the viewer camera followed `robot_1`, and
the fixture reached its disarmed zero-command operator hold. The user released
the fresh run token. The robot moved, then the native safety status reported
`native_lease_margin_exhausted` and applied zero. At the captured stop status,
the physical pose was approximately `(18.657, -33.401)`, 1.139 m from the
requested goal `(19.2, -32.4)`. Navigation failed; this is not a G5 pass.

The fixture pod reached Failed before the runner could copy its runtime
summary/trace (`runtime-partial-copy.json` records `pod ended before evidence
retrieval`). Therefore the captured native status is retained as the stop
evidence, but packet-level root cause attribution is incomplete. The run
wrapper cleanup succeeded, the noVNC route and demo pod are gone, the rendering
reservation was restored, and the settled G5 preflight passed at
`preflight-after-navigation-demo-on-12.json`. G5 remains HOLD.

The ingress-drain correction is present in the source used for this run. The
installed adapter regression suite passed all 10 tests during setup. This run
does not establish that the ingress change fixed the previous command-expiry
failure; the native watchdog stopped for a distinct reported reason.
