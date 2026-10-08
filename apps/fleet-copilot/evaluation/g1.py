from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from copilot.catalog import Catalog
from copilot.interpreter import interpret
from copilot.providers import OpenAIProvider, ProviderError


def heldout_supported() -> list[str]:
    subjects = [
        "Please have the service robot travel",
        "I need the hotel robot to move",
        "Could you route the robot",
        "Ask the robot to proceed",
        "Have our robot patrol",
    ]
    destinations = [
        "third-floor middle hallway",
        "level-3 middle hallway",
        "third floor hallway",
        "middle hallway",
        "L3",
    ]
    endings = [
        "and return to the lobby",
        "returning to the entrance afterward",
        "then come back to the ground floor",
        "and bring it back to the first floor",
    ]
    return [
        f"{subject} from the entrance to the {destination}, {ending}."
        for subject in subjects
        for destination in destinations
        for ending in endings
    ]


def heldout_unsupported() -> list[str]:
    invented = [
        "basement archive",
        "L4 east wing",
        "second-floor suite 204",
        "roof terrace",
        "room 999",
    ]
    delivery = [
        "medicine",
        "mail",
        "a package",
        "towels",
        "a meal",
    ]
    return [
        f"Send the robot to the {place} and return."
        for place in invented
        for _ in range(5)
    ] + [
        f"Deliver {item} from the lobby to level 3."
        for item in delivery
        for _ in range(5)
    ]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[index]


def main() -> int:
    root = Path(__file__).parents[1]
    catalog = Catalog.load(root / "fixtures" / "catalog.hotel-demo.json")
    provider = OpenAIProvider()
    supported = heldout_supported()
    unsupported = heldout_unsupported()
    latencies: list[float] = []
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    missing_usage = 0
    runs = []
    raw_outputs = []

    for repetition in range(1, 4):
        correct = 0
        held = 0
        for kind, cases in (("supported", supported), ("unsupported", unsupported)):
            for case in cases:
                started = time.perf_counter()
                preview = interpret(case, catalog, provider)
                latencies.append(time.perf_counter() - started)
                usage = provider.last_usage
                if usage is None:
                    missing_usage += 1
                else:
                    prompt_tokens += usage.get("prompt_tokens", 0)
                    completion_tokens += usage.get("completion_tokens", 0)
                    total_tokens += usage.get("total_tokens", 0)
                if kind == "supported":
                    correct += preview.places == ("lobby", "L3_middle_hallway", "lobby")
                else:
                    held += not preview.dispatchable
                raw_outputs.append({"repetition": repetition, "kind": kind, "input": case, "preview": preview.as_dict()})
        runs.append({
            "repetition": repetition,
            "supported_correct": correct,
            "supported_total": len(supported),
            "unsupported_held": held,
            "unsupported_total": len(unsupported),
        })

    input_rate = float(os.environ.get("FLEET_COPILOT_INPUT_COST_PER_1M", "0.40"))
    output_rate = float(os.environ.get("FLEET_COPILOT_OUTPUT_COST_PER_1M", "1.60"))
    cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
    semantic_pass = all(
        run["supported_correct"] >= 95 and run["unsupported_held"] == 50
        for run in runs
    )
    report = {
        "phase": 1,
        "corpus": "held-out",
        "provider": provider.name,
        "model": provider.model,
        "catalog_version": catalog.version,
        "runs": runs,
        "latency_seconds": {
            "count": len(latencies),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
            "budget_seconds": 5,
        },
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "missing_usage_calls": missing_usage,
        },
        "cost": {
            "input_usd_per_1m": input_rate,
            "output_usd_per_1m": output_rate,
            "estimated_usd": cost,
        },
        "semantic_pass": semantic_pass,
        "latency_pass": bool(latencies) and percentile(latencies, 0.95) <= 5,
        "usage_pass": missing_usage == 0,
        "pass": semantic_pass and bool(latencies) and percentile(latencies, 0.95) <= 5 and missing_usage == 0,
        "raw_outputs": raw_outputs,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
