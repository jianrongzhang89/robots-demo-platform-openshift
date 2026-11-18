#!/usr/bin/env python3
"""Run one Stage 2 physics-routing trial through the full RMF/Nav2 stack.

The route selector runs first, at planning time, before any world or
process starts. A feasible selection generates the selected corridor's
world and dispatches the same ordered RMF compose task used by the
accepted Phase 0/1 navigation trials; an infeasible selection records the
rejection and exits without motion. After a completed trial the mission
window (first Nav2 goal submission through task completion) is reconciled
against the raw modeled-energy trace so predicted and observed Wh share
one boundary.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from build_navigation import generate
from physics_model import PhysicsModel
import route_selector


def observe_mission_window(output):
    """Observed mission Wh/SOC/duration from raw traces (dispatch to completion)."""
    events = [json.loads(line) for line in (output / "adapter-events.jsonl").open()]
    physical = [json.loads(line) for line in (output / "physical.jsonl").open()]
    energy = list(csv.DictReader((output / "energy.csv").open()))
    goals = [e for e in events if e["event"] == "rmf_navigation"]
    if not goals or not physical or not energy:
        raise RuntimeError("missing mission evidence")
    dispatch_wall = goals[0]["wall_time"]
    mapping = [(row["wall_time"], row["sim_s"]) for row in physical]
    start_sim = min(mapping, key=lambda m: abs(m[0] - dispatch_wall))[1]
    end_sim = physical[-1]["sim_s"]

    def row_at(target):
        return min(energy, key=lambda row: abs(float(row["sim_s"]) - target))

    start_row, end_row = row_at(start_sim), row_at(end_sim)
    traction_j = 0.0
    previous = None
    for row in energy:
        t = float(row["sim_s"])
        dt = 0.0 if previous is None else t - previous
        if start_sim <= t <= end_sim and previous is not None and previous >= start_sim:
            traction_j += (float(row["left_mech_w"]) + float(row["right_mech_w"])) * dt
        previous = t
    return {
        "mission_window_sim_s": [round(start_sim, 3), round(end_sim, 3)],
        "observed_duration_s": round(end_sim - start_sim, 1),
        "observed_mission_wh": round(float(end_row["cumulative_wh"])
                                     - float(start_row["cumulative_wh"]), 6),
        "observed_mission_traction_j": round(traction_j, 3),
        "observed_final_soc": float(end_row["soc_fraction"]),
        "nav2_goal_submissions": len(goals),
    }


def run(args):
    root = Path(__file__).parent
    args.output = args.output.resolve()
    if args.output.exists():
        raise RuntimeError("preserve old trial: output exists")
    fixture = json.loads(args.fixture.read_text())
    model = PhysicsModel.load(args.physics_model)
    decision = route_selector.select(model, fixture, args.arm, args.payload,
                                     args.initial_soc, tuple(args.exclude_route))
    decision["fixture_sha256"] = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
    decision["physics_model_sha256"] = hashlib.sha256(args.physics_model.read_bytes()).hexdigest()
    decision["scope"] = ("planning-time selection over the frozen simulation fixture using the "
                         "calibrated physics model; not a physical energy measurement")
    args.output.mkdir(parents=True)
    (args.output / "route-selection.json").write_text(json.dumps(decision, indent=2) + "\n")
    if decision["status"] != "SELECTED":
        result = {"status": "REJECTED", "selection": decision,
                  "rejection_reason": decision["rejection_reason"],
                  "motion_started": False,
                  "scope": "planning-time feasibility gate; no task was dispatched"}
        (args.output / "stage2-result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return 0

    route = decision["selected_route"]
    generate(args.source, args.fixture, args.output, route, args.direction, args.payload,
             args.rtf, args.camera_width, args.camera_height, False)
    files = [p for p in root.iterdir() if p.suffix in ['.py', '.cc', '.xml']]
    files.extend([args.source, args.fixture, args.physics_model,
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
                               timeout=1200)
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
    observation = observe_mission_window(args.output)
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
        "selected_route": route,
        "selection": decision,
        "trial_status": trial_result.get("status"),
        "task_id": trial_result.get("task_id"),
        "prediction": {
            "predicted_mission_wh": predicted_wh,
            "predicted_duration_s": estimate["predicted_duration_s"],
            "predicted_final_soc": estimate["predicted_final_soc"],
        },
        "observation": observation,
        "prediction_error_wh": prediction_error_wh,
        "prediction_error_fraction": round(prediction_error_wh / observation["observed_mission_wh"], 4),
        "telemetry_model": ("frozen Phase 1 accounting (drive efficiency "
                            f"{energy['sensitivity_only']['efficiency'][1]}, auxiliary "
                            f"{energy['sensitivity_only']['auxiliary_w'][1]} W); the Stage 2 "
                            "physics model is a separate planning estimator"),
        "scope": "physics routing and modeled-energy comparison in simulation; no physical "
                 "battery calibration or energy-saving claim",
    }
    (args.output / "stage2-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--physics-model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arm', choices=['A', 'B'], required=True)
    parser.add_argument('--payload', type=float, default=.5)
    parser.add_argument('--initial-soc', type=float, default=.8)
    parser.add_argument('--exclude-route', action='append', default=[])
    parser.add_argument('--direction', choices=['up', 'down'], default='up')
    parser.add_argument('--rtf', type=float, default=3)
    parser.add_argument('--camera-width', type=int, default=320)
    parser.add_argument('--camera-height', type=int, default=240)
    raise SystemExit(run(parser.parse_args()))
