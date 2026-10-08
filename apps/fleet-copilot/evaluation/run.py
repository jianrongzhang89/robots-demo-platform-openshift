from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from copilot.catalog import Catalog
from copilot.interpreter import interpret
from copilot.providers import MockProvider, OpenAIProvider


def supported_cases() -> list[str]:
    subjects = ["Send the robot", "Please take the robot", "Navigate the robot", "Have the robot go", "Start a patrol"]
    destinations = ["third-floor middle hallway", "level 3 middle hallway", "third floor hallway", "middle hallway", "L3"]
    endings = ["and bring it back", "then return to the lobby", "and return", "and come back"]
    return [f"{subject} from the lobby to the {destination} {ending}." for subject in subjects for destination in destinations for ending in endings]


def unsupported_cases() -> list[str]:
    return [
        *[f"Send the robot to the {floor} floor." for floor in ("fourth", "fifth", "sixth", "seventh", "eighth") for _ in range(5)],
        *[f"Deliver package {number} from the lobby to the third floor." for number in range(1, 26)],
    ]


def main() -> int:
    root = Path(__file__).parents[1]
    catalog = Catalog.load(root / "fixtures" / "catalog.hotel-demo.json")
    provider = OpenAIProvider() if os.environ.get("FLEET_COPILOT_PROVIDER") == "openai" else MockProvider()
    supported = supported_cases()
    unsupported = unsupported_cases()
    runs = []
    raw_outputs = []
    for repetition in range(1, 4):
        correct = 0
        safe_rejections = 0
        for case in supported:
            preview = interpret(case, catalog, provider)
            correct += preview.places == ("lobby", "L3_middle_hallway", "lobby")
            raw_outputs.append({"repetition": repetition, "kind": "supported", "input": case, "preview": preview.as_dict()})
        for case in unsupported:
            preview = interpret(case, catalog, provider)
            safe_rejections += not preview.dispatchable
            raw_outputs.append({"repetition": repetition, "kind": "unsupported", "input": case, "preview": preview.as_dict()})
        runs.append({"repetition": repetition, "supported_correct": correct, "supported_total": len(supported), "unsupported_held": safe_rejections, "unsupported_total": len(unsupported)})
    report = {"phase": 1, "provider": provider.name, "catalog_version": catalog.version, "runs": runs, "raw_outputs": raw_outputs, "pass": all(run["supported_correct"] >= 95 and run["unsupported_held"] == 50 for run in runs)}
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
