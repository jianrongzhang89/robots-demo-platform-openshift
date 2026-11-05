# Auto-follow demo — ready for viewing, navigation pending

Historical preparation snapshot. The subsequent viewer-authorized run20
completed; its camera/body data, 0.2900 m clearance, and slight independent
endpoint-tolerance miss are recorded in the sibling directory
`auto-follow-run20-20261030-170611/`.

User requested another demonstration, then asked to be notified when noVNC
was ready. Navigation was therefore held until the viewer's next “go”.

Only the standalone simulator and Nav2 pods were recreated. The new camera
startup entrypoint mount is installed; the startup log and tracking telemetry
confirm FOLLOW_LOOK_AT for robot_1, 5 m overhead offset, gains 0.02. SAM3,
router, signed-off fixture, mat geometry and safety settings were unchanged.

The preparation helper now requires two seconds of continuously fresh body
and wheel input before issuing its guarded turn, avoiding the prior startup
sample race. Turn passed: body yaw 0.520963 rad, wheel yaw 0.516164 rad.

`preflight19.json` records the corrected route via (15.402, -29.95) and
(19.402, -29.95), finishing at (19.402, -31.594), south-facing:

- Planned minimum hull clearance **0.4392 m**, no envelope intersection.
- Body/wheel differences **0.0029 m / 0.0048 rad**.
- **motion_dispatched: false**.

Both pods ready, noVNC HTTP 200. Robot stopped at the prepared spawn.
`ready-metadata.json` holds exact route and readiness status; tracking and
camera startup output, full preflight path, pod snapshots and guarded-turn
samples are retained alongside it. No navigation run occurred at this stage.
