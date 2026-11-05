# Corrected presentation run 5 — November 4, 2026

**Navigation FAIL; cleanup PASS.** The fresh user “go” released this run's
operator hold. The restored mat and smooth viewer are verified, but this run
does not establish acceptable navigation around the wider mat.

- Staged mat: 1.2 × 1.95 m, matching historical standalone D2 geometry.
- Global semantic costmap: 883 lethal-254 cells, all within the evaluator's
  target containment bounds. Local costmap uses the existing non-semantic setup.
- Viewer renderer after startup: median 20.97 FPS, minimum 18.33 FPS
  (289 samples). This measures renderer FPS, not browser delivery FPS.
- Verified public HTTPS page 200, WebSocket upgrade 101, and RFB greeting.
- Native first fault: `packet_invalid`, followed by coordinator
  `native_session_lost` and goal cancellation. The native-link log shows a
  1.08445 ms lease window enqueued and sent with tight timing immediately before
  the fault. Transport/scheduling timing is a suspect, not a proven root cause.
- The `native_capture_stale` latch (103.292 ms processing age) occurred later,
  after the native stop; it was not the initial navigation cancellation cause.
- Robot stopped; contact audit passed with no unexpected physical contacts.
  The mat is visual-only, so the contact audit cannot establish mat clearance.
- Conservative circular-hull evaluation (radius 0.246 m): **0.331 m of mat
  exposure**, minimum clearance **−0.055 m**. This is estimated hull overlap,
  not a measured physical collision. Path length was 5.214 m.
- At the final matched control sample, physical goal distance was 0.676 m,
  belief goal distance 1.178 m, and belief/truth divergence 1.386 m.
- OpenShift AI served observation timing passed: p95 255.918 ms (500 ms limit),
  6.986 observations/s. No model or safety threshold changed.

See `demo-summary.json`, `native-stop.json`, retained trial records, and
`viewer-navigation.png`. No automatic rerun was launched. The wrapper removed
the temporary viewer/private topology and restored the rendering reservation.
G5 remains HOLD. Further work must address the native packet timing failure
and conservative hull clearance with the enlarged presentation geometry.

The native guard applied zero 4.322 ms after the packet-invalid trigger
(`native-stop.json`). The first restoration preflight observed a router pod
still terminating and therefore returned HOLD; its record is retained.
The settled restoration check is `../preflight-after-navigation-demo-5-settled.json`.
