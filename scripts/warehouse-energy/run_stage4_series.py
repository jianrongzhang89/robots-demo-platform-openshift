#!/usr/bin/env python3
"""Execute the frozen Stage 4 trial order inside the pinned pod.

Runs each trial from the frozen order file, preserving every output
directory and continuing past failures (each failure is recorded and the
trial is reported by the analyzer). Designed to run detached.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order", type=Path, required=True)
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--speed", type=float, default=0.1)
    args = parser.parse_args()
    order = json.loads(args.order.read_text())
    args.series.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).parent
    summary = []
    for index, trial in enumerate(order):
        output = args.series / trial["name"]
        record = {"trial": trial["name"], "started": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                   time.gmtime())}
        if output.exists():
            record["status"] = "skipped_exists"
            summary.append(record)
            continue
        command = [sys.executable, str(root / "run_stage4_trial.py"),
                   "--source", str(args.source), "--fixture", str(args.fixture),
                   "--physics-model", str(args.physics_model),
                   "--release-dir", str(args.release_dir),
                   "--output", str(output), "--arm", trial["arm"],
                   "--mission", trial["kind"], "--payload", str(trial["payload"]),
                   "--direction", trial["direction"], "--speed", str(args.speed)]
        if trial["kind"].startswith("roundtrip"):
            command += ["--outbound-payload", "0.5", "--return-payload", "0.0"]
        if trial.get("serving_unavailable"):
            command += ["--serving-unavailable"]
        log = open(args.series / f"{trial['name']}.log", "w")
        try:
            code = subprocess.run(command, stdout=log,
                                  stderr=subprocess.STDOUT).returncode
            record["status"] = "ok" if code == 0 else f"exit_{code}"
        finally:
            log.close()
        record["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        summary.append(record)
        (args.series / "series-progress.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
    failures = [r for r in summary if r["status"] not in ("ok", "skipped_exists")]
    (args.series / "series-summary.json").write_text(json.dumps(
        {"trials": len(summary), "failures": failures}, indent=2) + "\n")
    print(json.dumps({"complete": True, "trials": len(summary),
                      "failures": len(failures)}))


if __name__ == "__main__":
    main()
