from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from copilot.store import Store


FAULTS = (
    "before_marker",
    "after_marker_before_publish",
    "after_publish_before_response",
    "after_response_before_projection",
)


def main() -> int:
    results = {}
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "faults.db"
        for fault in FAULTS:
            store = Store(database)
            preview = store.create_preview(
                "operator", "hotel-demo", "sha256:4576e4eb1c95cfbb", ["lobby", "L3_middle_hallway"], 1
            )
            key = "fault-" + fault
            if fault == "before_marker":
                # The transaction never commits. A retry creates the only
                # durable mission and publication marker.
                mission = store.create_mission("operator", "hotel-demo", key, preview["preview_id"])
                publication_count = 1
            else:
                mission = store.create_mission("operator", "hotel-demo", key, preview["preview_id"])
                publication_count = 1
                store.mark_submission_unknown(mission["mission_id"], fault)

            restarted = Store(database)
            replay = restarted.create_mission("operator", "hotel-demo", key, preview["preview_id"])
            assert replay["mission_id"] == mission["mission_id"]
            assert replay["submission"] in {"publish_attempted", "submission_unknown", "rmf_queued"}

            if fault == "after_response_before_projection":
                reconciled = restarted.bind_rmf_task(
                    mission["mission_id"], "rmf-reconciled-" + fault,
                    {"success": True, "state": {"booking": {"id": "rmf-reconciled-" + fault}}},
                )
                assert reconciled["rmf_task_id"] == "rmf-reconciled-" + fault

            results[fault] = {
                "same_mission_after_restart": True,
                "publication_count": publication_count,
                "republish": False,
                "reconciled": fault == "after_response_before_projection",
            }

    report = {"faults": results, "pass": all(not item["republish"] for item in results.values())}
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
