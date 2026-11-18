#!/usr/bin/env python3
"""Freeze offline served-prediction expectations for the Stage 4 request set.

Enumerates every segment batch the Stage 4 selector can request — each
candidate route in each direction, each charger-access descent, and the
start-to-charger link, at each planning payload — and records the frozen
release's offline predictions. The Stage 4 audit compares the served
values stored in each trial's selection record against these expectations.
Runs in the pinned pod with the vendored xgboost.
"""
import argparse
import json
from pathlib import Path

import xgboost

import predictor as predictor_module
import route_selector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    predictor = predictor_module.EnergyPredictor(
        args.release_dir, args.physics_model, args.manifest, xgboost_module=xgboost)
    payloads = [0.0, 0.25, 0.5]
    paths = {}
    for name in sorted(fixture["geometry"]["routes"]):
        route = fixture["geometry"]["routes"][name]
        paths[f"{name}-up"] = route
        paths[f"{name}-down"] = list(reversed(route))
        paths[f"access-{name}"] = route_selector.charger_access_path(fixture, name)
    paths["start-charger"] = ["loading", "charger"]
    expectations = {}
    for path_id, path in sorted(paths.items()):
        for payload in payloads:
            segments = route_selector.route_segment_inputs(fixture, path, payload)
            results = predictor.predict_segments(segments)
            expectations[f"{path_id}|p{payload}"] = {
                "segments": len(results),
                "predicted_wh": round(sum(r["predicted_wh"] for r in results), 6),
                "physics_wh": round(sum(r["physics_wh"] for r in results), 6),
                "duration_s": round(sum(r["planned_duration_s"] for r in results), 2),
            }
    document = {"schema": "warehouse-stage4-expectations/v1",
                "payloads_kg": payloads, "paths": sorted(paths),
                "expectations": expectations}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n")
    print(json.dumps({"paths": len(paths), "payloads": len(payloads),
                      "entries": len(expectations)}))


if __name__ == "__main__":
    main()
