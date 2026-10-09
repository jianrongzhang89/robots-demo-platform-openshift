import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from copilot.evidence import classify


class PhaseFourEvidenceTests(unittest.TestCase):
    def mission(self):
        return {"mission_id": "m1", "rmf_task_id": "t1", "allocation": "pending", "execution": "queued", "freshness": "fresh"}

    def test_lift_wait_requires_active_lift_event(self):
        result = classify(self.mission(), [{"event_id": "e1", "event_type": "queued", "source": "rmf", "payload": {"rmf_state": {"active": 2, "phases": {"2": {"events": {"1": {"name": "Take Lift2 to L3", "status": "underway"}}}}}}}])
        self.assertEqual(result["classification"], "lift_wait")
        self.assertEqual(result["evidence_ids"], ["e1"])

    def test_stale_telemetry_is_uncertain(self):
        result = classify(self.mission(), [{"event_id": "e2", "event_type": "observation", "source": "fleet", "payload": {"source_age_ms": 6001}}])
        self.assertEqual(result["classification"], "telemetry_unavailable")
        self.assertTrue(result["uncertainties"])

    def test_missing_evidence_is_unresolved(self):
        result = classify(self.mission(), [])
        self.assertEqual(result["classification"], "allocation_pending")
        self.assertEqual(result["evidence_ids"], [])
        self.assertTrue(result["uncertainties"])

    def test_terminal_completion_overrides_historical_lift_wait(self):
        mission = self.mission() | {"execution": "completed"}
        result = classify(mission, [
            {"event_id": "lift", "event_type": "queued", "source": "rmf", "payload": {"rmf_state": {"active": 2, "phases": {"2": {"events": {"1": {"name": "Take Lift2", "status": "underway"}}}}}}},
            {"event_id": "done", "event_type": "completed", "source": "rmf", "payload": {}},
        ])
        self.assertEqual(result["classification"], "completed")
        self.assertEqual(result["evidence_ids"], ["done"])

    def test_navigation_progress_replaces_completed_lift_wait(self):
        mission = self.mission() | {"execution": "underway"}
        result = classify(mission, [])
        self.assertEqual(result["classification"], "navigation_progress")


if __name__ == "__main__":
    unittest.main()
