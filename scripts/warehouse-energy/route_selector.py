#!/usr/bin/env python3
"""Stage 2 route selector: distance or calibrated-physics energy routing.

Selects a directed corridor over the frozen fixture route graph before any
motion starts, subject to hard feasibility checks: the frozen one-way
mission deadline and the battery-reserve requirement after the mission plus
charger access. Arm A picks the shortest feasible distance; arm B picks the
minimum predicted-energy feasible route using the frozen Stage 2 physics
model. If no route is feasible the mission is rejected with an explicit
reason and no task is dispatched.

The selector is deterministic and planning-time only: it never reads
observed telemetry.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from physics_model import PhysicsModel, predict_path


def ramp_edges(fixture):
    nodes = fixture["geometry"]["nodes"]
    edges = {}
    for name, (low, high) in fixture["geometry"]["ramps"].items():
        run = math.dist(nodes[low][:2], nodes[high][:2])
        edges[(low, high)] = run
        edges[(high, low)] = run
    return edges


def predict_route(model, fixture, route_path, payload_kg):
    nodes = fixture["geometry"]["nodes"]
    mass = fixture["robot"]["physical_mass_kg"] + payload_kg
    return predict_path(model, nodes, route_path, ramp_edges(fixture), mass)


def charger_access_path(fixture, route):
    """Mission goal back to the charger along a given route's descent."""
    return list(reversed(fixture["geometry"]["routes"][route])) + ["charger"]


def route_segment_inputs(fixture, path, payload_kg, speed_mps=None,
                         dwell_s=None):
    """Raw serving-request segment inputs for a directed path.

    Uses exact graph values (unrounded headings and rises) matching the
    Stage 3A dataset derivation; dwell follows the navigation convention
    (no transition before the first edge, the frozen per-goal allowance
    afterwards) unless overridden.
    """
    nodes = fixture["geometry"]["nodes"]
    edges = ramp_edges(fixture)
    mass = fixture["robot"]["physical_mass_kg"] + payload_kg
    speed = float(speed_mps if speed_mps is not None
                  else fixture["robot"]["speed_cap_mps"])
    if dwell_s is None:
        dwell_s = 13.5  # frozen per-goal transition allowance
    segments = []
    previous_heading = None
    for start, end in zip(path, path[1:]):
        a, b = nodes[start], nodes[end]
        heading = math.atan2(b[1] - a[1], b[0] - a[0])
        change = 0.0 if previous_heading is None else abs(math.atan2(
            math.sin(heading - previous_heading), math.cos(heading - previous_heading)))
        previous_heading = heading
        segments.append({
            "length_m": math.dist(a[:2], b[:2]),
            "ramp_run_m": edges.get((start, end)),
            "signed_rise_m": b[2] - a[2],
            "speed_mps": speed,
            "heading_change_rad": change,
            "planned_stops": 0,
            "planned_dwell_s": 0.0 if len(segments) == 0 else dwell_s,
            "total_mass_kg": mass,
            "class": "nav",
        })
    return segments


class ServedEstimator:
    """Arm C mission estimator backed by the qualified serving endpoint.

    Batches every candidate mission into one bounded request. The client's
    documented fallback returns physics-only predictions with the frozen
    conservative allowance when the endpoint is unavailable, so route
    selection degrades exactly as specified.
    """

    def __init__(self, client, fixture):
        self.client = client
        self.fixture = fixture

    def estimate(self, path, payload_kg, generation):
        segments = route_segment_inputs(self.fixture, path, payload_kg)
        result = self.client.predict_batch(segments, generation)
        return {"wh": sum(s["predicted_wh"] for s in result["segments"]),
                "duration_s": sum(s["planned_duration_s"] for s in result["segments"]),
                "mode": result["mode"], "segments": result["segments"],
                "allowance_wh": (result["allowances"]["learned_wh"]
                                 if result["mode"] == "served"
                                 else result["allowances"]["physics_fallback_wh"])}


def select_stage4(model, fixture, arm, payload_kg, initial_soc, excluded=(),
                  direction="up", estimator=None, round_trip_return_payload_kg=None,
                  physics_allowance_wh=0.0):
    """Stage 4 selection across the three comparison arms.

    Arm A picks the shortest feasible distance with physics-based
    feasibility checks (energy is logged only). Arm B picks the minimum
    predicted-energy route with the calibrated physics estimator. Arm C
    uses the supplied served estimator (physics-plus-XGBoost) with its
    documented fallback. Round-trip planning adds the return leg at the
    given payload and the charger access from the mission end.
    """
    if arm not in ("A", "B", "C"):
        raise ValueError("arm must be A, B or C")
    energy = fixture["energy"]
    capacity = float(energy["nominal_battery_wh"])
    reserve = float(energy["minimum_soc_after_mission_and_charger"])
    deadline = float(energy["deadline_one_way_s"])
    available = [name for name in sorted(fixture["geometry"]["routes"])
                 if name not in excluded]

    def mission_estimate(path, payload):
        if arm == "C" and estimator is not None:
            return estimator.estimate(path, payload, f"selection-{arm}")
        return predict_route(model, fixture, path, payload)

    # Charger access from the mission goal along each available route.
    access_estimates = {
        name: mission_estimate(charger_access_path(fixture, name), payload_kg)
        for name in sorted(fixture["geometry"]["routes"])}
    access_by_route = {name: (access_estimates[name] if name in available else None)
                       for name in sorted(fixture["geometry"]["routes"])}
    estimates = {}
    for name in sorted(fixture["geometry"]["routes"]):
        route = fixture["geometry"]["routes"][name]
        path = route if direction == "up" else list(reversed(route))
        mission = mission_estimate(path, payload_kg)
        total_wh = mission["wh"]
        total_duration = mission["duration_s"]
        if round_trip_return_payload_kg is not None:
            return_path = list(reversed(path))
            return_leg = mission_estimate(return_path, round_trip_return_payload_kg)
            # After returning to the start, charger access is the short
            # level link from the start node.
            access_from_start = mission_estimate(
                [path[0], "charger"], round_trip_return_payload_kg)
            total_wh += return_leg["wh"] + access_from_start["wh"]
            total_duration += return_leg["duration_s"]
            access_wh = access_from_start["wh"]
        else:
            access_wh = min((access_by_route[r]["wh"] for r in available
                             if access_by_route[r] is not None), default=None)
        # Each arm applies its own estimator's calibrated uncertainty to the
        # reserve check; arms A and B use the frozen physics-mode allowance.
        allowance = (mission.get("allowance_wh")
                     if arm == "C" and estimator is not None else None)
        if allowance is None:
            allowance = physics_allowance_wh
        if round_trip_return_payload_kg is not None and direction != "up":
            raise ValueError("round-trip missions start with the uphill leg")
        violations = []
        if name in excluded:
            violations.append(f"route excluded at planning time: {name}")
        if total_duration > (2 * deadline if round_trip_return_payload_kg is not None
                             else deadline):
            violations.append(f"predicted duration {total_duration:.1f}s exceeds deadline")
        final_soc = initial_soc - (total_wh + allowance +
                                   (0.0 if round_trip_return_payload_kg is not None
                                    else access_wh)) / capacity
        if final_soc < reserve:
            violations.append(f"predicted final SOC {final_soc:.4f} below reserve {reserve}")
        estimates[name] = {
            "path": path, "distance_m": round(sum(
                math.dist(fixture["geometry"]["nodes"][a][:2],
                          fixture["geometry"]["nodes"][b][:2])
                for a, b in zip(path, path[1:])), 3),
            "predicted_mission_wh": round(mission["wh"], 6),
            "predicted_duration_s": round(mission["duration_s"], 2),
            "round_trip_predicted_total_wh": (round(total_wh, 6)
                                              if round_trip_return_payload_kg is not None
                                              else None),
            "charger_access_wh": round(access_wh, 6) if access_wh is not None else None,
            "uncertainty_allowance_wh": round(allowance, 8),
            "predicted_final_soc": round(final_soc, 6),
            "estimator_mode": mission.get("mode", "physics"),
            "feasible": not violations, "violations": violations,
        }
    feasible = [name for name in available if estimates[name]["feasible"]]
    decision = {"arm": arm, "payload_kg": payload_kg, "initial_soc": initial_soc,
                "direction": direction, "excluded_routes": sorted(excluded),
                "round_trip_return_payload_kg": round_trip_return_payload_kg,
                "routes": estimates,
                "tie_energy_wh": float(energy["tie_energy_wh"]),
                "selected_route": None, "rejection_reason": None}
    if not feasible:
        reasons = "; ".join(f"{n}: {'; '.join(estimates[n]['violations'])}"
                            for n in available) or "no candidate routes"
        decision["rejection_reason"] = f"no feasible route ({reasons})"
        decision["status"] = "REJECTED"
        return decision
    objective_key = (lambda name: (estimates[name]["distance_m"], name)) if arm == "A" \
        else (lambda name: (estimates[name][
            "round_trip_predicted_total_wh" if round_trip_return_payload_kg is not None
            else "predicted_mission_wh"], estimates[name]["predicted_duration_s"], name))
    selected = min(feasible, key=objective_key)
    decision["selected_route"] = selected
    decision["status"] = "SELECTED"
    return decision


def evaluate_routes(model, fixture, payload_kg, initial_soc, excluded):
    energy = fixture["energy"]
    capacity = float(energy["nominal_battery_wh"])
    reserve = float(energy["minimum_soc_after_mission_and_charger"])
    deadline = float(energy["deadline_one_way_s"])
    available = [name for name in sorted(fixture["geometry"]["routes"]) if name not in excluded]
    # After the mission the robot may descend by any route still available;
    # reserve feasibility uses the cheapest predicted access among them.
    access_estimates = {
        name: predict_route(model, fixture, charger_access_path(fixture, name), payload_kg)
        for name in sorted(fixture["geometry"]["routes"])
    }
    access_wh = min((access_estimates[name]["wh"] for name in available), default=None)
    estimates = {}
    for name in sorted(fixture["geometry"]["routes"]):
        route = fixture["geometry"]["routes"][name]
        mission = predict_route(model, fixture, route, payload_kg)
        violations = []
        if name in excluded:
            violations.append(f"route excluded at planning time: {name}")
        if mission["duration_s"] > deadline:
            violations.append(
                f"predicted duration {mission['duration_s']:.1f}s exceeds deadline {deadline}s")
        final_soc = initial_soc - (mission["wh"] + access_wh) / capacity
        if final_soc < reserve:
            violations.append(
                f"predicted final SOC {final_soc:.4f} below reserve {reserve} after mission "
                f"plus charger access")
        estimates[name] = {
            "path": route, "distance_m": round(mission["distance_m"], 3),
            "predicted_mission_wh": round(mission["wh"], 6),
            "predicted_duration_s": round(mission["duration_s"], 2),
            "charger_access_policy": "minimum predicted energy over routes available at planning time",
            "charger_access_wh": round(access_wh, 6),
            "predicted_final_soc": round(final_soc, 6),
            "feasible": not violations, "violations": violations,
        }
    return estimates, available


def select(model, fixture, arm, payload_kg, initial_soc, excluded=()):
    if arm not in ("A", "B"):
        raise ValueError("arm must be A or B")
    estimates, available = evaluate_routes(model, fixture, payload_kg, initial_soc, excluded)
    feasible = [name for name in available if estimates[name]["feasible"]]
    decision = {
        "arm": arm,
        "objective": ("minimum_distance" if arm == "A"
                      else "minimum_predicted_mission_energy"),
        "payload_kg": payload_kg,
        "initial_soc": initial_soc,
        "excluded_routes": sorted(excluded),
        "routes": estimates,
        "selected_route": None,
        "rejection_reason": None,
        "tie_energy_wh": float(fixture["energy"]["tie_energy_wh"]),
        "tie_break": fixture["energy"]["tie_break"],
    }
    if not feasible:
        reasons = "; ".join(f"{name}: {'; '.join(estimates[name]['violations'])}"
                            for name in available) or "no candidate routes"
        decision["rejection_reason"] = f"no feasible route ({reasons})"
        decision["status"] = "REJECTED"
        return decision
    if arm == "A":
        selected = min(feasible, key=lambda name: (estimates[name]["distance_m"], name))
    else:
        best = min(estimates[name]["predicted_mission_wh"] for name in feasible)
        tied = [name for name in feasible
                if estimates[name]["predicted_mission_wh"] <= best + decision["tie_energy_wh"]]
        selected = min(tied, key=lambda name: (estimates[name]["predicted_duration_s"], name))
    decision["selected_route"] = selected
    decision["status"] = "SELECTED"
    return decision


def should_switch(current_route, estimates, hysteresis_fraction, current_excluded=()):
    """Replanning hysteresis: switch corridors only for a material gain.

    Returns the route to keep: the incumbent unless another feasible route
    predicts more than hysteresis_fraction lower mission energy.
    """
    feasible = {name: row for name, row in estimates.items()
                if row["feasible"] and name not in current_excluded}
    if current_route not in feasible:
        return min(feasible, key=lambda name: feasible[name]["predicted_mission_wh"]) \
            if feasible else None
    current = feasible[current_route]["predicted_mission_wh"]
    for name, row in feasible.items():
        if name == current_route:
            continue
        if row["predicted_mission_wh"] < current * (1.0 - hysteresis_fraction):
            return name
    return current_route


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--arm", choices=["A", "B"], required=True)
    parser.add_argument("--payload", type=float, default=0.5)
    parser.add_argument("--initial-soc", type=float, default=0.8)
    parser.add_argument("--exclude-route", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    model = PhysicsModel.load(args.physics_model)
    decision = select(model, fixture, args.arm, args.payload, args.initial_soc,
                      tuple(args.exclude_route))
    decision["fixture_sha256"] = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    decision["physics_model_sha256"] = hashlib.sha256(args.physics_model.read_bytes()).hexdigest()
    decision["scope"] = ("planning-time selection over the frozen simulation fixture using the "
                         "calibrated physics model; not a physical energy measurement")
    text = json.dumps(decision, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
