#!/usr/bin/env python3
"""Capture a stopped frame using the current Gazebo robot_1 world pose."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path


def parse_gazebo_pose(payload: str) -> list[float]:
    message = json.loads(payload)
    pose = next((item for item in message.get("pose", [])
                 if item.get("name") == "robot_1"), None)
    if pose is None:
        raise ValueError("Gazebo pose/info did not contain robot_1")
    position = pose["position"]
    orientation = pose["orientation"]
    values = [position[axis] for axis in ("x", "y", "z")] + [
        orientation[axis] for axis in ("x", "y", "z", "w")
    ]
    values = [float(value) for value in values]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Gazebo pose contains a non-finite value")
    quaternion_norm = math.sqrt(sum(value * value for value in values[3:]))
    if not 0.99 <= quaternion_norm <= 1.01:
        raise ValueError(f"Gazebo pose quaternion norm is {quaternion_norm:.6f}, expected ~1")
    return values


def gazebo_pose(attempts: int = 3) -> list[float]:
    command = ["gz", "topic", "-e", "-t", "/world/sim_world/pose/info",
               "-n", "1", "--json-output"]
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=10, check=False)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()[-500:]
                raise RuntimeError(f"gz topic exited {result.returncode}: {detail}")
            return parse_gazebo_pose(result.stdout)
        except (subprocess.TimeoutExpired, OSError, RuntimeError, ValueError,
                json.JSONDecodeError, KeyError, TypeError) as error:
            errors.append(f"attempt {attempt}/{attempts}: {error}")
            if attempt < attempts:
                time.sleep(0.25 * attempt)
    raise RuntimeError("unable to read a valid robot_1 Gazebo pose; " + "; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-script", type=Path,
                        default=Path("/opt/semantic-navigation/capture_camera_frames.py"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--label", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not args.capture_script.is_file():
        parser.error(f"capture script does not exist: {args.capture_script}")
    pose = gazebo_pose()
    command = [
        sys.executable, str(args.capture_script),
        "--output", str(args.output), "--count", str(args.count),
        "--label", args.label, "--timeout", str(args.timeout),
        "--world-from-base-link", *(str(value) for value in pose),
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
