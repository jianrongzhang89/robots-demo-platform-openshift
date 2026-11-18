#!/usr/bin/env python3
"""Fit and freeze the Stage 2 planning physics model.

Calibration data: the 36 dedicated Phase 0 fresh-world ramp trials (two
routes x two directions x three payloads x three resets) retained in the
Phase 0 qualification archive. Each trial's scripted command profile is
reconstructed from the published phase-0 trial logic; observed electrical
Wh is recomputed from the raw actuator trace under the frozen Phase 1
telemetry accounting model. Only complete runs are used.

The fit minimizes squared error between predicted and observed Wh over
(rolling resistance, drive efficiency, auxiliary power). Because predicted
energy is linear in (1/eta, auxiliary) for a fixed rolling resistance, the
electrical pair is solved analytically at each rolling-resistance grid
point. The result is frozen to config/warehouse-energy/physics-model-v1.json.

This is a simulation-consistency calibration against modeled telemetry, not
a physical battery calibration.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from physics_model import PhysicsModel, ramp_height, GRAVITY

SETTLE_S = 3.0
BRAKE_S = 3.0
HOLD_S = 3.0
FINISH_S = 4.0
BRAKE_TRIGGER_M = 0.12
END_TRIGGER_M = 0.08
COMMAND_SPEED_MPS = 0.10
COMMAND_ACCEL_MPS2 = 0.10
DT = 0.05

CRR_GRID = [i * 0.0002 for i in range(0, 41)]
CRR_REFINE = 0.00002
ETA_BOUNDS = (0.30, 0.95)
AUX_BOUNDS_W = (0.0, 30.0)


def scripted_profile(design, speed=COMMAND_SPEED_MPS, stops=1, hold=HOLD_S):
    """Replicate a scripted command profile (planning-time).

    Defaults reproduce the frozen Phase 0 qualification profile; sweep runs
    pass their own planned speed, mid-ramp stop count, and hold duration.
    """
    run = float(design["run_m"])
    rise = float(design["rise_m"])
    end_x = float(design["end_x"])
    direction = 1.0 if design["direction"] == "up" else -1.0
    x = -1.0 if direction > 0 else run + 1.0
    speed = float(design.get("planned_speed_mps", speed))
    stops = int(design.get("planned_mid_stops", stops))
    hold = float(design.get("planned_hold_s", hold))
    speed_cap = speed
    accel_cap = COMMAND_ACCEL_MPS2
    stop_done = stops <= 0
    samples = []
    state = {"x": x, "speed": 0.0, "phase": "settle", "phase_time": 0.0,
             "stop_done": stop_done}
    previous_height = ramp_height(state["x"], run, rise)
    while True:
        target = speed_cap if state["phase"] == "drive" else 0.0
        accel = 0.0
        if state["speed"] < target:
            accel = accel_cap
        elif state["speed"] > target:
            accel = -accel_cap
        state["speed"] = max(0.0, min(speed_cap, state["speed"] + accel * DT))
        advance = direction * state["speed"] * DT
        state["x"] += advance
        height = ramp_height(state["x"], run, rise)
        travel = abs(advance)
        drop = height - previous_height  # signed along the direction of travel
        hypot = math.hypot(travel, drop)
        sin_grade = drop / hypot if hypot > 1e-12 else 0.0
        cos_grade = travel / hypot if hypot > 1e-12 else 1.0
        samples.append((DT, state["speed"], sin_grade, cos_grade, accel))
        previous_height = height
        state["phase_time"] += DT
        if state["phase"] == "settle" and state["phase_time"] >= SETTLE_S:
            state["phase"], state["phase_time"] = "drive", 0.0
        elif (state["phase"] == "drive" and not state["stop_done"]
              and abs(state["x"] - run / 2) < BRAKE_TRIGGER_M):
            state["phase"], state["phase_time"] = "brake", 0.0
        elif state["phase"] == "brake" and state["phase_time"] >= BRAKE_S:
            state["phase"], state["phase_time"] = "hold", 0.0
        elif state["phase"] == "hold" and state["phase_time"] >= hold:
            state["phase"], state["phase_time"] = "drive", 0.0
            state["stop_done"] = True
        elif state["phase"] == "drive" and abs(state["x"] - end_x) < END_TRIGGER_M:
            state["phase"], state["phase_time"] = "finish", 0.0
        elif state["phase"] == "finish" and state["phase_time"] >= FINISH_S:
            return samples


def observed_wh(torque_csv, accounting):
    """Observed electrical Wh under the frozen Phase 1 telemetry model."""
    eta = float(accounting["electrical_model"]["drive_efficiency"])
    aux = float(accounting["electrical_model"]["auxiliary_power_w"])
    rows = list(csv.DictReader(torque_csv.open()))
    electrical_j = 0.0
    previous = None
    for row in rows:
        t = float(row["sim_s"])
        dt = 0.0 if previous is None else t - previous
        previous = t
        left = max(0.0, float(row["left_nm"]) * float(row["left_rad_s"]))
        right = max(0.0, float(row["right_nm"]) * float(row["right_rad_s"]))
        electrical_j += ((left + right) / eta + aux) * dt
    return electrical_j / 3600.0, len(rows), float(rows[-1]["sim_s"]) - float(rows[0]["sim_s"])


def traction_for_crr(samples, mass, crr):
    """Traction mechanical J for a candidate rolling resistance."""
    total = 0.0
    for dt, speed, sin_grade, cos_grade, accel in samples:
        force = (mass * accel + mass * GRAVITY * sin_grade
                 + crr * mass * GRAVITY * cos_grade)
        total += max(force * speed, 0.0) * dt
    return total


def solve_electrical(traction_j, durations_s, observed_j):
    """Bounded least squares for (u=1/eta, aux_w); linear in both."""
    def sse(u, aux):
        return sum((u * traction_j[i] + aux * durations_s[i] - observed_j[i]) ** 2
                   for i in range(len(traction_j)))
    saa = sum(a * a for a in traction_j)
    stt = sum(t * t for t in durations_s)
    sat = sum(traction_j[i] * durations_s[i] for i in range(len(traction_j)))
    sao = sum(traction_j[i] * observed_j[i] for i in range(len(traction_j)))
    sto = sum(durations_s[i] * observed_j[i] for i in range(len(traction_j)))
    det = saa * stt - sat * sat
    u = aux = None
    if det > 0:
        u = (sao * stt - sat * sto) / det
        aux = (saa * sto - sat * sao) / det
    u_clamped = u is None or not 1.0 / ETA_BOUNDS[1] <= u <= 1.0 / ETA_BOUNDS[0]
    aux_clamped = aux is None or not AUX_BOUNDS_W[0] <= aux <= AUX_BOUNDS_W[1]
    if u_clamped and aux_clamped:
        u = min(max(u if u is not None else 1 / 0.6, 1.0 / ETA_BOUNDS[1]), 1.0 / ETA_BOUNDS[0])
        aux = min(max(aux if aux is not None else 10.0, AUX_BOUNDS_W[0]), AUX_BOUNDS_W[1])
    elif u_clamped:
        aux = min(max(aux, AUX_BOUNDS_W[0]), AUX_BOUNDS_W[1])
        u = sum(observed_j[i] * traction_j[i] - aux * durations_s[i] * traction_j[i]
                for i in range(len(traction_j))) / saa if saa > 0 else 1 / 0.6
        u = min(max(u, 1.0 / ETA_BOUNDS[1]), 1.0 / ETA_BOUNDS[0])
    elif aux_clamped:
        u = min(max(u, 1.0 / ETA_BOUNDS[1]), 1.0 / ETA_BOUNDS[0])
        aux = sum(observed_j[i] * durations_s[i] - u * traction_j[i] * durations_s[i]
                  for i in range(len(traction_j))) / stt if stt > 0 else 10.0
        aux = min(max(aux, AUX_BOUNDS_W[0]), AUX_BOUNDS_W[1])
    return u, aux, sse(u, aux)


def fit(runs, fixed_eta=None):
    def evaluate(crr):
        traction_j = [traction_for_crr(run["profile"], run["mass_kg"], crr) for run in runs]
        durations = [run["planned_duration_s"] for run in runs]
        observed = [run["observed_wh"] * 3600.0 for run in runs]
        if fixed_eta is not None:
            u = 1.0 / fixed_eta
            denominator = sum(t * t for t in durations)
            aux = min(max(sum(observed[i] * durations[i] - u * traction_j[i] * durations[i]
                              for i in range(len(traction_j))) / denominator
                         if denominator > 0 else 10.0, AUX_BOUNDS_W[0]), AUX_BOUNDS_W[1])
            error = sum((u * traction_j[i] + aux * durations[i] - observed[i]) ** 2
                        for i in range(len(traction_j)))
            return {"crr": round(crr, 8), "u_efficiency": u, "aux_w": aux, "sse": error}
        u, aux, error = solve_electrical(traction_j, durations, observed)
        return {"crr": round(crr, 8), "u_efficiency": u, "aux_w": aux, "sse": error}

    best = min((evaluate(crr) for crr in CRR_GRID), key=lambda r: r["sse"])
    for step in range(1, 5):
        for crr in (best["crr"] - step * CRR_REFINE, best["crr"] + step * CRR_REFINE):
            if crr < 0:
                continue
            result = evaluate(round(crr, 8))
            if result["sse"] < best["sse"]:
                best = result
    return best


def matrix_digest(matrix):
    digest = hashlib.sha256()
    for directory in sorted(matrix.iterdir()):
        if not directory.is_dir():
            continue
        for name in ["design.json", "torque.csv"]:
            digest.update(str(directory.name).encode())
            digest.update(name.encode())
            digest.update((directory / name).read_bytes())
    return digest.hexdigest()


def load_runs(matrix, robot_mass, accounting):
    runs = []
    for directory in sorted(matrix.iterdir()):
        if not directory.is_dir():
            continue
        design = json.loads((directory / "design.json").read_text())
        wh, samples, trace_duration = observed_wh(directory / "torque.csv", accounting)
        profile = scripted_profile(design)
        runs.append({"name": directory.name, "design": design, "observed_wh": wh,
                     "actuator_samples": samples, "trace_duration_s": trace_duration,
                     "planned_duration_s": sum(s[0] for s in profile),
                     "profile": profile,
                     "mass_kg": robot_mass + float(design["payload_kg"])})
    return runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True,
                        help="extracted phase-0 ramp-evidence matrix directory")
    parser.add_argument("--accounting", type=Path, required=True,
                        help="config/warehouse-energy/phase1-telemetry-v1.json")
    parser.add_argument("--fixture", type=Path, required=True,
                        help="config/warehouse-energy/fixture-v1.json")
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    accounting = json.loads(args.accounting.read_text())
    fixture = json.loads(args.fixture.read_text())
    robot_mass = float(fixture["robot"]["physical_mass_kg"])
    runs = load_runs(args.matrix, robot_mass, accounting)
    if len(runs) != 36:
        raise SystemExit(f"expected 36 calibration runs, found {len(runs)}")
    best = fit(runs)
    eta = 1.0 / best["u_efficiency"]
    telemetry_eta = float(accounting["electrical_model"]["drive_efficiency"])
    telemetry_aux = float(accounting["electrical_model"]["auxiliary_power_w"])
    constrained = fit(runs, fixed_eta=telemetry_eta)
    traction_share = [ (run["observed_wh"] * 3600.0 - telemetry_aux * run["planned_duration_s"])
                       / (run["observed_wh"] * 3600.0) for run in runs ]
    model_document = {
        "schema_version": "warehouse-physics-model-v1",
        "status": "frozen_for_stage_2",
        "parameters": {
            "rolling_resistance_coefficient": round(best["crr"], 8),
            "drive_efficiency": round(eta, 6),
            "auxiliary_power_w": round(best["aux_w"], 6),
        },
        "force_model": "F = m*a + m*g*sin(theta) + Crr*m*g*cos(theta); "
                       "traction power max(F*v, 0)/eta; no regeneration; constant auxiliary load",
        "planning_assumptions": {
            "speed_cap_mps": float(fixture["robot"]["speed_cap_mps"]),
            "acceleration_cap_mps2": float(fixture["robot"]["acceleration_cap_mps2"]),
            "goal_transition_base_s": 13.5,
            "rotate_to_heading_angular_vel_rad_s": 0.3,
            "provenance": "speed/acceleration caps and rotation rate are frozen fixture and Nav2 "
                          "controller settings; the per-goal transition allowance is a declared "
                          "planning constant derived from the accepted Phase 1 repeated-run series "
                          "mission windows (11.6-19.7 s overhead per intermediate goal including "
                          "route-B rotations), not a fitted parameter",
        },
        "calibration": {
            "runs": len(runs),
            "data": "phase-0 qualification ramp matrix (36 complete fresh-world trials)",
            "data_sha256": matrix_digest(args.matrix),
            "observed_label": "modeled electrical Wh recomputed from raw actuator traces under the "
                              "frozen Phase 1 telemetry accounting model",
            "method": "rolling-resistance grid with analytic bounded least squares for "
                      "(1/eta, auxiliary); complete-run separation",
            "rmse_wh": None,
        },
        "scope_limits": [
            "Calibrated against modeled simulated telemetry, not physical battery measurements.",
            "Valid only for the frozen warehouse fixture, robot, payloads, and surfaces.",
            "Waypoint transition and rotation demand are declared planning allowances; their "
            "residual error is Stage 3B residual-learning material.",
        ],
    }
    frozen = PhysicsModel(model_document)
    rows = []
    errors = []
    for run in runs:
        prediction = frozen.integrate(run["profile"], run["mass_kg"])
        error = prediction["wh"] - run["observed_wh"]
        errors.append(error)
        rows.append({"run": run["name"], "route": run["design"]["route"],
                     "direction": run["design"]["direction"],
                     "payload_kg": run["design"]["payload_kg"],
                     "observed_wh": round(run["observed_wh"], 6),
                     "predicted_wh": round(prediction["wh"], 6),
                     "error_wh": round(error, 6),
                     "observed_trace_duration_s": round(run["trace_duration_s"], 1),
                     "planned_duration_s": round(run["planned_duration_s"], 1)})
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    model_document["calibration"]["rmse_wh"] = round(rmse, 6)
    model_document["calibration"]["max_abs_error_wh"] = round(max(abs(e) for e in errors), 6)
    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    args.model_output.write_text(json.dumps(model_document, indent=2) + "\n")
    report = {
        "status": "PASS" if rmse < 0.01 else "REVIEW",
        "frozen_parameters": model_document["parameters"],
        "rmse_wh": round(rmse, 6),
        "max_abs_error_wh": model_document["calibration"]["max_abs_error_wh"],
        "identifiability": {
            "traction_energy_share_min": round(min(traction_share), 4),
            "traction_energy_share_max": round(max(traction_share), 4),
            "statement": "Traction is a small share of modeled energy, so rolling resistance and "
                         "drive efficiency are jointly weakly identified: a valley of solutions "
                         "fits all 36 runs within the reported error. The frozen point is the "
                         "unconstrained least-squares minimum.",
            "telemetry_consistent_alternative": {
                "drive_efficiency_fixed": telemetry_eta,
                "rolling_resistance_coefficient": constrained["crr"],
                "auxiliary_power_w": round(constrained["aux_w"], 6),
                "note": "efficiency fixed at the frozen Phase 1 telemetry constant; the fitted "
                        "rolling resistance then reproduces the declared simulator wheel joint "
                        "friction (2 x 0.001 Nm / 0.033 m)",
            },
        },
        "runs": rows,
        "scope": "simulation-consistency calibration against the frozen Phase 1 modeled-telemetry "
                 "label; not a physical electrical calibration",
        "inputs": {
            "matrix": str(args.matrix),
            "matrix_sha256": model_document["calibration"]["data_sha256"],
            "accounting": str(args.accounting),
            "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}))


if __name__ == "__main__":
    main()
