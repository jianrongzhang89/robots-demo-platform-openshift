# Command-lease renewal fix

Implemented the correction investigated after presentation runs 5 and 6.
The serving model, native receiver and all freshness/lease constants remain
unchanged. Live end-to-end navigation validation is pending run 7's operator
release; this does not resolve or qualify the separate wider-mat clearance issue.

## Behavior changes

- Repeated checked copies of the same captured source retain grace that has
  already been granted. A new source resets the allowance normally. The fix
  cannot turn a zero-only hold into extended nonzero motion, cannot inherit a
  setup budget on the first command, and cannot revive an expired gate.
- The coordinator evaluates its existing, newer-source-proven one-shot grace
  before forwarding a newly admitted command. This eliminates the intermediate
  ungraced packet followed by a later corrected packet.
- A packet already too short for the native receiver's 2 ms allowance causes
  explicit fail-closed `native_lease_margin_exhausted`, rather than transmitting
  a known-invalid lease. No deadline is extended to make the packet valid.
- The callback pump handles command ingress, task responses and fresh native
  status, then runs the full guard before observer callbacks. All work retains
  the same bounded callback count, and task responses still precede renewal.
  The existing ownership, evidence, command-join and native checks are retained.
- Bounded timing diagnostics now split TF witness, semantic lease, costmap,
  cancellation, scan-transform, command-drain/forward and coordinator stages.
  These measurements do not supply authority or change decisions.

## Validation

All **237 local safety tests pass**. Four new regression tests were also run
against the pre-fix source from git HEAD; all four fail there and pass with the
fix. Retained output: `before.log`, `after.log`, `local-tests.log`, and
`validation.json` (including source SHA-256 hashes).

Coverage includes the original 1.08445 ms packet case, preserving exactly one
25 ms grant across same-source copies, ordinary source-loss expiry and no
revival, a genuinely new source resetting grace, zero-hold-to-motion limits,
first-command setup-budget limits, grace applied before the first forward,
no-newer-source fail-closed behavior, and a simulated slow-observer workload
using the real Python final receiver. The latter loses the old lease under the
old scheduling order and retains it with the new order; authority still expires
normally when renewals stop.

Python compilation and whitespace checks pass. The actual native C++ guard is
unchanged; the private fixture runs its native/ROS integration suites before
entering the viewing hold. Run 7 retains its full source hashes and manifest.
`run7-source-check.json` compares staged control files against the tested source.

The historical investigation reproductions and outputs remain untouched; their
bug-expecting Python replay intentionally fails after the corrected source is
installed. Use the new regression tests to validate the fixed behavior.

## Live validation checkpoint

`../navigation-demo-on-7` used the restored 1.2 × 1.95 m mat and faster
view-only viewer after explicit operator release. The same-source renewal
failure did not recur before a separate fail-closed `native_capture_stale`
fault stopped navigation. See that run's report. This does not establish
successful end-to-end navigation or G4/G5 acceptance; further live validation
requires fixing the capture-processing backlog and a fresh operator release.
