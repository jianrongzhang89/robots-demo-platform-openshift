# Corrected opposite-side endpoint — prepared, navigation pending

Historical preparation snapshot. The subsequent viewer-authorized run18
reached the corrected opposite-side destination with 0.2980 m independent
minimum hull clearance and no detected overlap. Results are in the sibling
directory `opposite-side-run18-20261030-163949/`.

The user clarified that run16 stopped at the wrong destination: the bypass
lane rather than opposite the spawn across the mat. Its measured clearance
result remains valid for that shorter route; it did not satisfy the intended
destination.

Corrected waypoint-guided route:

- Start (15.402, -31.594), physically prepared near 0.52 rad yaw.
- Via (15.402, -29.95), then (19.402, -29.95).
- Finish **(19.402, -31.594)**, south-facing (-π/2) to match the final leg.

Mat remains 1.2 × 1.95 m at (17.4014, -31.594), with the unchanged conservative
0.10 m hull-clearance envelope and 0.12 m/s speed cap. No goal tolerance or
watchdog was relaxed. The signed-off fixture was not modified.

Only the standalone simulator and Nav2 pods were reset. The first guarded
preparation turn stopped on a simulator-startup telemetry gap and published
zeros (`truth-turn-startup-abort.*`). It was not a navigation run. The retry
after startup settled passed (`truth-turn.json`): body yaw 0.520487 rad,
wheel yaw 0.534278 rad. Final zeros were published.

`preflight17.json` records the full planned path and exact goal/heading:

- Minimum planned hull clearance **0.4730 m**; no envelope intersection.
- Body/wheel position error 0.0053 m, yaw error 0.0138 rad.
- **motion_dispatched: false**.

The runner now accepts `--goal-yaw` (default zero/east) so a southbound
finish need not circle to achieve an east-facing orientation. Both planner
and navigation use that same final quaternion. All 51 semantic-demo tests
passed, including default and southbound final-heading checks.

The corrected route has not yet been motion-tested. Await the viewer's
new “go” before navigation. See `ready-metadata.json` for exact arguments.
