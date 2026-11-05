#!/usr/bin/env python3
"""Exercise only private Phase 4 clear/deactivate/pause/reset paths, with restoration.

Records every costmap update, including empty rasters and internal buffer counts.
Never calls a motion service or sends velocity commands.
"""
import argparse
import datetime as dt
import gzip
import json
from pathlib import Path
import queue
import shlex
import subprocess
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--inference-pod", default="semantic-phase4-inference")
    parser.add_argument("--simulator-pod", default="semantic-phase4-simulator")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    base = ["oc", "-n", "semantic-navigation"]
    process = subprocess.Popen(base + ["logs", args.inference_pod, "-c", "costmap-observer", "-f", "--tail=0", "--timestamps"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    events = queue.Queue()
    rows, actions = [], []
    latest = None
    def reader():
        for line in process.stdout:
            try:
                timestamp, text = line.split(" ", 1)
                row = json.loads(text)
                row["log_wall_ns"] = int(dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()*1e9)
                if "maps" in row:
                    events.put(row)
            except (ValueError, TypeError):
                pass
    threading.Thread(target=reader, daemon=True).start()
    def wait(predicate, timeout=45):
        nonlocal latest
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                latest = events.get(timeout=0.2)
            except queue.Empty:
                continue
            rows.append(latest)
            if predicate(latest):
                return latest
        raise AssertionError("costmap condition timed out")
    def healthy(row):
        return all(m["current"] for m in row["maps"].values()) and row["maps"]["global_semantic"]["marked_cells"] > 0
    def cleared(row):
        return all(m["marked_cells"] == 0 and m["cells"] == 0 for m in row["maps"].values())
    def service(name):
        command = base + ["exec", args.inference_pod, "-c", "costmap-observer", "--", "bash", "-lc",
            "python3 -c 'import time; print(time.time_ns(), flush=True)'; source /opt/semantic-costmap-ws/install/setup.bash; ros2 service call /phase4/" + name + " std_srvs/srv/Trigger '{}'" ]
        start = time.time_ns()
        result = subprocess.run(command, text=True, capture_output=True, timeout=30, check=True)
        assert "success=True" in result.stdout, result.stdout+result.stderr
        cluster_start = int(next(line for line in result.stdout.splitlines() if line.isdigit()))
        actions.append({"action":name,"client_start_wall_ns":start,"client_end_wall_ns":time.time_ns(),
                        "cluster_start_wall_ns":cluster_start,"stdout":result.stdout})
        return cluster_start
    def world(request):
        # GZ_PARTITION and GZ_IP are inherited from this private simulator only.
        gz = ["gz", "service",
            "-s", "/world/sim_world/control", "--reqtype", "gz.msgs.WorldControl", "--reptype", "gz.msgs.Boolean",
            "--timeout", "5000", "--req", request]
        command = base + ["exec", args.simulator_pod, "-c", "simulator", "--", "bash", "-lc",
                         "python3 -c 'import time; print(time.time_ns(), flush=True)'; " + shlex.join(gz)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=15, check=True)
        assert "true" in result.stdout, result.stdout+result.stderr
        cluster_start = int(next(line for line in result.stdout.splitlines() if line.isdigit()))
        actions.append({"action":request,"client_end_wall_ns":time.time_ns(),
                        "cluster_start_wall_ns":cluster_start,"stdout":result.stdout})
        return cluster_start
    results = {}
    try:
        initial = wait(healthy, 90)
        epoch = initial["maps"]["global_semantic"]["epoch"]
        barrier_start = service("clear")
        empty = wait(lambda r: r["maps"]["global_semantic"]["epoch"] > epoch and cleared(r))
        fresh = wait(healthy)
        assert all(m["last"]["capture_wall_ns"] > barrier_start for m in fresh["maps"].values())
        results["clear"] = {"pass":True,"empty":empty,"recovered":fresh}

        service("deactivate")
        empty = wait(lambda r: all(not m["active"] and m["pending"] == 0 for m in r["maps"].values()) and cleared(r))
        until = time.monotonic()+2
        quiet = []
        while time.monotonic() < until:
            row = wait(lambda r: True, 2)
            assert cleared(row) and all(m["pending"] == 0 for m in row["maps"].values())
            quiet.append(row)
        barrier_start = service("activate")
        fresh = wait(healthy)
        assert all(m["last"]["capture_wall_ns"] > barrier_start for m in fresh["maps"].values())
        results["deactivate_reactivate"] = {"pass":True,"quiet_updates":len(quiet),"recovered":fresh}

        before = latest
        world("pause: true")
        try:
            empty = wait(cleared, 10)
            period = max(r["period_ms"] for r in rows[-100:])
            for name, m in empty["maps"].items():
                if before["maps"][name]["marked_cells"]:
                    age = (empty["log_wall_ns"] - m["last"]["capture_wall_ns"])/1e6+2
                    assert age <= 1000+2*period, (name,age,period)
            until = time.monotonic()+2
            while time.monotonic() < until:
                assert cleared(wait(lambda r: True, 2))
            results["paused_expiry"] = {"pass":True,"empty":empty,"max_update_period_ms":period}
        finally:
            world("pause: false")
        recovered = wait(healthy)
        epoch = recovered["maps"]["global_semantic"]["epoch"]
        barrier_start = world("reset: {all: true}")
        empty = wait(lambda r: r["maps"]["global_semantic"]["epoch"] > epoch and cleared(r))
        fresh = wait(healthy)
        assert fresh["sim_ns"] < recovered["sim_ns"]
        assert all(m["last"]["capture_wall_ns"] > barrier_start for m in fresh["maps"].values())
        results["clock_reset"] = {"pass":True,"empty":empty,"recovered":fresh}
        results["pass"] = True
    except Exception as exc:
        results["pass"] = False
        results["error"] = repr(exc)
        raise
    finally:
        # Always restore the test process and private simulation, even on failure.
        try:
            service("activate")
            world("pause: false")
        except Exception as exc:
            results["restoration_error"] = repr(exc)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
        with gzip.open(args.output_dir/"updates.jsonl.gz", "wt") as handle:
            for row in rows:
                handle.write(json.dumps(row,separators=(",",":"))+"\n")
        (args.output_dir/"result.json").write_text(json.dumps({"results":results,"actions":actions},indent=2)+"\n")
        print(json.dumps(results,indent=2),flush=True)


if __name__ == "__main__":
    main()
