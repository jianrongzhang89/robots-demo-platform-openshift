from __future__ import annotations

from typing import Any


def _lift_wait(state: dict[str, Any]) -> str | None:
    phases = state.get("phases") or {}
    active = state.get("active")
    candidates = [phases.get(str(active))] if active is not None and phases.get(str(active)) else list(phases.values())
    for phase in candidates:
        if not phase:
            continue
        for event in (phase.get("events") or {}).values():
            name = str(event.get("name", ""))
            if "lift" in name.lower() and event.get("status") == "underway":
                return name
    return None


def classify(mission: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    evidence_ids: list[str] = []
    classification = "unresolved"
    uncertainties: list[str] = []
    summary = "The current cause cannot be established from correlated evidence."

    if mission.get("execution") == "completed":
        terminal_ids = [event["event_id"] for event in events if event.get("event_type") == "completed"]
        if terminal_ids:
            return {
                "classification": "completed",
                "summary": "The mission completed according to correlated RMF terminal evidence.",
                "claims": [{"text": "The mission completed according to correlated RMF terminal evidence.", "evidence_ids": terminal_ids[-1:]}],
                "uncertainties": [],
                "suggested_next_checks": [],
                "facts": [],
                "evidence_ids": terminal_ids[-1:],
                "mission_id": mission["mission_id"],
                "rmf_task_id": mission.get("rmf_task_id"),
                "observation_age_ms": None,
            }

    latest_state_event = next(
        (event for event in reversed(events) if isinstance((event.get("payload") or {}).get("rmf_state"), dict) or "source_age_ms" in (event.get("payload") or {}) or event.get("event_type") in {"failed", "failed_to_assign"}),
        None,
    )
    state_events = [latest_state_event] if latest_state_event else []
    for event in state_events:
        payload = event.get("payload") or {}
        state = payload.get("rmf_state") if isinstance(payload, dict) else None
        if not isinstance(state, dict):
            state = {}
        lift = _lift_wait(state)
        if lift:
            classification = "lift_wait"
            summary = f"The task is waiting on an active lift event: {lift}."
            facts.append({"text": lift, "source": event.get("source")})
            evidence_ids = [event["event_id"]]
        if event.get("event_type") in {"failed", "failed_to_assign"}:
            classification = "navigation_failure" if event.get("event_type") == "failed" else "allocation_failed"
            summary = "The correlated task reported a failure; completion is not claimed."
            facts.append({"text": event.get("event_type"), "source": event.get("source")})
            evidence_ids = [event["event_id"]]
        source_age = payload.get("source_age_ms") if isinstance(payload, dict) else None
        if isinstance(source_age, (int, float)) and source_age > 5000:
            classification = "telemetry_unavailable"
            summary = f"Progress evidence is stale ({source_age:.0f} ms old)."
            uncertainties.append("The current delay cause cannot be established from stale telemetry.")
            evidence_ids = [event["event_id"]]

    if not evidence_ids:
        if mission.get("allocation") == "failed_to_assign":
            classification = "allocation_failed"
            summary = "RMF did not assign the mission to a fleet."
        elif mission.get("allocation") == "pending" and mission.get("execution") in {"unknown", "queued"}:
            classification = "allocation_pending"
            summary = "RMF is still allocating or starting the mission."
        uncertainties.append("No correlated evidence event supports a more specific cause.")

    if mission.get("freshness") in {"stale", "source_gap", "generation_changed"}:
        classification = "telemetry_unavailable"
        summary = "Progress evidence is unavailable or belongs to an older episode."
        uncertainties.append(f"Mission freshness is {mission['freshness']}.")

    if mission.get("execution") == "underway" and classification == "unresolved":
        classification = "navigation_progress"
        summary = "The robot is continuing navigation after the lift transition."
        uncertainties.append("The mission is not complete yet; terminal evidence is still pending.")

    return {
        "classification": classification,
        "summary": summary,
        "claims": [{"text": summary, "evidence_ids": evidence_ids}],
        "uncertainties": uncertainties,
        "suggested_next_checks": ["Inspect the latest correlated RMF task event and source age."],
        "facts": facts,
        "evidence_ids": evidence_ids,
        "mission_id": mission["mission_id"],
        "rmf_task_id": mission.get("rmf_task_id"),
        "observation_age_ms": None,
    }
