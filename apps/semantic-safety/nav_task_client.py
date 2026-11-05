"""Non-actuating ROS NavigateToPose ownership/cancel adapter.

Call only on the node's single-threaded executor. start() is an explicit task
request, not an arm API. A future integrating coordinator must also satisfy
SafetyGate, global action-idle and native actuator prerequisites. The revoke
hook must withdraw command permission synchronously; cancellation is async.
"""
import json
import time
import uuid

from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from std_msgs.msg import String
from unique_identifier_msgs.msg import UUID

from task_session import TaskSession


class NavTaskClient(Node):
    def __init__(self, backend, on_revoke):
        if not callable(on_revoke):
            raise ValueError("a synchronous command-permission revoke hook is required")
        super().__init__("phase5_task_client")
        self.session = TaskSession()
        self.client = ActionClient(self, NavigateToPose, backend)
        self.on_revoke = on_revoke
        self.handles, self.cancel_sent, self.notified = {}, set(), set()
        self.events = []
        self.status = self.create_publisher(String, "/phase5/task_status", 10)
        self.create_timer(.02, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def event(self, kind, **data):
        self.events.append({"event": kind, "steady_ns": time.monotonic_ns(), **data})
        self.events = self.events[-1000:]

    def notify_revoke(self):
        token = self.session.token
        if token and self.session.revoked and token not in self.notified:
            self.notified.add(token)
            self.on_revoke(token, self.session.reason)
            self.event("permission_revoked", token=token, reason=self.session.reason)

    def start(self, goal):
        if not self.client.server_is_ready():
            raise RuntimeError("navigation backend unavailable")
        token = self.session.begin(time.monotonic())
        self.event("goal_requested", token=token)
        try:
            future = self.client.send_goal_async(goal, goal_uuid=UUID(uuid=list(uuid.UUID(token).bytes)))
            future.add_done_callback(lambda response: self.accepted(token, response))
        except Exception:
            # Unknown delivery: do not claim that no backend task exists.
            self.stop("goal_request_error")
            raise
        return token

    def stop(self, reason):
        self.session.revoke(reason, time.monotonic())
        self.notify_revoke()  # withdraw authority BEFORE any ROS cancel request
        self.cancel_if_needed()

    def accepted(self, token, future):
        if token != self.session.token or self.session.state == "idle":
            return
        try:
            handle = future.result()
            disposition = self.session.accepted(token, handle.accepted, time.monotonic())
            self.event("goal_response", token=token, disposition=disposition)
            self.notify_revoke()
            if disposition in ("run", "cancel"):
                self.handles[token] = handle
                handle.get_result_async().add_done_callback(lambda result: self.finished(token, result))
                self.cancel_if_needed()
        except Exception as error:
            self.event("goal_response_error", detail=str(error))
            self.stop("goal_response_error")

    def cancel_if_needed(self):
        token = self.session.token
        if self.session.state != "stopping" or token not in self.handles or token in self.cancel_sent:
            return
        self.cancel_sent.add(token)
        self.event("cancel_requested", token=token)
        try:
            self.handles[token].cancel_goal_async().add_done_callback(lambda result: self.canceled(token, result))
        except Exception as error:
            self.event("cancel_error", token=token, detail=str(error))

    def canceled(self, token, future):
        try:
            reply = future.result()
            ids = [str(uuid.UUID(bytes=bytes(g.goal_id.uuid))) for g in reply.goals_canceling]
            accepted = reply.return_code == 0 and token in ids
            self.session.acknowledge_cancel(token, accepted)
            self.event("cancel_response", token=token, accepted=accepted)
        except Exception as error:
            self.event("cancel_error", token=token, detail=str(error))

    def finished(self, token, future):
        if token != self.session.token or self.session.state == "idle":
            return
        try:
            response = future.result()
            terminal = self.session.finish(token, response.status, time.monotonic())
            self.notify_revoke()
            if terminal:
                self.handles.pop(token, None)
                self.event("terminal_result", token=token, status=response.status, outcome=self.session.outcome)
        except Exception as error:
            self.event("result_error", token=token, detail=str(error))
            self.stop("result_error")

    def tick(self):
        self.session.tick(time.monotonic())
        if self.session.state == "running" and not self.client.server_is_ready():
            self.session.revoke("backend_disappeared", time.monotonic())
        self.notify_revoke()
        self.cancel_if_needed()
        self.status.publish(String(data=json.dumps({"schema": "phase5-owned-task/v1",
            "state": self.session.state, "token": self.session.token, "reason": self.session.reason,
            "revoked": self.session.revoked, "cancel_ack": self.session.cancel_ack,
            "outcome": self.session.outcome,
            "timeout": self.session.timeout, "wall_ns": time.time_ns(),
            "scope": "owned_action_only_not_global_idle_or_arm_permission"})))

