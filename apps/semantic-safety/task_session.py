"""Owned-action lifecycle only; NOT evidence of global task idleness or robot safety.

The integrating coordinator must qualify sensors, stationary/neutral state,
all other action servers, and the actuator handshake before admitting a goal.
This component never arms a SafetyGate or grants an actuator lease by itself.
"""
import uuid


class TaskSession:
    def __init__(self):
        self.token = None
        self.state = "idle"
        self.reason = "startup"
        self.revoked = True
        self.cancel_ack = None
        self.deadline = None
        self.timeout = None
        self.terminal_status = None
        self.outcome = None

    def begin(self, now):
        if self.state != "idle":
            raise RuntimeError("previous goal is unresolved")
        self.token = str(uuid.uuid4())
        self.state, self.reason = "requesting", "goal_request"
        self.revoked, self.cancel_ack = False, None
        self.timeout = self.terminal_status = None
        self.outcome = None
        self.deadline = now + 5.0
        return self.token

    def revoke(self, reason, now):
        if self.state == "idle":
            return False
        first = not self.revoked
        if first:
            self.reason, self.deadline = reason, now + 2.0
        self.revoked, self.state = True, "stopping"
        return first

    def accepted(self, token, accepted, now):
        if token != self.token or self.state == "idle":
            return "ignore"
        self.tick(now)  # a late response cannot hide a missed deadline
        if not accepted:
            if not self.revoked:
                self.reason = "goal_rejected"
            self.revoked, self.state, self.deadline = True, "idle", None
            self.outcome = "rejected"
            return "rejected"
        if self.revoked:
            return "cancel"
        self.state, self.reason, self.deadline = "running", "goal_active", None
        return "run"

    def acknowledge_cancel(self, token, accepted):
        if token == self.token and self.state == "stopping":
            self.cancel_ack = bool(accepted)
            # An accepted cancellation is NOT a terminal action result.

    def finish(self, token, status, now):
        if token != self.token or self.state == "idle":
            return False
        if status not in (4, 5, 6):  # ROS succeeded, canceled, aborted
            self.revoke("invalid_terminal_status", now)
            return False
        self.outcome = "stopped" if self.revoked else {4: "succeeded", 5: "canceled", 6: "aborted"}[status]
        self.revoke({4: "goal_succeeded", 5: "goal_canceled", 6: "goal_aborted"}[status], now)
        self.terminal_status, self.state, self.deadline = status, "idle", None
        return True

    def tick(self, now):
        if self.deadline is not None and now >= self.deadline:
            if self.state == "requesting":
                self.revoke("goal_accept_timeout", now)
            elif self.state == "stopping":
                self.timeout = "terminal_result_timeout"
                self.deadline = None  # stays unresolved; no automatic reset

    def may_command(self, token):
        return token == self.token and self.state == "running" and not self.revoked

