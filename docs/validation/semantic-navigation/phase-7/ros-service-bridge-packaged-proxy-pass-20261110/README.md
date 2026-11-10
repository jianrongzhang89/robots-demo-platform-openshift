# Packaged Phase 7 cancellation-proxy bridge fixture — November 10, 2026

## Result

The isolated three-domain ROS bridge integration Job passed. Runtime candidate
`semantic-safety@sha256:d153b717d2d6656d0b656c1c0080012213e8d85e3aca463c1f44df56b2683a77`
(build #44) ran both the cancellation-proxy sidecar and the verifier with a
read-only root filesystem. Its build passed Python compilation and all 17
Phase 7 runtime unit tests.

The Nav2 fixture had active goals on `/robot_1/navigate_to_pose` and
`/robot_1/navigate_through_poses`. The proxy returned one successful
cancellation acknowledgement per action, and both goals reached status 5
(`STATUS_CANCELED`). The fixture also applied the `blue crate` prompt through
the adapter's atomic parameter service and received three adapter status
messages. All six Job containers exited with code zero.

ROS domains were Nav2 187, adapter 188, and operator 189. Zenoh service and
action routes were explicitly allowlisted in the test ConfigMap.

## Limits

This fixture verifies the packaged proxy process and isolated bridge wiring. It
does not use production Nav2, adapter, model service, operator identities,
permit key, or network policy. Production topology and additional-category
recognition qualification remain HOLD gates.

## Raw evidence

- `verify-operator-service-bridges.log`: machine-readable result with action
  acknowledgements, statuses, prompt apply, and adapter status count.
- `nav2-cancel-proxy.log`: proxy startup and clean shutdown.
- The other four logs contain the bridge and router process output.
- `pod-state.txt`: Job condition, pod node, and exit code for each container.
