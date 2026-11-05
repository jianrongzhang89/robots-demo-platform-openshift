#!/usr/bin/env python3
"""Read-only resource sampling of the fixed private Phase 4 workloads."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 10 <= args.duration <= 600:
        parser.error("new output path and duration 10..600 required")
    started = time.monotonic()
    rows = []
    base = ["oc", "-n", "semantic-navigation"]
    commands = {
        "top": base + ["adm", "top", "pods", "--containers"],
        "costmap_processes": base + ["exec", "semantic-phase4-inference", "-c", "costmap-observer", "--", "ps", "-eo", "pid,rss,comm"],
        "inference_processes": base + ["exec", "semantic-phase4-inference", "-c", "sam3-inference", "--", "ps", "-eo", "pid,rss,comm"],
        "gpu": base + ["exec", "semantic-phase4-inference", "-c", "sam3-inference", "--", "nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
    }
    while time.monotonic() - started < args.duration:
        row = {"elapsed_s":time.monotonic()-started, "client_wall_ns":time.time_ns()}
        for name, command in commands.items():
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            output = result.stdout
            if name == "top":
                output = "\n".join(line for line in output.splitlines() if "semantic-phase4-" in line)
            row[name] = {"output":output,"stderr":result.stderr,"exit_code":result.returncode}
        rows.append(row)
        print(json.dumps({"event":"resource_sample","elapsed_s":row["elapsed_s"]}), flush=True)
        time.sleep(min(20,max(0,args.duration-(time.monotonic()-started))))
    with args.output.open("x") as handle:
        json.dump({"duration_s":time.monotonic()-started,"samples":rows},handle,indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
