#!/usr/bin/env python3
"""Run one Stage 4 comparative-demonstration mission (arm A, B, or C).

Arm A selects by shortest feasible distance (energy logged only). Arm B
selects by minimum predicted mission energy with the calibrated physics
estimator. Arm C selects with the qualified serving endpoint
(physics-plus-XGBoost) and its documented fallback. Round-trip missions
plan both legs plus charger access as one decision and execute one leg
per invocation. The selection record is the operator view: per-route
estimates, uncertainty, feasibility, chosen corridor, model identity.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from build_navigation import generate
from physics_model import PhysicsModel
import route_selector

ROOT = Path(__file__).resolve().parents[2]


def observe_mission_window_arrival(output, end_node_xy):
    """Mission window on the model's label convention: dispatch through
    final waypoint arrival (the Stage 2 convention additionally counted
    post-arrival teardown idle, which is not part of the mission)."""
    events = [json.loads(line) for line in (output / "adapter-events.jsonl").open()]
    physical = [json.loads(line) for line in (output / "physical.jsonl").open()]
    energy = list(csv.DictReader((output / "energy.csv").open()))
    goals = [e for e in events if e["event"] == "rmf_navigation"]
    if not goals or not physical or not energy:
        raise RuntimeError("missing mission evidence")
    mapping = [(row["wall_time"], row["sim_s"]) for row in physical]
    start_sim = min(mapping, key=lambda m: abs(m[0] - goals[0]["wall_time"]))[1]
    arrival = next((row["sim_s"] for row in physical
                    if row["sim_s"] >= start_sim
                    and math.hypot(row["x"] - end_node_xy[0], row["y"] - end_node_xy[1]) < 0.20),
                   None)
    if arrival is None:
        raise RuntimeError("final waypoint arrival not observed")
    end_sim = physical[-1]["sim_s"]

    def row_at(target):
        return min(energy, key=lambda row: abs(float(row["sim_s"]) - target))

    start_row, arrival_row, end_row = row_at(start_sim), row_at(arrival), row_at(end_sim)
    traction_j = 0.0
    previous = None
    for row in energy:
        t = float(row["sim_s"])
        dt = 0.0 if previous is None else t - previous
        if start_sim <= t <= arrival and previous is not None and previous >= start_sim:
            traction_j += (float(row["left_mech_w"]) + float(row["right_mech_w"])) * dt
        previous = t
    return {
        "mission_window_sim_s": [round(start_sim, 3), round(arrival, 3)],
        "observed_duration_s": round(arrival - start_sim, 1),
        "observed_mission_wh": round(float(arrival_row["cumulative_wh"])
                                     - float(start_row["cumulative_wh"]), 6),
        "post_arrival_idle_wh": round(float(end_row["cumulative_wh"])
                                      - float(arrival_row["cumulative_wh"]), 6),
        "observed_mission_traction_j": round(traction_j, 3),
        "observed_final_soc": float(end_row["soc_fraction"]),
        "nav2_goal_submissions": len(goals),
    }


def build_client(args, release, predictor):
    from energy_serving_client import EnergyServingClient
    frozen = release["frozen"]
    endpoint = ("https://192.0.2.1:8443" if args.serving_unavailable
                else args.serving_endpoint)
    return EnergyServingClient(
        endpoint, args.tls_cert, args.tls_key, args.tls_ca,
        {"model_name": "energy-predictor-v1",
         "frozen_sha256": release["frozen_sha256"],
         "xgb_model_sha256": frozen["xgb_model_sha256"],
         "physics_model_sha256": hashlib.sha256(
             args.physics_model.read_bytes()).hexdigest()},
        predictor.derive,
        fallback_allowance_wh=frozen["uncertainty_calibration"]["allowance_physics_fallback_wh"],
        learned_allowance_wh=frozen["uncertainty_calibration"]["allowance_learned_wh"])


def run(args):
    root = Path(__file__).parent
    args.output = args.output.resolve()
    if args.output.exists():
        raise RuntimeError("preserve old trial: output exists")
    fixture = json.loads(args.fixture.read_text())
    model = PhysicsModel.load(args.physics_model)
    release = json.loads((args.release_dir / "release.json").read_text())
    frozen = release["frozen"]
    physics_allowance = frozen["uncertainty_calibration"]["allowance_physics_fallback_wh"]

    sys.path.insert(0, str(ROOT / "apps/energy-predictor"))
    import predictor as predictor_module
    predictor = predictor_module.EnergyPredictor(
        args.release_dir, args.physics_model,
        ROOT / "apps/energy-predictor/model-manifest.json", xgboost_module=None)

    estimator = None
    serving = {"mode": "not_used", "endpoint": None}
    if args.arm == "C":
        client = build_client(args, release, predictor)
        estimator = route_selector.ServedEstimator(client, fixture)
        serving = {"mode": "unavailable_fallback" if args.serving_unavailable else "served",
                   "endpoint": "https://192.0.2.1:8443" if args.serving_unavailable
                   else args.serving_endpoint,
                   "model_version": "energy-predictor-v1",
                   "frozen_sha256": release["frozen_sha256"]}

    round_trip = args.mission in ("roundtrip-out", "roundtrip-return")
    if round_trip and args.outbound_payload is None:
        raise ValueError("--outbound-payload is required for round-trip missions")
    planning_payload = args.outbound_payload if round_trip else args.payload
    decision = route_selector.select_stage4(
        model, fixture, args.arm, planning_payload, args.initial_soc,
        tuple(args.exclude_route), "up" if round_trip else args.direction, estimator,
        round_trip_return_payload_kg=(args.return_payload if round_trip else None),
        physics_allowance_wh=physics_allowance)
    decision.update({
        "mission": args.mission,
        "operator_view": {
            "warehouse": "frozen warehouse fixture v1",
            "candidate_routes": {name: {
                "distance_m": row["distance_m"],
                "predicted_mission_wh": row["predicted_mission_wh"],
                "predicted_duration_s": row["predicted_duration_s"],
                "round_trip_predicted_total_wh": row["round_trip_predicted_total_wh"],
                "uncertainty_allowance_wh": row["uncertainty_allowance_wh"],
                "predicted_final_soc": row["predicted_final_soc"],
                "feasible": row["feasible"], "estimator_mode": row["estimator_mode"]}
                for name, row in decision["routes"].items()},
            "battery_reserve_minimum": fixture["energy"]["minimum_soc_after_mission_and_charger"],
            "deadline_one_way_s": fixture["energy"]["deadline_one_way_s"],
            "selected_route": decision.get("selected_route"),
            "arm": args.arm,
            "serving": serving,
        },
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "scope": "Stage 4 comparative demonstration selection; modeled energy only",
    })
    args.output.mkdir(parents=True)
    (args.output / "route-selection.json").write_text(json.dumps(decision, indent=2) + "\n")
    if decision["status"] != "SELECTED":
        result = {"status": "REJECTED", "selection": decision,
                  "rejection_reason": decision["rejection_reason"],
                  "motion_started": False,
                  "scope": "planning-time feasibility gate; no task was dispatched"}
        (args.output / "stage4-result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return 0

    route = decision["selected_route"]
    generate(args.source, args.fixture, args.output, route, args.direction, args.payload,
             args.rtf, args.camera_width, args.camera_height, False, args.speed)
    files = [p for p in root.iterdir() if p.suffix in ['.py', '.cc', '.xml']]
    files.extend([args.source, args.fixture, args.physics_model, args.release_dir / "release.json",
                  Path('/work/libWarehouseTelemetry.so'), Path('/work/scripts/local_nav2_fleet_adapter.py')])
    (args.output / 'source-sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files}, indent=2) + '\n')
    design = json.loads((args.output / 'design.json').read_text())
    x, y, z, yaw = design['start']
    energy = design['source_fixture']['energy']
    env = dict(os.environ, WAREHOUSE_RUN_DIR=str(args.output), WAREHOUSE_TORQUE_TRACE=str(args.output/'torque.csv'),
        WAREHOUSE_ENERGY_TRACE=str(args.output/'energy.csv'),
        WAREHOUSE_INITIAL_SOC=str(energy['initial_soc']),
        WAREHOUSE_BATTERY_CAPACITY_WH=str(energy['nominal_battery_wh']),
        WAREHOUSE_DRIVE_EFFICIENCY=str(energy['sensitivity_only']['efficiency'][1]),
        WAREHOUSE_AUXILIARY_W=str(energy['sensitivity_only']['auxiliary_w'][1]),
        GZ_PARTITION='warehouse_navigation_trial', ROS_DOMAIN_ID='85',
        ROS_LOG_DIR=str(args.output/'ros-logs'))
    processes = []
    logs = []

    def start(name, command):
        log = open(args.output/f'{name}.log', 'w'); logs.append(log)
        p = subprocess.Popen(command, env=env, cwd=args.output, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(p); return p
    try:
        start('gazebo', ['gz', 'sim', '-s', '-r', str(args.output/'world.sdf')])
        start('bridge', [sys.executable, str(root/'navigation_bridge.py')])
        time.sleep(2)
        start('nav2', ['ros2', 'launch', str(root/'navigation.launch.py')])
        time.sleep(5)
        start('rgbd-bridge', ['ros2', 'launch', 'ros_gz_bridge', 'ros_gz_bridge.launch.py',
            'bridge_name:=warehouse_rgbd_bridge', f'config_file:={root / "rgbd-bridge.yaml"}'])
        start('schedule', ['ros2', 'run', 'rmf_traffic_ros2', 'rmf_traffic_schedule',
                           '--ros-args', '-p', 'use_sim_time:=true'])
        start('dispatcher', ['ros2', 'run', 'rmf_task_ros2', 'rmf_task_dispatcher', '--ros-args',
                             '-p', 'use_sim_time:=true', '-p', 'bidding_time_window:=2.0',
                             '-p', 'use_unique_hex_string_with_task_id:=true'])
        time.sleep(3)
        start('adapter', [sys.executable, str(root/'warehouse_adapter.py'), '--fleet-config',
            str(args.output/'fleet.yaml'), '--nav-graph', str(args.output/'graph.yaml'),
            '--initial-map', 'warehouse', '--initial-x', str(x), '--initial-y', str(y),
            '--initial-yaw', str(yaw), '--ros-namespace', ''])
        trial = subprocess.run([sys.executable, str(root/'navigation_trial.py')], env=env,
                               timeout=1500)
        trial_code = trial.returncode
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
        for log in logs:
            log.close()

    trial_result = json.loads((args.output / "result.json").read_text())
    end_node_xy = design["nodes"][design["path"][-1]][:2]
    observation = observe_mission_window_arrival(args.output, end_node_xy)
    estimate = decision["routes"][route]
    predicted_wh = estimate["predicted_mission_wh"]
    prediction_error_wh = round(observation["observed_mission_wh"] - predicted_wh, 6)
    reserve = float(fixture["energy"]["minimum_soc_after_mission_and_charger"])
    deadline = float(fixture["energy"]["deadline_one_way_s"])
    violations = []
    if trial_code != 0 or trial_result.get("status") != "PASS":
        violations.append("underlying navigation trial did not pass")
    if observation["observed_final_soc"] < reserve:
        violations.append(f"observed final SOC {observation['observed_final_soc']:.4f} below reserve")
    if observation["observed_duration_s"] > deadline:
        violations.append(f"observed duration {observation['observed_duration_s']}s exceeds deadline")
    result = {
        "status": "FAIL" if violations else "PASS",
        "errors": violations,
        "arm": args.arm,
        "mission": args.mission,
        "payload_kg": args.payload,
        "direction": args.direction,
        "selected_route": route,
        "selection": decision,
        "trial_status": trial_result.get("status"),
        "task_id": trial_result.get("task_id"),
        "prediction": {
            "predicted_mission_wh": predicted_wh,
            "predicted_duration_s": estimate["predicted_duration_s"],
            "predicted_final_soc": estimate["predicted_final_soc"],
            "estimator_mode": estimate["estimator_mode"],
            "uncertainty_allowance_wh": estimate["uncertainty_allowance_wh"],
        },
        "observation": observation,
        "prediction_error_wh": prediction_error_wh,
        "prediction_error_fraction": round(prediction_error_wh / observation["observed_mission_wh"], 4),
        "upper_estimate_wh": round(predicted_wh + estimate["uncertainty_allowance_wh"], 6),
        "upper_estimate_covers_observation": bool(
            observation["observed_mission_wh"]
            <= predicted_wh + estimate["uncertainty_allowance_wh"]),
        "serving": serving,
        "scope": "Stage 4 comparative demonstration; modeled energy only; "
                 "no physical calibration or energy-saving claim",
    }
    (args.output / "stage4-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["status", "arm", "mission", "selected_route",
                                             "prediction_error_wh"]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--physics-model', type=Path, required=True)
    parser.add_argument('--release-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arm', choices=['A', 'B', 'C'], required=True)
    parser.add_argument('--mission', choices=['oneway', 'roundtrip-out', 'roundtrip-return'],
                        default='oneway')
    parser.add_argument('--payload', type=float, default=.5,
                        help='physical payload for this leg')
    parser.add_argument('--outbound-payload', type=float, default=None,
                        help='round-trip planning payload for the outbound leg')
    parser.add_argument('--return-payload', type=float, default=0.0,
                        help='return-leg payload for round-trip planning')
    parser.add_argument('--initial-soc', type=float, default=.8)
    parser.add_argument('--direction', choices=['up', 'down'], default='up')
    parser.add_argument('--speed', type=float, default=.1)
    parser.add_argument('--rtf', type=float, default=3)
    parser.add_argument('--camera-width', type=int, default=320)
    parser.add_argument('--camera-height', type=int, default=240)
    parser.add_argument('--exclude-route', action='append', default=[])
    parser.add_argument('--serving-endpoint',
                        default='https://energy-predictor-v1-tls.semantic-model-serving.svc:8443')
    parser.add_argument('--tls-cert', type=Path, default=Path('/tls/tls.crt'))
    parser.add_argument('--tls-key', type=Path, default=Path('/tls/tls.key'))
    parser.add_argument('--tls-ca', type=Path, default=Path('/tls/client-ca.crt'))
    parser.add_argument('--serving-unavailable', action='store_true',
                        help='demonstrate the documented physics fallback (arm C)')
    raise SystemExit(run(parser.parse_args()))
