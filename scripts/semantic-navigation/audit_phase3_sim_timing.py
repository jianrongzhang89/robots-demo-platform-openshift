#!/usr/bin/env python3
"""Read Gazebo world statistics, retaining RTF samples without changing the sim."""
import argparse
import json
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--output", help="Write full sample array to a NEW file")
    args = parser.parse_args()
    started = time.time_ns()
    process = subprocess.Popen(["gz", "topic", "-e", "-t", "/world/sim_world/stats"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        output, error = process.communicate(timeout=args.duration)
    except subprocess.TimeoutExpired:
        process.terminate()
        output, error = process.communicate(timeout=5)
    values = [float(line.split(":", 1)[1]) for line in output.splitlines()
              if line.startswith("real_time_factor:")]
    if not values:
        raise RuntimeError(f"no RTF samples: {error}")
    report = {"kind": "gazebo_rtf", "topic": "/world/sim_world/stats",
        "started_wall_ns": started, "finished_wall_ns": time.time_ns(),
        "samples": values, "min": min(values), "max": max(values),
        "mean": sum(values)/len(values)}
    if args.output:
        with open(args.output, "x") as handle:
            json.dump(report, handle, sort_keys=True)
        print(json.dumps({**{k:v for k,v in report.items() if k != "samples"},
                          "sample_count": len(values), "evidence_file": args.output}))
    else:
        print(json.dumps(report))


if __name__ == "__main__":
    main()
