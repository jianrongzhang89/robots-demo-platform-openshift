#!/usr/bin/env python3
"""No-motion planner spike in the pinned RMF image; no task is dispatched.

Ordered go_to_place destinations force each ramp through RMF. This checks the
installed planner's graph sequence only, not a live schedule or Nav2 trajectory.
"""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import rmf_adapter.geometry as geometry
import rmf_adapter.graph as graph
import rmf_adapter.plan as plan
import rmf_adapter.vehicletraits as traits


def check(fixture):
    nodes = fixture["geometry"]["nodes"]
    routes = fixture["geometry"]["routes"]
    network = graph.Graph()
    indices = {}
    for name, xyz in nodes.items():
        waypoint = network.add_waypoint("warehouse", xyz[:2])
        indices[name] = waypoint.index
        network.add_key(name, waypoint.index)
    edges = set()
    for path in [*routes.values(), ["loading", "charger"]]:
        for a, b in zip(path, path[1:]):
            edge = tuple(sorted((a, b)))
            if edge not in edges:
                network.add_bidir_lane(indices[a], indices[b])
                edges.add(edge)
    profile = traits.Profile(geometry.make_final_convex_circle(0.246))
    vehicle = traits.VehicleTraits(traits.Limits(0.1, 0.1), traits.Limits(0.45, 0.7), profile)
    planner = plan.Planner(plan.Configuration(network, vehicle))
    names = {index: name for name, index in indices.items()}

    def leg(a, b):
        result = planner.get_plan_waypoints(plan.Start(datetime.now(), indices[a], 0.0),
                                            plan.Goal(indices[b]))
        sequence = []
        for waypoint in result:
            if waypoint.graph_index is not None:
                name = names[waypoint.graph_index]
                if not sequence or sequence[-1] != name:
                    sequence.append(name)
        if not sequence or sequence[0] != a or sequence[-1] != b:
            raise RuntimeError(f"planner did not connect {a} to {b}: {sequence}")
        return sequence

    checks = []
    for name, route in routes.items():
        for direction, path in [("up", route), ("down", list(reversed(route)))]:
            actual = [path[0]]
            for a, b in zip(path, path[1:]):
                actual.extend(leg(a, b)[1:])
            checks.append({"route": name, "direction": direction,
                           "requested": path, "planned": actual, "pass": actual == path})
    return {"status": "PASS" if all(r["pass"] for r in checks) else "FAIL",
            "motion_dispatched": False, "live_itinerary_agreement": "NOT_TESTED",
            "direct_endpoint_plan": leg("loading", "transfer"), "checks": checks,
            "request_example": {"type": "dispatch_task_request", "request": {
                "category": "compose", "fleet_name": "warehouse_energy",
                "requester": "warehouse-energy", "description": {
                    "category": "warehouse_route_B", "phases": [
                        {"activity": {"category": "go_to_place", "description": {
                            "one_of": [{"waypoint": waypoint}]}}}
                        for waypoint in routes["B"][1:]]}}}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    result = check(json.loads(args.fixture.read_text()))
    result["fixture_sha256"] = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    print(json.dumps(result, indent=2))
    raise SystemExit(result["status"] != "PASS")
