#!/usr/bin/env python3
"""Stage 3A navigation-profile dataset trial with a forced corridor.

Runs the full RMF/Nav2/Gazebo stack exactly like the Phase 0/1 navigation
trials, but forces the swept route, direction, payload, and planned speed
so the dataset covers both ramps rather than only the preferred route.
Evidence and auditing are identical to run_navigation.py; the design file
records the sweep conditions for the dataset builder.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from build_navigation import generate


def run(args):
    root = Path(__file__).parent
    args.output = args.output.resolve()
    if args.output.exists():
        raise RuntimeError('preserve old trial: output exists')
    generate(args.source, args.fixture, args.output, args.route, args.direction, args.payload,
             args.rtf, args.camera_width, args.camera_height, False, args.speed)
    design = json.loads((args.output / 'design.json').read_text())
    design['class'] = 'nav'
    (args.output / 'design.json').write_text(json.dumps(design, indent=2) + '\n')
    files = [p for p in root.iterdir() if p.suffix in ['.py', '.cc', '.xml']]
    files.extend([args.source, args.fixture, Path('/work/libWarehouseTelemetry.so'),
                  Path('/work/scripts/local_nav2_fleet_adapter.py')])
    (args.output / 'source-sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files}, indent=2) + '\n')
    x, y, z, yaw = design['start']
    energy = design['source_fixture']['energy']
    env = dict(os.environ, WAREHOUSE_RUN_DIR=str(args.output),
        WAREHOUSE_TORQUE_TRACE=str(args.output / 'torque.csv'),
        WAREHOUSE_ENERGY_TRACE=str(args.output / 'energy.csv'),
        WAREHOUSE_INITIAL_SOC=str(energy['initial_soc']),
        WAREHOUSE_BATTERY_CAPACITY_WH=str(energy['nominal_battery_wh']),
        WAREHOUSE_DRIVE_EFFICIENCY=str(energy['sensitivity_only']['efficiency'][1]),
        WAREHOUSE_AUXILIARY_W=str(energy['sensitivity_only']['auxiliary_w'][1]),
        GZ_PARTITION='warehouse_navigation_trial', ROS_DOMAIN_ID='85',
        ROS_LOG_DIR=str(args.output / 'ros-logs'))
    processes = []; logs = []

    def start(name, command):
        log = open(args.output / f'{name}.log', 'w'); logs.append(log)
        p = subprocess.Popen(command, env=env, cwd=args.output, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(p); return p
    try:
        start('gazebo', ['gz', 'sim', '-s', '-r', str(args.output / 'world.sdf')])
        start('bridge', [sys.executable, str(root / 'navigation_bridge.py')])
        time.sleep(2)
        start('nav2', ['ros2', 'launch', str(root / 'navigation.launch.py')])
        time.sleep(5)
        start('rgbd-bridge', ['ros2', 'launch', 'ros_gz_bridge', 'ros_gz_bridge.launch.py',
            'bridge_name:=warehouse_rgbd_bridge', f'config_file:={root / "rgbd-bridge.yaml"}'])
        start('schedule', ['ros2', 'run', 'rmf_traffic_ros2', 'rmf_traffic_schedule',
                           '--ros-args', '-p', 'use_sim_time:=true'])
        start('dispatcher', ['ros2', 'run', 'rmf_task_ros2', 'rmf_task_dispatcher', '--ros-args',
                             '-p', 'use_sim_time:=true', '-p', 'bidding_time_window:=2.0',
                             '-p', 'use_unique_hex_string_with_task_id:=true'])
        time.sleep(3)
        start('adapter', [sys.executable, str(root / 'warehouse_adapter.py'), '--fleet-config',
            str(args.output / 'fleet.yaml'), '--nav-graph', str(args.output / 'graph.yaml'),
            '--initial-map', 'warehouse', '--initial-x', str(x), '--initial-y', str(y),
            '--initial-yaw', str(yaw), '--ros-namespace', ''])
        trial = subprocess.run([sys.executable, str(root / 'navigation_trial.py')], env=env,
                               timeout=1500)
        return trial.returncode
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--route', choices=['A', 'B'], required=True)
    parser.add_argument('--direction', choices=['up', 'down'], required=True)
    parser.add_argument('--payload', type=float, default=.5)
    parser.add_argument('--speed', type=float, default=.1)
    parser.add_argument('--rtf', type=float, default=3)
    parser.add_argument('--camera-width', type=int, default=320)
    parser.add_argument('--camera-height', type=int, default=240)
    raise SystemExit(run(parser.parse_args()))
