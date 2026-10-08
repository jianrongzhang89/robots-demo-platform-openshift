import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from copilot.store import ConflictError, Store
from copilot.bridge import RmfBridge


class PhaseTwoStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "fleet.db")
        self.preview = self.store.create_preview(
            "operator", "hotel-demo", "sha256:4576e4eb1c95cfbb", ["lobby", "L3_middle_hallway"], 1
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_idempotency_retries_have_one_mission_and_one_publication(self):
        first = self.store.create_mission("operator", "hotel-demo", "same-key", self.preview["preview_id"])
        retries = [
            self.store.create_mission("operator", "hotel-demo", "same-key", self.preview["preview_id"])
            for _ in range(10)
        ]
        self.assertTrue(all(item["mission_id"] == first["mission_id"] for item in retries))
        with sqlite3.connect(self.store.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dispatch_attempts").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE event_type = 'bridge.publish_attempted'").fetchone()[0], 1)

    def test_concurrent_retries_share_identity(self):
        def submit(_):
            return self.store.create_mission("operator", "hotel-demo", "concurrent-key", self.preview["preview_id"])["mission_id"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            mission_ids = list(executor.map(submit, range(10)))
        self.assertEqual(set(mission_ids), {mission_ids[0]})

    def test_changed_payload_with_same_key_conflicts(self):
        self.store.create_mission("operator", "hotel-demo", "same-key", self.preview["preview_id"])
        other = self.store.create_preview(
            "operator", "hotel-demo", "sha256:4576e4eb1c95cfbb", ["lobby", "L3_middle_hallway", "lobby"], 1
        )
        with self.assertRaises(ConflictError):
            self.store.create_mission("operator", "hotel-demo", "same-key", other["preview_id"])

    def test_existing_idempotency_key_replays_after_preview_expiry(self):
        first = self.store.create_mission("operator", "hotel-demo", "expired-key", self.preview["preview_id"])
        with sqlite3.connect(self.store.path) as db:
            db.execute("UPDATE previews SET expires_at = '2000-01-01T00:00:00+00:00'")
        replay = self.store.create_mission("operator", "hotel-demo", "expired-key", self.preview["preview_id"])
        self.assertEqual(replay["mission_id"], first["mission_id"])

    def test_terminal_state_wins_over_late_snapshot_and_reset_changes_generation(self):
        mission = self.store.create_mission("operator", "hotel-demo", "terminal-key", self.preview["preview_id"])
        mission_id = mission["mission_id"]
        self.store.record_event(mission_id, "completed", {}, "rmf-emulator", "terminal-1")
        late = self.store.record_event(mission_id, "queued", {}, "rmf-emulator", "late-1")
        self.assertEqual(late["execution"], "completed")
        old_episode = late["episode_id"]
        pending = self.store.create_mission("operator", "hotel-demo", "pending-key", self.preview["preview_id"])
        reset = self.store.reset_episode()
        self.assertNotEqual(old_episode, reset["episode_id"])
        self.assertEqual(self.store.get_mission(mission_id)["freshness"], "fresh")
        self.assertEqual(self.store.get_mission(pending["mission_id"])["freshness"], "generation_changed")

    def test_duplicate_and_out_of_order_events_do_not_regress_projection(self):
        mission = self.store.create_mission("operator", "hotel-demo", "ordering-key", self.preview["preview_id"])
        mission_id = mission["mission_id"]
        self.store.record_event(mission_id, "dispatched", {"rmf_task_id": "rmf-1"}, "rmf", "evt-1")
        self.store.record_event(mission_id, "queued", {}, "rmf", "evt-2")
        duplicate = self.store.record_event(mission_id, "queued", {}, "rmf", "evt-1")
        self.assertEqual(duplicate["execution"], "underway")
        self.assertEqual(duplicate["revision"], 2)

    def test_rmf_dispatch_leaves_time_to_the_simulation_clock(self):
        class CapturingBridge(RmfBridge):
            def __init__(self):
                super().__init__("http://rmf")
                self.payload = None

            def _request(self, method, path, payload=None):
                self.payload = payload
                return {"success": True, "state": {"booking": {"id": "rmf-1"}}}

        bridge = CapturingBridge()
        bridge.dispatch({
            "mission_id": "mission-1", "episode_id": "episode-1", "site_id": "hotel-demo",
            "places": ["lobby", "L3_middle_hallway"], "rounds": 1,
        })
        request = bridge.payload["request"]
        self.assertNotIn("unix_millis_request_time", request)
        self.assertNotIn("unix_millis_earliest_start_time", request)

    def test_foreign_events_cannot_advance_a_mission(self):
        mission = self.store.create_mission("operator", "hotel-demo", "foreign-key", self.preview["preview_id"])
        with self.assertRaises(ConflictError):
            self.store.record_event(
                mission["mission_id"], "completed",
                {"mission_id": "other-mission"}, "rmf", "foreign-1"
            )


if __name__ == "__main__":
    unittest.main()
