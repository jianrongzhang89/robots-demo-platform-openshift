"""Run the allowlisted Nav2 cancellation proxy in the local ROS domain."""
import os
from pathlib import Path
import tempfile


def main():
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node

    from phase7_nav2_cancel_proxy import Nav2CancelProxy

    actions = tuple(filter(None, os.getenv(
        "PHASE7_NAV_ACTIONS",
        "/robot_1/navigate_to_pose,/robot_1/navigate_through_poses").split(",")))
    service = os.getenv("PHASE7_NAV_CANCEL_PROXY",
                         "/robot_1/phase7/cancel_navigation")
    allowed_actions = {
        "/navigate_to_pose", "/navigate_through_poses",
        "/robot_1/navigate_to_pose", "/robot_1/navigate_through_poses",
    }
    if not actions or any(name not in allowed_actions for name in actions):
        raise RuntimeError("explicit allowlisted Nav2 actions required")

    log_dir = Path(os.environ.setdefault(
        "ROS_LOG_DIR", str(Path(tempfile.gettempdir()) / "phase7-nav2-proxy-logs")))
    log_dir.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    node = Node("phase7_nav2_cancel_proxy")
    proxy = Nav2CancelProxy(node, actions, service)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown(timeout_sec=2.0)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
