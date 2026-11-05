#!/usr/bin/env python3
"""Collect actual isolated costmap update records; never moves a robot.

The output directory must be new. Full records are gzip-compressed; summary
percentiles use unique applied request IDs, not repeated timer snapshots.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    offset = (len(values) - 1) * p / 100
    low = int(offset)
    return values[low] + (values[min(low+1, len(values)-1)] - values[low]) * (offset-low)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pod", default="semantic-phase4-inference")
    args = parser.parse_args()
    if not 10 <= args.duration <= 600:
        parser.error("duration must be 10..600 seconds")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    command = ["oc", "logs", "-n", "semantic-navigation", args.pod,
               "-c", "costmap-observer", "--follow", "--tail=0", "--timestamps"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pending = queue.Queue()
    def read():
        for line in process.stdout:
            pending.put(line)
        pending.put(None)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    rows, messages = [], []
    started = None
    warm_deadline = time.monotonic() + 180
    next_progress = time.monotonic() + 30
    try:
        while True:
            now = time.monotonic()
            if started is not None and now - started >= args.duration:
                break
            if started is None and now > warm_deadline:
                raise TimeoutError("No qualified live output in 180 seconds")
            if now > next_progress:
                print(json.dumps({"event": "progress", "records": len(rows),
                                  "elapsed_s": now-started if started else None}), flush=True)
                next_progress = now+30
            try:
                line = pending.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError("costmap log stream ended")
            try:
                timestamp, text = line.split(" ", 1)
                row = json.loads(text)
                if "maps" not in row:
                    raise ValueError("not costmap diagnostic")
            except (ValueError, TypeError):
                messages.append(line.strip())
                continue
            if started is None:
                if not all(v["last"] and "costmap_wall_ns" in v["last"] for v in row["maps"].values()):
                    continue
                started = time.monotonic()
                print(json.dumps({"event": "measurement_started", "timestamp": timestamp}), flush=True)
            row["log_timestamp"] = timestamp
            rows.append(row)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        with gzip.open(args.output_dir / "updates.jsonl.gz", "wt") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        (args.output_dir / "messages.json").write_text(json.dumps(messages, indent=2)+"\n")
    duration = time.monotonic() - started
    summary = {"collected_at": dt.datetime.now(dt.timezone.utc).isoformat(), "duration_s": duration,
               "records": len(rows), "period_ms": {"p95": percentile([r["period_ms"] for r in rows],95),
               "max": max(r["period_ms"] for r in rows)}, "maps": {}}
    for name in ("global_semantic", "local_semantic"):
        maps = [row["maps"][name] for row in rows]
        unique = {value["last"]["request_id"]: value["last"] for value in maps
                  if value["last"] and "costmap_wall_ns" in value["last"]}
        ages = [value["capture_to_costmap_upper_ms"] for value in unique.values()]
        summary["maps"][name] = {
            "applied_unique": len(unique), "applied_rate_hz": len(unique)/duration,
            "capture_to_costmap_ms": {"p50": percentile(ages,50), "p95": percentile(ages,95), "max": max(ages) if ages else None},
            "accepted_delta": maps[-1]["accepted"]-maps[0]["accepted"],
            "rejected_delta": maps[-1]["rejected"]-maps[0]["rejected"],
            "evicted_delta": maps[-1]["evicted"]-maps[0]["evicted"],
            "marked_cells_min": min(m["marked_cells"] for m in maps),
            "marked_cells_max": max(m["marked_cells"] for m in maps),
            "pending_max": max(m["pending"] for m in maps),
            "cells_max": max(m["cells"] for m in maps),
            "not_current_updates": sum(not m["current"] for m in maps),
            "epoch_changes": maps[-1]["epoch"]-maps[0]["epoch"],
            "update_ms_p95": percentile([m["update_ms"] for m in maps],95),
        }
    raw = args.output_dir / "updates.jsonl.gz"
    summary["raw_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
    # This tool assesses nominal timing only, never the whole Phase 4 gate.
    summary["nominal_timing_pass"] = all(m["applied_unique"] > 0 and m["capture_to_costmap_ms"]["p95"] <= 300
                                          for m in summary["maps"].values())
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
