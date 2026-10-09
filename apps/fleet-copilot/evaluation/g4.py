from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from copilot.evidence import classify


def fixtures():
    cases = []
    for kind in ("allocation_pending", "lift_wait", "navigation_failure", "telemetry_unavailable"):
        for number in range(10):
            mission = {"mission_id": f"mission-{kind}-{number}", "rmf_task_id": "rmf-1", "allocation": "pending", "execution": "queued", "freshness": "fresh"}
            events = []
            if kind == "lift_wait":
                events = [{"event_id": f"event-{kind}-{number}", "event_type": "queued", "source": "rmf", "payload": {"rmf_state": {"active": 2, "phases": {"2": {"events": {"1": {"name": "Take Lift2 to L3", "status": "underway"}}}}}}}]
            elif kind == "navigation_failure":
                events = [{"event_id": f"event-{kind}-{number}", "event_type": "failed", "source": "rmf", "payload": {}}]
            elif kind == "telemetry_unavailable":
                events = [{"event_id": f"event-{kind}-{number}", "event_type": "observation", "source": "fleet", "payload": {"source_age_ms": 6000}}]
            cases.append((kind, mission, events))
    return cases


def main() -> int:
    results = []
    for expected, mission, events in fixtures():
        result = classify(mission, events)
        valid_ids = all(claim_id in {event["event_id"] for event in events} for claim in result["claims"] for claim_id in claim["evidence_ids"])
        results.append(expected == result["classification"] and valid_ids)
    passed = sum(results)
    report = {"fixtures": len(results), "passed": passed, "accuracy": passed / len(results), "pass": passed >= 38 and all(results)}
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
