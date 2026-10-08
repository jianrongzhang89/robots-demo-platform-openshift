#!/usr/bin/env python3
"""Conservative terminal-success check for RMF Web task-state JSON.

RMF Web can expose a completed phase list and finish timestamp while retaining
``standby`` as the top-level status and stale event statuses. Consumers must
not use ``/dispatch_states.finished`` or top-level status alone as completion.
"""

from __future__ import annotations

import json
import sys
from typing import Any


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
        return False, f"completed phases {sorted(completed)} do not match {sorted(phase_ids)}"
    if pending:
        return False, f"task still has pending phases: {pending}"
    if not isinstance(start, int) or not isinstance(finish, int) or finish <= start:
        return False, "task has no valid terminal finish timestamp"
    return True, "all phases completed with a terminal finish timestamp"


def main() -> int:
    state = json.load(sys.stdin)
    success, reason = terminal_success(state)
    print(json.dumps({"terminal_success": success, "reason": reason}))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
