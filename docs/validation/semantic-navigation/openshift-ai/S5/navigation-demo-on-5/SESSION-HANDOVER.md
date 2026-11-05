# Closed corrected presentation — run 5

Run 5 consumed its fresh user “go” and completed with navigation FAIL, cleanup
PASS. Do not reuse its token. The temporary noVNC route is removed.

See report.md and demo-summary.json: restored 1.2 × 1.95 m mat; viewer median
20.97 FPS; native first fault packet_invalid → native_session_lost; later
native_capture_stale is secondary. Conservative hull exposure is 0.331 m,
minimum clearance −0.055 m. No unexpected physical contacts; robot stopped.
Serving observation p95 255.918 ms passed. Full wider-mat navigation remains
unresolved; no automatic retry or G4/G5 acceptance. Source safety limits unchanged.

The sampler lifetime correction succeeded (no early resource_probe exit).
Next work: diagnose packet timing and restore adequate wider-mat hull clearance,
using the prior D2 evidence without claiming this fixture reproduces all D2
controller/waypoint/localization adjustments. Preserve failed runs and fresh
operator notification before any further navigation.

Final restoration preflight PASS: `../preflight-after-navigation-demo-5-settled.json`. Initial post-cleanup check caught a terminating router and remains HOLD evidence. Native zero applied 4.322 ms after packet-invalid trigger.
