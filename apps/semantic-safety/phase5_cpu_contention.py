#!/usr/bin/env python3
"""Apply a bounded, reproducible two-worker CPU load to a private Phase 5 probe."""
import json
import argparse
import multiprocessing
import os
from pathlib import Path
import resource
import signal
import sys
import time


WORKERS = 2
shutdown_requested = False


def burn(stop):
    value = 1
    while not stop.is_set():
        value = (value * 1103515245 + 12345) & 0x7FFFFFFF
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid-file", type=Path, required=True)
    args = parser.parse_args()
    context = multiprocessing.get_context("fork")
    stop = context.Event()

    def request_stop(_signal, _frame):
        global shutdown_requested
        shutdown_requested = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    args.pid_file.write_text(str(os.getpid()))
    workers = [context.Process(target=burn, args=(stop,), name=f"phase5-cpu-{i}")
               for i in range(WORKERS)]
    started = time.monotonic()
    for worker in workers:
        worker.start()
    print(json.dumps({"kind": "phase5_cpu_contention", "state": "started",
                      "workers": WORKERS, "requested_cpu_cores": WORKERS}), flush=True)
    try:
        while not shutdown_requested:
            if any(not worker.is_alive() for worker in workers):
                break
            time.sleep(0.2)
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=3.0)
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=1.0)
    elapsed = max(time.monotonic() - started, 1e-9)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = usage.ru_utime + usage.ru_stime
    result = {"kind": "phase5_cpu_contention", "state": "stopped",
              "workers": WORKERS, "wall_seconds": round(elapsed, 3),
              "child_cpu_seconds": round(child_cpu, 3),
              "observed_cpu_cores": round(child_cpu / elapsed, 3),
              "exit_codes": [worker.exitcode for worker in workers]}
    print(json.dumps(result), flush=True)
    args.pid_file.unlink(missing_ok=True)
    if any(code != 0 for code in result["exit_codes"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
