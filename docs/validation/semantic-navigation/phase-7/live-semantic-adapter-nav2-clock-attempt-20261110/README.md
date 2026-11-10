# Live adapter/Nav2 clock bridge attempt — November 10, 2026

**Result: adapter inference active; Nav2 remained gated on simulation clock.** Runtime candidate #54 routed `/odom`, `/scan`, and `/tf` from Zenoh into ROS domain 182; the bridge logs confirm all three subscriptions. The pinned red-mat adapter path also remained active.

Nav2's entrypoint did not advance because it received no `/clock` messages in domain 182. The ROS graph showed the clock publisher created by the Zenoh bridge, and the source clock delivered a sample in domain 181, but an echo in domain 182 timed out. The Nav2 entrypoint was still waiting for `/clock`; the action server never became ready. No goal or cancellation was attempted. The watchdog remained disarmed.

This attempt isolates the remaining graph issue to clock delivery across the ROS/Zenoh boundary. The next iteration will test a direct Gazebo-to-ROS clock bridge in the isolated pod. This does not alter the independent actual Nav2 cancellation pass. Phase 6 simulator, Nav2, and SAM3 workloads remained Running on their original nodes; see `phase6-unchanged.txt`.
