"""Expose a normal ROS service that fans cancellation out to Nav2 actions."""
import json
import threading


class Nav2CancelProxy:
    """Bridgeable service facade for local Nav2 action cancellation services."""

    def __init__(self, node, action_names, service_name="/robot_1/phase7/cancel_navigation",
                 timeout_s=3.0):
        from action_msgs.srv import CancelGoal
        from rclpy.callback_groups import ReentrantCallbackGroup
        from std_srvs.srv import Trigger

        if not action_names or any(not isinstance(name, str) or not name.startswith("/")
                                   for name in action_names):
            raise ValueError("explicit absolute Nav2 action list required")
        self.node = node
        self.action_names = tuple(action_names)
        self.timeout_s = float(timeout_s)
        self.callback_group = ReentrantCallbackGroup()
        self.clients = {
            name: node.create_client(CancelGoal, name.rstrip("/") + "/_action/cancel_goal",
                                     callback_group=self.callback_group)
            for name in self.action_names
        }
        self.service = node.create_service(Trigger, service_name, self.cancel_all,
                                           callback_group=self.callback_group)

    def cancel_all(self, _request, response):
        from action_msgs.srv import CancelGoal

        readiness = {name: client.service_is_ready()
                     for name, client in self.clients.items()}
        if not all(readiness.values()):
            response.success = False
            response.message = json.dumps({"ready": readiness})
            return response

        results = {}
        pending = set(self.clients)
        completed = threading.Event()

        def record(name, future):
            try:
                result = future.result()
                results[name] = {"return_code": result.return_code,
                                 "goals_canceling": len(result.goals_canceling)}
            except Exception as exc:  # surface transport failures as a rejected stop
                results[name] = {"error": type(exc).__name__}
            pending.discard(name)
            if not pending:
                completed.set()

        for name, client in self.clients.items():
            future = client.call_async(CancelGoal.Request())
            future.add_done_callback(lambda value, action=name: record(action, value))
        if not completed.wait(self.timeout_s):
            response.success = False
            response.message = json.dumps({"timeout": True, "acks": results})
            return response

        successful = (len(results) == len(self.clients) and
                      all(item.get("return_code") == CancelGoal.Response.ERROR_NONE
                          for item in results.values()))
        response.success = successful
        response.message = json.dumps({"acks": results})
        return response
