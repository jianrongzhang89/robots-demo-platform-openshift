"""Verify cancellation of an accepted goal on a live, isolated Nav2 stack."""
import argparse
import gc
import json
import threading
import time
from pathlib import Path


def wait_for(predicate, description, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise TimeoutError(f"timed out waiting for {description}")


def live_sam3_status_qualified(row, *, prompt_transitions_enabled=False):
    """Return whether adapter status proves fresh output from the pinned model.

    The adapter reports the active prompt and deployment identity at status
    level. ``last_result.identity`` identifies the frame/request generation;
    it intentionally does not repeat the prompt.
    """
    if not isinstance(row, dict):
        return False
    identity = row.get("deployment_identity")
    last_result = row.get("last_result")
    request_identity = (last_result.get("identity")
                        if isinstance(last_result, dict) else None)
    try:
        result_age_ms = float(row.get("last_valid_result_age_ms"))
        valid_counts = (int(row.get("emitted_results", 0)) >= 1 and
                        int(row.get("paired_triplets", 0)) >= 1 and
                        int(row.get("policy_generation", 0)) == 1)
    except (TypeError, ValueError):
        return False
    return (
        row.get("ready") is True and row.get("backend") == "http" and
        row.get("prompt") == "red mat" and
        row.get("approved_prompts") == ["red mat"] and
        row.get("prompt_transition_enabled") is prompt_transitions_enabled and
        result_age_ms <= 500.0 and valid_counts and
        isinstance(identity, dict) and
        identity.get("container_digest") ==
        "sha256:f9bcc273a164f741426079ccf4c9d2269c9ec5e9530845029e593bf466a3aa2e" and
        identity.get("weights_sha256") ==
        "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e" and
        isinstance(last_result, dict) and
        isinstance(request_identity, dict) and
        request_identity.get("robot") == "robot_1" and
        request_identity.get("stream") == "camera/color" and
        request_identity.get("generation") == 1 and
        isinstance(request_identity.get("request_id"), str) and
        bool(request_identity.get("request_id")) and
        isinstance(request_identity.get("sequence"), int) and
        request_identity["sequence"] >= 0
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-live-sam3-adapter", action="store_true",
                        help="require a successful result from the live HTTP SAM3 adapter")
    parser.add_argument("--require-enabled-prompt-transitions", action="store_true",
                        help="require the signed-prompt transition verifier to be enabled")
    args = parser.parse_args()

    import rclpy
    from action_msgs.msg import GoalStatus
    from gz.msgs10.stringmsg_pb2 import StringMsg
    from gz.transport13 import Node as GzNode
    from geometry_msgs.msg import PoseStamped
    from nav2_msgs.action import NavigateToPose
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from std_srvs.srv import Trigger

    rclpy.init()
    node = Node("phase7_live_nav2_cancel_verifier")
    action = ActionClient(node, NavigateToPose, "/navigate_to_pose")
    cancel_proxy = node.create_client(Trigger, "/phase7/cancel_navigation")
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    native_lock = threading.Lock()
    native_rows = []
    adapter_lock = threading.Lock()
    adapter_rows = []
    gz_node = GzNode()

    def receive_native(message):
        try:
            row = json.loads(message.data)
        except (TypeError, ValueError):
            return
        if isinstance(row, dict):
            with native_lock:
                native_rows.append(row)
                first = len(native_rows) == 1
            if first:
                print(json.dumps({"native_status_sample": row}, sort_keys=True),
                      flush=True)

    def receive_adapter_status(message):
        try:
            row = json.loads(message.data)
        except (TypeError, ValueError):
            return
        if isinstance(row, dict):
            with adapter_lock:
                adapter_rows.append(row)
                del adapter_rows[:-200]

    try:
        if not gz_node.subscribe(StringMsg, "/phase5/drive/status", receive_native):
            raise RuntimeError("could not subscribe to private native drive status")
        if args.require_live_sam3_adapter:
            node.create_subscription(
                String, "/robot_1/semantic/status", receive_adapter_status, 10)
        # The full simulator topology has more lifecycle and bridge startup
        # stages than the isolated action-only fixture. Keep polling the real
        # action client while those components settle instead of treating a
        # slow action discovery as a failed safety assertion.
        wait_for(lambda: action.server_is_ready(),
                 "live Nav2 navigate_to_pose action", timeout=150.0)
        wait_for(lambda: cancel_proxy.service_is_ready(), "local cancellation proxy")

        def status_snapshot():
            with native_lock:
                return list(native_rows)

        def native_speed(row):
            physical = row.get("physical")
            if not isinstance(physical, dict):
                return 1e9
            return float(row.get("speed_mps", physical.get("speed", 1e9)))

        def disarmed_zero(rows):
            return any(row.get("armed") is False and
                       abs(native_speed(row)) < 0.002 and
                       abs(float(row.get("applied_vx", 1e9))) < 1e-6 and
                       abs(float(row.get("applied_wz", 1e9))) < 1e-6
                       for row in rows)

        wait_for(lambda: disarmed_zero(status_snapshot()),
                 "fresh disarmed native status with zero applied command")

        adapter_result = None
        if args.require_live_sam3_adapter:
            def live_model_result():
                with adapter_lock:
                    rows = list(adapter_rows)
                for row in reversed(rows):
                    if live_sam3_status_qualified(
                            row, prompt_transitions_enabled=
                            args.require_enabled_prompt_transitions):
                        return row
                return None

            adapter_result = wait_for(
                live_model_result,
                "a fresh red-mat inference from the pinned live SAM3 service",
                timeout=120.0)
            print(json.dumps({
                "live_sam3_adapter_sample": {
                    "backend": adapter_result["backend"],
                    "prompt": adapter_result["prompt"],
                    "approved_prompts": adapter_result["approved_prompts"],
                    "policy_generation": adapter_result["policy_generation"],
                    "emitted_results": adapter_result["emitted_results"],
                    "paired_triplets": adapter_result["paired_triplets"],
                    "prompt_transition_enabled": adapter_result[
                        "prompt_transition_enabled"],
                    "deployment_identity": adapter_result["deployment_identity"],
                    "last_result": adapter_result["last_result"],
                }
            }, sort_keys=True), flush=True)
        # Discard pre-physics and spawn-settling samples; qualify the run from
        # the first fresh stationary native status onward.
        with native_lock:
            native_rows.clear()

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = "map"
        goal.pose.pose.position.x = 8.0
        goal.pose.pose.position.y = -8.0
        goal.pose.pose.orientation.w = 1.0
        # The action server endpoint appears before Nav2's lifecycle manager has
        # activated bt_navigator. Retry only rejected submissions so the test
        # waits for the real active stack instead of racing startup.
        goal_deadline = time.monotonic() + 60.0
        attempts = 0
        while True:
            attempts += 1
            send_future = action.send_goal_async(goal)
            goal_handle = wait_for(
                lambda: send_future.result() if send_future.done() else None,
                "Nav2 goal acceptance", timeout=max(0.1, goal_deadline - time.monotonic()))
            if goal_handle.accepted:
                break
            if time.monotonic() >= goal_deadline:
                raise RuntimeError(
                    f"live Nav2 kept rejecting the cancellation test goal ({attempts} attempts)")
            time.sleep(0.5)
        print(json.dumps({"goal_acceptance_attempts": attempts}), flush=True)
        print("live Nav2 accepted cancellation test goal", flush=True)
        result_future = goal_handle.get_result_async()
        cancel_future = cancel_proxy.call_async(Trigger.Request())
        cancel_response = wait_for(
            lambda: cancel_future.result() if cancel_future.done() else None,
            "cancellation proxy acknowledgement")
        if not cancel_response.success:
            raise RuntimeError(f"live Nav2 cancellation proxy failed: {cancel_response.message}")
        ack = json.loads(cancel_response.message)
        active_ack = ack.get("acks", {}).get("/navigate_to_pose", {})
        if active_ack.get("return_code") != 0 or active_ack.get("goals_canceling") < 1:
            raise RuntimeError(f"proxy did not acknowledge the active Nav2 goal: {ack}")
        action_result = wait_for(
            lambda: result_future.result() if result_future.done() else None,
            "canceled live Nav2 goal result")
        if action_result.status != GoalStatus.STATUS_CANCELED:
            raise RuntimeError(f"live Nav2 goal ended with status {action_result.status}")

        time.sleep(0.5)
        rows = status_snapshot()
        if len(rows) < 2 or not all(disarmed_zero([row]) for row in rows):
            raise RuntimeError("native drive was not continuously disarmed at zero during cancellation")
        result = {
            "event": "phase7_live_nav2_cancel",
            "passed": True,
            "action": "/navigate_to_pose",
            "goal_accepted": True,
            "cancel_proxy": "/phase7/cancel_navigation",
            "cancel_acknowledgements": ack,
            "goal_status": action_result.status,
            "goal_status_name": "STATUS_CANCELED",
            "native_status_samples": len(rows),
            "native_armed": False,
            "max_native_speed_mps": max(abs(native_speed(row)) for row in rows),
            "max_applied_vx": max(abs(float(row.get("applied_vx", 0.0)))
                                   for row in rows),
            "max_applied_wz": max(abs(float(row.get("applied_wz", 0.0)))
                                   for row in rows),
        }
        if adapter_result is not None:
            result["live_sam3_adapter"] = {
                "passed": True,
                "backend": adapter_result["backend"],
                "prompt": adapter_result["prompt"],
                "approved_prompts": adapter_result["approved_prompts"],
                "policy_generation": adapter_result["policy_generation"],
                "emitted_results": adapter_result["emitted_results"],
                "paired_triplets": adapter_result["paired_triplets"],
                "prompt_transition_enabled": adapter_result[
                    "prompt_transition_enabled"],
                "deployment_identity": adapter_result["deployment_identity"],
                "last_result": adapter_result["last_result"],
            }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, sort_keys=True), flush=True)
    finally:
        # Gazebo Transport owns native subscriber threads. Stop the callback
        # before tearing down ROS so pybind's Node destructor can join them.
        if gz_node is not None:
            gz_node.unsubscribe("/phase5/drive/status")
        executor.shutdown(timeout_sec=2.0)
        spin_thread.join(timeout=2.0)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        del gz_node
        gc.collect()


if __name__ == "__main__":
    main()
