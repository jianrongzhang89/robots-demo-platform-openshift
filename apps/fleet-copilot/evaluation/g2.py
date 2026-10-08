from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from copilot.store import ConflictError, Store


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "fleet.db"
        first_store = Store(database)
        operations = []
        for number in range(100):
            preview = first_store.create_preview(
                "operator", "hotel-demo", "sha256:4576e4eb1c95cfbb", ["lobby", "L3_middle_hallway"], 1
            )
            operations.append((f"operation-{number:03d}", preview["preview_id"]))

        def submit(item):
            key, preview_id = item
            store = Store(database)
            first = store.create_mission("operator", "hotel-demo", key, preview_id)
            with ThreadPoolExecutor(max_workers=10) as executor:
                retries = list(executor.map(
                    lambda _: Store(database).create_mission("operator", "hotel-demo", key, preview_id),
                    range(10),
                ))
            assert {retry["mission_id"] for retry in retries} == {first["mission_id"]}
            return first["mission_id"]

        with ThreadPoolExecutor(max_workers=10) as executor:
            mission_ids = list(executor.map(submit, operations))

        # A fresh Store instance models gateway restart; persisted keys must replay.
        restarted = Store(database)
        replayed = [
            restarted.create_mission("operator", "hotel-demo", key, preview_id)["mission_id"]
            for (key, preview_id) in operations
        ]
        assert replayed == mission_ids

        conflict_count = 0
        for number in range(100):
            preview = restarted.create_preview(
                "operator", "hotel-demo", "sha256:4576e4eb1c95cfbb", ["lobby", "L3_middle_hallway", "lobby"], 1
            )
            try:
                restarted.create_mission("operator", "hotel-demo", f"operation-{number:03d}", preview["preview_id"])
            except ConflictError:
                conflict_count += 1
        assert conflict_count == 100

        with sqlite3.connect(database) as db:
            missions = db.execute("SELECT COUNT(*) FROM missions").fetchone()[0]
            publications = db.execute("SELECT COUNT(*) FROM dispatch_attempts").fetchone()[0]
            markers = db.execute("SELECT COUNT(*) FROM events WHERE event_type = 'bridge.publish_attempted'").fetchone()[0]

        report = {
            "operations": 100,
            "same_key_retries_per_operation": 10,
            "concurrent_retry_identity": "pass",
            "gateway_restart_replay": "pass",
            "changed_payload_conflicts": conflict_count,
            "mission_rows": missions,
            "dispatch_attempt_rows": publications,
            "publish_markers": markers,
            "duplicate_publications": publications - missions,
            "pass": missions == publications == markers == 100 and conflict_count == 100,
        }
        print(json.dumps(report, indent=2))
        return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
