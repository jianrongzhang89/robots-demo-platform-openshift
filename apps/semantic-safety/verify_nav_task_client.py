"""Real ROS action protocol, controlled fake navigation backend; NO motion."""
import json
import os
import time
import uuid

import rclpy
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.task import Future

from nav_task_client import NavTaskClient


class Backend(Node):
    def __init__(self):
        super().__init__("phase5_fake_navigation_backend")
        self.reject_goal = self.reject_cancel = False
        self.goals, self.results = {}, {}
        self.server = ActionServer(self, NavigateToPose, "/phase5_fixture/navigate_to_pose",
            execute_callback=self.execute, goal_callback=self.goal,
            handle_accepted_callback=self.accepted, cancel_callback=self.cancel)

    def goal(self, request):
        return GoalResponse.REJECT if self.reject_goal else GoalResponse.ACCEPT

    def accepted(self, handle):
        token = str(uuid.UUID(bytes=bytes(handle.goal_id.uuid)))
        self.goals[token], self.results[token] = handle, Future()
        handle.execute()

    async def execute(self, handle):
        token = str(uuid.UUID(bytes=bytes(handle.goal_id.uuid)))
        return await self.results[token]

    def cancel(self, handle):
        return CancelResponse.REJECT if self.reject_cancel else CancelResponse.ACCEPT

    def finish(self, token, status):
        handle = self.goals[token]
        {4: handle.succeed, 5: handle.canceled, 6: handle.abort}[status]()
        self.results[token].set_result(NavigateToPose.Result())


def main():
    if os.getenv("ROS_DOMAIN_ID") != "85" or "phase5" not in os.getenv("CYCLONEDDS_URI", ""):
        raise RuntimeError("isolated fixture only")
    rclpy.init()
    revoked, checks = [], []
    backend = Backend()
    client = NavTaskClient("/phase5_fixture/navigate_to_pose", lambda token, reason: revoked.append((token,reason)))
    executor = SingleThreadedExecutor(); executor.add_node(backend); executor.add_node(client)

    def until(predicate, timeout=5):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            executor.spin_once(timeout_sec=.01)
            if predicate(): return
        raise AssertionError("action fixture timed out: "+str(vars(client.session)))

    def goal():
        result = NavigateToPose.Goal()
        result.pose.header.frame_id = "map"
        result.pose.pose.orientation.w = 1.
        return result

    def start():
        token = client.start(goal())
        until(lambda: client.session.state == "running")
        assert client.session.may_command(token)
        return token

    def blocked():
        try: client.start(goal())
        except RuntimeError: return
        raise AssertionError("unresolved goal admitted a successor")

    try:
        until(client.client.server_is_ready)
        token = start(); client.stop("camera_stale")
        assert not client.session.may_command(token) and revoked[-1] == (token,"camera_stale")
        until(lambda: client.session.cancel_ack is True)
        blocked()
        until(lambda: client.session.timeout is not None, 4)
        blocked(); assert client.session.state == "stopping"
        backend.finish(token,5); until(lambda: client.session.state == "idle")
        checks.append({"case": "revoke_before_cancel_ack_and_wait_for_terminal", "passed": True})

        token = client.start(goal()); client.stop("cancel_before_accept")
        until(lambda: client.session.cancel_ack is True)
        assert not client.session.may_command(token)
        backend.finish(token,5); until(lambda: client.session.state == "idle")
        checks.append({"case": "late_acceptance_canceled_without_permission", "passed": True})

        token = start(); backend.finish(token,4); until(lambda: client.session.state == "idle")
        assert not client.session.may_command(token) and revoked[-1] == (token,"goal_succeeded")
        checks.append({"case": "success_revokes_and_requires_new_request", "passed": True})

        backend.reject_cancel = True
        token = start(); client.stop("tf_stale"); until(lambda: client.session.cancel_ack is False)
        blocked(); assert not client.session.may_command(token)
        backend.finish(token,6); until(lambda: client.session.state == "idle")
        backend.reject_cancel = False
        checks.append({"case": "rejected_cancel_stays_inhibited_until_terminal", "passed": True})

        backend.reject_cancel = True
        token = start(); client.stop("backend_timeout"); until(lambda: client.session.cancel_ack is False)
        backend.finish(token,4); until(lambda: client.session.state == "idle")
        assert client.session.reason == "backend_timeout" and client.session.outcome == "stopped"
        assert not client.session.may_command(token)
        backend.reject_cancel = False
        checks.append({"case": "late_backend_success_not_reported_as_task_success", "passed": True})

        old = token
        token = start()
        stale = Future(); stale.set_exception(RuntimeError("late prior-session callback"))
        client.finished(old, stale); client.accepted(old, stale)
        assert client.session.may_command(token)
        backend.finish(token,4); until(lambda: client.session.state == "idle")
        checks.append({"case": "prior_session_callback_errors_do_not_change_current_task", "passed": True})

        backend.reject_goal = True
        token = client.start(goal()); until(lambda: client.session.state == "idle")
        assert not client.session.may_command(token) and client.session.reason == "goal_rejected"
        checks.append({"case": "backend_rejection_never_allows_command", "passed": True})

        graph = dict(client.get_topic_names_and_types())
        assert not any("cmd_vel" in name or "/drive/" in name or "lease" in name for name in graph)
        checks.append({"case": "no_actuator_or_command_topics", "passed": True})
        print(json.dumps({"event": "phase5_owned_action_fixture", "passed": True,
                          "checks": checks, "events": client.events, "topics": graph}), flush=True)
    finally:
        executor.shutdown(); backend.server.destroy(); client.client.destroy()
        backend.destroy_node(); client.destroy_node(); rclpy.shutdown()


if __name__ == "__main__":
    main()
