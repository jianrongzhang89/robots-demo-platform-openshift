#!/usr/bin/env python3
"""Geometry and uncalibrated sensitivity checks, not simulated energy evidence."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path


def segment_energy(a, b, mass, speed, crr, efficiency, auxiliary):
    distance = math.dist(a, b)
    horizontal = math.dist(a[:2], b[:2])
    mechanical_j = mass * 9.80665 * ((b[2] - a[2]) + crr * horizontal)
    return max(mechanical_j, 0) / efficiency / 3600 + auxiliary * distance / speed / 3600


def check(fixture):
    geometry = fixture["geometry"]
    nodes = geometry["nodes"]
    routes = geometry["routes"]
    robot = fixture["robot"]
    for route in routes.values():
        assert route[0] == "loading" and route[-1] == "transfer"
        assert all(name in nodes for name in route)
        assert len(route) == len(set(route)), "route contains cycle"
    dimensions = {}
    for name, ramp in geometry["ramps"].items():
        a, b = [nodes[n] for n in ramp]
        run = math.dist(a[:2], b[:2])
        assert run > 0 and b[2] > a[2]
        dimensions[name] = {"horizontal_run_m": run,
                            "grade": (b[2] - a[2]) / run,
                            "pitch_deg": math.degrees(math.atan2(b[2] - a[2], run))}
    sensitivity = fixture["energy"]["sensitivity_only"]
    rows = []
    for payload, crr, eta, aux, direction in itertools.product(
            robot["payload_candidates_kg"], sensitivity["crr"],
            sensitivity["efficiency"], sensitivity["auxiliary_w"], ["up", "down"]):
        estimates = {}
        for name, route in routes.items():
            path = route if direction == "up" else list(reversed(route))
            estimates[name] = sum(segment_energy(nodes[a], nodes[b],
                robot["physical_mass_kg"] + payload, robot["speed_cap_mps"], crr, eta, aux)
                for a, b in zip(path, path[1:]))
        rows.append({"payload_kg": payload, "crr": crr, "eta": eta,
                     "auxiliary_w": aux, "direction": direction,
                     "energy_wh": estimates, "winner": min(estimates, key=estimates.get)})
    return {"status": "DESIGN_CHECK_ONLY", "calibrated": False,
            "ramps": dimensions,
            "route_length_m": {name: sum(math.dist(nodes[a], nodes[b])
                 for a, b in zip(path, path[1:])) for name, path in routes.items()},
            "scope": "constant speed, no turns/dwell/transitions; same surface and efficiency on both routes",
            "cases": len(rows), "winner_counts": {name: sum(r["winner"] == name for r in rows)
                                                   for name in routes},
            "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = check(json.loads(args.fixture.read_text()))
    report["fixture_sha256"] = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
