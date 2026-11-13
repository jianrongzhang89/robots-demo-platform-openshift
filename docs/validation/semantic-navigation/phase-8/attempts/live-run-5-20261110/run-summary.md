# OpenRMF-integrated Phase 8 demo run

- Phase 8 pod: `semantic-phase8-nav2` (10/10 Ready)
- Simulator pod: `semantic-phase6-simulator` (4/4 Ready)
- RMF task: `compose.dispatch-d6ad7315b6` (`go_to_place phase8_dropoff`)
- Task submission: accepted; robot bid awarded to `phase8_semantic`
- Motion: observed active Nav2 goal and nonzero odometry; the robot reached the destination through Nav2
- Completion: Nav2 `Goal succeeded`; adapter logged activity completion after pose validation
- Ground truth at completion: `(19.2163, -31.5414)`; requested waypoint `(19.402, -31.594)`
- Robot is stopped near the destination; Phase 8 remains deployed for interactive demo use.

See `navigation-task-response.json`, `navigation-moving.json`, `navigation-idle.json`,
`adapter-live-run.log`, and `nav2-live-run.log` for runtime evidence.

The viewer showed the robot crossing the red mat directly. Although Nav2 accepted
semantic observations and logged merged costmap cells, the actual moving plan
was not captured, so this run does not demonstrate semantic-costmap avoidance.
The no-motion path preflight is separate evidence and does not override the
observed live trajectory.
