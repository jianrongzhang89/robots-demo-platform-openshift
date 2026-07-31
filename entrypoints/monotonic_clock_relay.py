#!/usr/bin/env python3
"""
Monotonic sim-clock relay — two-process design to avoid rclpy+zenoh conflicts.

When invoked with --zenoh-sub: subscribe to Zenoh clock, filter backwards
  timestamps, write "sec nanosec" lines to stdout.
When invoked with --ros-pub: read "sec nanosec" lines from stdin, publish
  to the ROS2 /clock topic.

The entrypoint pipes them:
  python3 relay.py --zenoh-sub robot_1 | python3 relay.py --ros-pub

Keeping the two halves in separate processes avoids the segfault that occurs
when rclpy (fastrtps DDS) and zenoh Python share the same process.
"""
import sys
import struct
import time


def zenoh_subscriber(robot_name: str) -> None:
    """Zenoh half: subscribe to robot_N/clock, filter, write to stdout."""
    import zenoh

    last_ns: int = 0

    def on_clock(sample: zenoh.Sample) -> None:
        nonlocal last_ns
        try:
            raw = bytes(sample.payload.to_bytes())
            if len(raw) < 12:
                return
            sec  = struct.unpack_from("<i", raw, 4)[0]
            nsec = struct.unpack_from("<I", raw, 8)[0]
            ns = sec * 1_000_000_000 + nsec
            if ns < last_ns:
                return          # drop backwards jump
            last_ns = ns
            sys.stdout.write(f"{sec} {nsec}\n")
            sys.stdout.flush()
        except Exception:
            pass

    # Retry until the router is up
    z = None
    for attempt in range(30):
        try:
            conf = zenoh.Config()
            conf.insert_json5("connect/endpoints", '["tcp/zenoh-router:7447"]')
            conf.insert_json5("mode", '"client"')
            conf.insert_json5("scouting/multicast/enabled", "false")
            z = zenoh.open(conf)
            break
        except Exception as exc:
            sys.stderr.write(
                f"[monotonic_clock_relay] Zenoh connect attempt {attempt+1}/30 failed: {exc}\n"
            )
            time.sleep(2)

    if z is None:
        sys.stderr.write("[monotonic_clock_relay] Could not connect to Zenoh router\n")
        return

    clock_key = f"{robot_name}/clock"
    sys.stderr.write(
        f"[monotonic_clock_relay] Subscribing to {clock_key} (monotonic filter)\n"
    )
    sub = z.declare_subscriber(clock_key, on_clock)

    while True:
        time.sleep(1)


def ros_publisher() -> None:
    """ROS2 half: read filtered 'sec nanosec' lines from stdin, publish /clock."""
    import rclpy
    import threading
    from rclpy.node import Node
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
    from rosgraph_msgs.msg import Clock
    from builtin_interfaces.msg import Time

    rclpy.init(args=["monotonic_clock_relay"])
    node = Node("monotonic_clock_relay")
    qos = QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
    )
    pub = node.create_publisher(Clock, "/clock", qos)

    executor = SingleThreadedExecutor()
    executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()

    node.get_logger().info("[monotonic_clock_relay] Publishing filtered /clock")

    for line in sys.stdin:
        try:
            sec, nanosec = (int(x) for x in line.split())
            msg = Clock()
            msg.clock = Time(sec=sec, nanosec=nanosec)
            pub.publish(msg)
        except Exception:
            pass


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "--zenoh-sub":
        robot_name = sys.argv[2] if len(sys.argv) > 2 else "robot_1"
        zenoh_subscriber(robot_name)
    elif mode == "--ros-pub":
        ros_publisher()
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
