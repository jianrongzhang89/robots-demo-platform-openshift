from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class RmfBridgeError(RuntimeError):
    pass


class RmfBridge:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={"Content-Type": "application/json"} if body else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RmfBridgeError(str(exc)) from exc

    def dispatch(self, mission: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        response = self._request(
            "POST",
            "/tasks/dispatch_task",
            {
                "type": "dispatch_task_request",
                "request": {
                    # Omit timestamps so RMF assigns them from its active ROS
                    # simulation clock. Wall-clock epoch milliseconds make a
                    # simulation task wait indefinitely in the queue.
                    "category": "patrol",
                    "description": {"category": "patrol", "places": mission["places"], "rounds": mission["rounds"]},
                    "labels": [
                        f"mission_id={mission['mission_id']}",
                        f"episode_id={mission['episode_id']}",
                        f"site_id={mission['site_id']}",
                    ],
                    "requester": "fleet-copilot",
                },
            },
        )
        if not response.get("success"):
            raise RmfBridgeError(response.get("error", "RMF rejected dispatch"))
        task_id = ((response.get("state") or {}).get("booking") or {}).get("id")
        if not task_id:
            raise RmfBridgeError("RMF response did not contain state.booking.id")
        return task_id, response

    def state(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/tasks/{task_id}/state")

    def find_by_mission(self, mission_id: str) -> list[dict[str, Any]]:
        return self._request("GET", "/tasks?label=mission_id=" + mission_id)

    def cancel(self, task_id: str, mission_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/tasks/cancel_task",
            {
                "type": "cancel_task_request",
                "task_id": task_id,
                "labels": [f"mission_id={mission_id}", "requester=fleet-copilot"],
            },
        )

    @staticmethod
    def terminal_success(state: dict[str, Any]) -> tuple[bool, str]:
        phases = state.get("phases") or {}
        phase_ids = {int(phase_id) for phase_id in phases}
        completed = {int(phase_id) for phase_id in (state.get("completed") or [])}
        pending = state.get("pending") or []
        start = state.get("unix_millis_start_time")
        finish = state.get("unix_millis_finish_time")
        status = state.get("status")
        if status in {"failed", "canceled", "killed", "error"}:
            return False, f"terminal failure status: {status}"
        if not phase_ids:
            return False, "task has no phases"
        if phase_ids != completed:
            return False, "completed phases do not match task phases"
        if pending:
            return False, "task still has pending phases"
        if not isinstance(start, int) or not isinstance(finish, int) or finish <= start:
            return False, "task has no valid terminal finish timestamp"
        return True, "all phases completed with a terminal finish timestamp"
