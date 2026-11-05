# Recording rerun 6 — November 4, 2026

**Navigation FAIL.** This fresh run was explicitly requested for recording and
released by the user's fresh “go”. The robot stopped before reaching the goal.
No model, motion, controller, or freshness limit was changed for this rerun.

The first native fault is `lease_expired`, causing coordinator
`native_session_lost` and action cancellation. The last accepted native sequence
was 4129. Renewals 4130/4131 were emitted, but the native session had expired
before a renewal was accepted. Zero was applied **1.992 ms** after the native
trigger. Distinguish this from run 5's `packet_invalid` first fault. No native
capture-clock fault was recorded in run 6. The exact source of the renewal
timing delay remains unresolved; these records do not isolate CPU scheduling
from transport/receive-path delays.

- Path length 2.761 m; final matched physical goal distance **2.265 m**.
- Conservative 0.246 m circular-hull evaluation: minimum clearance **−0.006 m**,
  exposure **0.121 m**. Thus the run also does not establish strict mat avoidance.
  This is estimated hull overlap, not evidence of a physical mat collision.
- Native stationary-after-task and physical contact audit passed; no unexpected
  physical contacts. The visual-only mat is outside the physical-contact test.
- OpenShift AI served timing passed: capture-age p95 **253.760 ms**, 6.986 results/s.
- Restored mat 1.2 × 1.95 m. Viewer median **20.86 FPS**, minimum 18.10 after
  startup. These are renderer measurements rather than browser delivery FPS.
- HTTPS 200, WebSocket 101 and RFB greeting were verified before notifying user.

See `demo-summary.json`, `operator-release.json`, `viewer-navigation.png`, and
`trial/runtime/trace.jsonl`, `native-link-sends.jsonl`, `guard-events.json`.
The failed run is retained; no automatic retry or G4/G5 acceptance is claimed.

Wrapper cleanup PASS: removed private fixture/viewer/topology and restored the rendering reservation. Restoration preflight is retained at `../preflight-after-navigation-demo-6.json`.

Run6 cleanup/restoration verified: settled preflight PASS (`preflight-after-navigation-demo-6-settled.json` in S5). Initial check observed the terminating router and remains retained as HOLD. G5 acceptance status remains HOLD.
