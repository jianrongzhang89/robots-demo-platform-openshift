"""Exercise Phase 7's narrowly allowed ROS service/topic routes across DDS domains."""
import argparse
import json
import os
import time
from pathlib import Path


NAV2_ACTIONS = (
    "/robot_1/navigate_to_pose",
    "/robot_1/navigate_through_poses",
)
NAV2_CANCEL_PROXY = "/robot_1/phase7/cancel_navigation"
ADAPTER_SERVICE = "/robot_1/sam3_inference/set_parameters_atomically"
ADAPTER_STATUS = "/robot_1/semantic/status"


def until(predicate, timeout_s=30, description="ROS bridge endpoint"):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise TimeoutError(f"timed out waiting for {description}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-dir", type=Path, required=True)
    args = parser.parse_args()
    args.shared_dir.mkdir(parents=True, exist_ok=True)

    import rclpy
    from rclpy.context import Context
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.action import ActionServer
    from rclpy.action import ActionClient
    from rclpy.action.server import CancelResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from nav2_msgs.action import NavigateThroughPoses, NavigateToPose
    from geometry_msgs.msg import PoseStamped
    from action_msgs.msg import GoalStatus
    from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue, SetParametersResult
    from rcl_interfaces.srv import SetParametersAtomically
    from std_msgs.msg import String
    from std_srvs.srv import Trigger

    contexts = {}
    nodes = []
    executors = []
    threads = []
    action_servers = []
    adapter_calls = []
    status_rows = []
    cancelled_action_goals = []
    nav2_action_callbacks = ReentrantCallbackGroup()
    try:
        def node_for(domain, name):
            os.environ["ROS_DOMAIN_ID"] = str(domain)
            context = Context()
            rclpy.init(context=context)
            contexts[domain] = context
            node = Node(name, context=context)
            nodes.append(node)
            executor = MultiThreadedExecutor(num_threads=4, context=context)
            executor.add_node(node)
            executors.append(executor)
            thread = __import__("threading").Thread(
                target=executor.spin, daemon=True, name=f"ros-domain-{domain}")
            thread.start()
            threads.append(thread)
            return node

        nav2 = node_for(187, "phase7_bridge_nav2_fixture")
        adapter = node_for(188, "phase7_bridge_adapter_fixture")
        operator = node_for(189, "phase7_bridge_operator_client")

        for action_name, action_type in (
                ("/robot_1/navigate_to_pose", NavigateToPose),
                ("/robot_1/navigate_through_poses", NavigateThroughPoses)):
            def execute(goal_handle, action_type=action_type, action_name=action_name):
                while not goal_handle.is_cancel_requested:
                    time.sleep(.02)
                goal_handle.canceled()
                return action_type.Result()
            def cancel_goal(_goal_handle, name=action_name):
                cancelled_action_goals.append(name)
                return CancelResponse.ACCEPT
            action_servers.append(ActionServer(
                nav2, action_type, action_name, execute_callback=execute,
                cancel_callback=cancel_goal,
                callback_group=nav2_action_callbacks))
        print(json.dumps({"nav2_fixture_services": nav2.get_service_names_and_types()},
                         default=str), flush=True)

        def apply_prompt(request, response):
            values = {parameter.name: parameter.value for parameter in request.parameters}
            valid = (set(values) == {"prompt", "phase7_transition_permit"}
                     and values["prompt"].type == ParameterType.PARAMETER_STRING
                     and values["prompt"].string_value == "blue crate"
                     and values["phase7_transition_permit"].type == ParameterType.PARAMETER_STRING
                     and values["phase7_transition_permit"].string_value == "bridge-test-permit")
            adapter_calls.append({"valid_schema": valid,
                                  "prompt": values.get("prompt", ParameterValue()).string_value})
            response.result = SetParametersResult(successful=valid)
            return response

        adapter.create_service(SetParametersAtomically, ADAPTER_SERVICE, apply_prompt)
        status_pub = adapter.create_publisher(String, ADAPTER_STATUS, 10)
        status_timer = adapter.create_timer(.05, lambda: publish_status(status_pub, String))

        cancel_client = operator.create_client(Trigger, NAV2_CANCEL_PROXY)
        action_clients = {
            name: ActionClient(nav2, action_type, name,
                               callback_group=nav2_action_callbacks)
            for name, action_type in zip(NAV2_ACTIONS,
                                         (NavigateToPose, NavigateThroughPoses))
        }
        parameter_client = operator.create_client(SetParametersAtomically, ADAPTER_SERVICE)
        operator.create_subscription(String, ADAPTER_STATUS,
                                     lambda message: receive_status(message, status_rows), 10)

        until(parameter_client.service_is_ready,
              description="adapter atomic-parameter service route")
        print("adapter atomic-parameter service route ready", flush=True)
        until(cancel_client.service_is_ready,
              description=f"Nav2 cancellation proxy route {NAV2_CANCEL_PROXY}")
        print(f"Nav2 cancellation proxy route ready: {NAV2_CANCEL_PROXY}", flush=True)
        until(lambda: status_rows and status_rows[-1].get("prompt") == "red mat",
              description="adapter status topic route")

        until(lambda: all(client.server_is_ready()
                          for client in action_clients.values()),
              description="both Nav2 action servers")
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.pose.orientation.w = 1.0
        goals = {
            "/robot_1/navigate_to_pose": NavigateToPose.Goal(),
            "/robot_1/navigate_through_poses": NavigateThroughPoses.Goal(),
        }
        goals["/robot_1/navigate_to_pose"].pose = pose
        goals["/robot_1/navigate_through_poses"].poses = [pose]
        goal_handles = {}
        for name, client in action_clients.items():
            goal_handles[name] = call_and_wait(client.send_goal_async(goals[name]))
            if not goal_handles[name].accepted:
                raise AssertionError(f"Nav2 fixture rejected active test goal {name}")
        goal_results = {name: handle.get_result_async()
                        for name, handle in goal_handles.items()}

        cancel_response = call_and_wait(cancel_client, Trigger.Request())
        if not cancel_response.success:
            raise AssertionError(f"remote cancellation proxy rejected: {cancel_response.message}")
        completed_results = {
            name: call_and_wait(future)
            for name, future in goal_results.items()
        }
        goal_statuses = {name: result.status
                         for name, result in completed_results.items()}
        if (set(cancelled_action_goals) != set(NAV2_ACTIONS) or
                any(result.status != GoalStatus.STATUS_CANCELED
                    for result in completed_results.values())):
            raise AssertionError(
                f"proxy ACK did not cancel both active Nav2 fixture goals: "
                f"callbacks={cancelled_action_goals}; "
                f"statuses={goal_statuses}")

        prompt = Parameter(name="prompt", value=ParameterValue(
            type=ParameterType.PARAMETER_STRING, string_value="blue crate"))
        permit = Parameter(name="phase7_transition_permit", value=ParameterValue(
            type=ParameterType.PARAMETER_STRING, string_value="bridge-test-permit"))
        request = SetParametersAtomically.Request()
        request.parameters = [prompt, permit]
        response = call_and_wait(parameter_client, request)
        if not response.result.successful:
            raise AssertionError("remote adapter atomic-parameter service rejected request")
        until(lambda: adapter_calls
              and adapter_calls[-1]["valid_schema"],
              description="server-side service callback evidence")

        result = {
            "event": "phase7_ros_service_bridge_integration",
            "passed": True,
            "ros_domains": {"nav2": 187, "adapter": 188, "operator": 189},
            "nav2_cancel_proxy": NAV2_CANCEL_PROXY,
            "nav2_cancel_acknowledgements": json.loads(cancel_response.message),
            "cancelled_active_action_goals": cancelled_action_goals,
            "goal_statuses": goal_statuses,
            "adapter_parameter_service": ADAPTER_SERVICE,
            "adapter_atomic_apply": adapter_calls[-1],
            "adapter_status_topic": ADAPTER_STATUS,
            "status_messages_received": len(status_rows),
            "transport": "Zenoh ROS 2 DDS bridge with service server/client allowlists",
        }
        result_path = args.shared_dir / "phase7-ros-service-bridge-result.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, sort_keys=True), flush=True)
    finally:
        for executor in executors:
            executor.shutdown(timeout_sec=2.0)
        for action_server in action_servers:
            action_server.destroy()
        for node in nodes:
            node.destroy_node()
        for context in contexts.values():
            if rclpy.ok(context=context):
                rclpy.shutdown(context=context)


def call_and_wait(client_or_future, request=None, timeout_s=15):
    future = (client_or_future.call_async(request) if request is not None
              else client_or_future)
    return until(lambda: future.result() if future.done() else None,
                 timeout_s=timeout_s, description="ROS service response")


def publish_status(publisher, message_type):
    message = message_type()
    message.data = json.dumps({"prompt": "red mat", "policy_generation": 1,
                               "stream_epoch": "phase7-bridge-fixture",
                               "prompt_transition_ready": True, "ready": True})
    publisher.publish(message)


def receive_status(message, rows):
    try:
        value = json.loads(message.data)
        if isinstance(value, dict):
            rows.append(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass


if __name__ == "__main__":
    main()
