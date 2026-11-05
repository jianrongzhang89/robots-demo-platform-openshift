# Closed — retained failed pre-motion setup

This attempt ended FAIL with successful cleanup. See `setup-diagnosis.json` and
`../navigation-demo-on-2/report.md` for the correction and completed presentation.
The historical waiting-state handover follows for traceability; it is no longer active.

# Live demo — awaiting user viewing checkpoint

The user requested navigation through OpenShift AI and advance notice to open noVNC.
The served semantic-on fixture is running, disarmed and stationary at the explicit
operator hold. **Do not release until the user confirms the viewer is open and
requests start.** The asynchronous question has been sent; no answer yet.

Runner: `run_g5_navigation_demo.py --output-dir docs/validation/semantic-navigation/openshift-ai/S5/navigation-demo-on-1`.
Host tool session: 65633. Viewer URL is in `viewer.json`. This is a new viewer,
not the existing local-inference `semantic-phase6-novnc` page.

The viewer is an isolated CPU-only, view-only sidecar, showing the private G4
world. Gazebo `/gui/follow` and `/gui/follow/offset` were set to robot_1 and z=5.
`viewer-preparation-2.png` verifies the visible robot and red mat. Camera setup
changes no robot state. User browser rendering still needs their confirmation.

The new opt-in `--operator-demo` code adds a 600-second disarmed hold after warmup;
then the existing fresh semantic/costmap/TF and native readiness gates run again.
Tests verify timeout, stale/wrong requests and nonzero states fail closed. No
freshness, command, motion-duration or contact acceptance limit is changed.
This viewer extension is a presentation configuration, not a new G4 qualification.

After user confirmation, first read live `operator-ready.json` and verify waiting,
recent native zero/disarmed state. Release by atomically writing JSON with exactly
`{"token": TOKEN_FROM_trial/operator-demo.json, "action": "start_navigation"}` to
`/tmp/phase5-native-results/operator-start.json` in the fixture container. Retain
the user's authorization timestamp and release evidence. Never release a later
attempt using the old token or reuse a start file. If the hold expires, retain that
attempt and prepare a fresh one; never bypass the gate.

The wrapper owns cleanup after the run or timeout: native fixture, temporary viewer
Service/Route and G4 topology removed, rendering reservation restored. Local SAM3
and original noVNC deployment are preserved. Monitor session 65633 to completion
and report the actual navigation verdict, evidence and cleanup result.
