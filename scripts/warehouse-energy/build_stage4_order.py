#!/usr/bin/env python3
"""Emit the frozen Stage 4 trial order (deterministic seeded shuffle)."""
import argparse
import json
import random


def build_order(experiment):
    rng = random.Random(experiment["randomization"]["seed"])
    strata = [(payload, direction)
              for payload in experiment["strata"]["payloads_kg"]
              for direction in experiment["strata"]["directions"]]
    rng.shuffle(strata)
    trials = []
    for payload, direction in strata:
        for triplet in range(experiment["one_way_triplets_per_stratum"]):
            arms = ["A", "B", "C"]
            rng.shuffle(arms)
            for arm in arms:
                label = f"p{payload}-d{direction}"
                trials.append({"name": f"ow-{label}-t{triplet}-arm{arm}",
                               "kind": "oneway", "arm": arm,
                               "payload": payload, "direction": direction})
    for triplet in range(experiment["round_trip"]["triplets"]):
        arms = ["A", "B", "C"]
        rng.shuffle(arms)
        for arm in arms:
            for leg, direction in (("out", "up"), ("return", "down")):
                trials.append({"name": f"rt-t{triplet}-arm{arm}-{leg}",
                               "kind": f"roundtrip-{leg}", "arm": arm,
                               "payload": experiment["round_trip"]["outbound_payload_kg"]
                               if leg == "out" else experiment["round_trip"]["return_payload_kg"],
                               "direction": direction})
    trials.append({"name": "fallback-armC-serving-unavailable",
                   "kind": "oneway", "arm": "C", "payload": 0.5,
                   "direction": "up", "serving_unavailable": True})
    return trials


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=argparse.FileType(), required=True)
    parser.add_argument("--output", type=argparse.FileType("w"), required=True)
    args = parser.parse_args()
    experiment = json.load(args.experiment)
    trials = build_order(experiment)
    args.output.write(json.dumps(trials, indent=2) + "\n")
    print(json.dumps({"trials": len(trials),
                      "oneway": sum(1 for t in trials if t["kind"] == "oneway"),
                      "roundtrip_legs": sum(1 for t in trials
                                            if t["kind"].startswith("roundtrip"))}))
