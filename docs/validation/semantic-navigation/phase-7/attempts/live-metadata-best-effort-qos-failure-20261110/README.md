# Phase 7 live retry: sensor metadata QoS failure

This run failed before operator API readiness and before Nav2 goal submission. The semantic adapter did not become ready because it received compressed RGB/depth but not CameraInfo or the required capture trace. Bridge logs show the ROS publishers, Zenoh routes, and remote publisher announcements were present, so this was not a missing allowlist route. The adapter requested RELIABLE QoS for all inputs; Gazebo camera metadata and traces are offered with sensor-style BEST_EFFORT QoS. ROS 2 QoS compatibility prevents a RELIABLE subscriber from matching a BEST_EFFORT publisher. The source probe used sensor-data QoS and could receive these messages, which masked the mismatch.

The operator runtime correctly kept its endpoint unavailable until a fresh inference result and native/Nav2 services were ready. No operator request or navigation goal was sent. The native watchdog remained disarmed with zero applied commands. This attempt is retained as diagnosis, not a pass.

The corrective change makes CameraInfo and capture/compression trace subscriptions BEST_EFFORT; a ROS regression test checks the requested QoS. The compressed RGB/depth subscriptions remain RELIABLE because the local compressor publishes them RELIABLE.
