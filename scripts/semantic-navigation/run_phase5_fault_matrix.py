#!/usr/bin/env python3
"""Fixed moving fault-stop matrix; no automatic retries.

Each trial injects one fault class into the qualified guarded moving
fixture after independently verified motion and requires a fail-closed
stop with a mode-qualified first reason, native stop metrics, terminal
cancellation and no automatic resume. The plan is frozen before the first
trial; the series stops on the first failure. This is the Phase 5
moving fault-stop subgate only, not the armed semantic fault matrix.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from run_phase5_baseline import placement_args, placement_error

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/semantic-safety"))
from fault_stop_probe import MODES as FAULT_STOP_MODES


def trial_passed(evidence, returncode, mode):
    required = {"fault_stop_" + mode, "fault_stop_native_stop_metrics",
                "no_automatic_resume_after_fault_restore",
                "cancellation_terminal_and_acknowledged",
                "closed_graph_and_descendants_terminal",
                "guarded_fault_stop_probe_terminal",
                "independent_native_motion_observed",
                "baseline_contact_window", "settled_support_geometry"}
    if evidence.get("fault_stop_mode") != mode:
        return False
    if evidence.get("console_only_server") is not True or evidence.get("world_recording") is not False:
        return False
    if evidence.get("diagnostic_only", False):
        return False
    checks = {c["case"]: c for c in evidence.get("checks", [])}
    return (returncode == 0 and evidence.get("passed") is True
            and all(checks.get(name, {}).get("passed") is True for name in required)
            and all(c.get("passed") is True for c in evidence.get("checks", [])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oc", default="oc")
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--modes", nargs="+", choices=FAULT_STOP_MODES, default=list(FAULT_STOP_MODES))
    parser.add_argument("--node-name", required=True, help="pin every trial to one Kubernetes hostname")
    parser.add_argument("--gpu-rendering", action="store_true",
                        help="pin every trial to a GPU worker and render the RGB-D camera through EGL")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("at least one repetition per fault mode is required")
    error = placement_error(False, args.node_name, False, args.gpu_rendering)
    if error:
        parser.error(error)
    root = Path(__file__).resolve().parents[2]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    files = sorted((root / "apps/semantic-safety").glob("*.py")) + [
        root / "apps/semantic-safety/phase5-baseline.xml",
        root / "helm/semantic-navigation/phase5-nav2-candidate.yaml",
        root / "scripts/semantic-navigation/run_phase5_native.py",
        root / "scripts/semantic-navigation/run_phase5_fault_matrix.py"]
    hashes = lambda: {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    frozen = hashes()
    trials = [{"mode": mode, "repetition": repetition}
              for repetition in range(1, args.repetitions + 1)
              for mode in args.modes]
    plan = {"image": args.image, "planned_trials": len(trials),
            "scenario": "qualified guarded moving fixture; single fault class injected after verified motion",
            "modes": args.modes, "repetitions": args.repetitions,
            "node_name": args.node_name, "gpu_rendering": args.gpu_rendering,
            "retry_policy": "none; stop series on first failure",
            "qualified_profile": {"console_only_server": True, "contact_audit": True,
                                  "rear_casters": True, "physics_step": 0.002,
                                  "lidar_range": 12.0, "odom_frequency": 200.0},
            "source_hashes": frozen}
    (args.output_dir / "plan.json").write_text(json.dumps(plan, indent=2))
    results = []
    for trial in trials:
        if hashes() != frozen:
            raise RuntimeError("runtime inputs changed during fixed series")
        directory = args.output_dir / f"trial-{len(results) + 1:02d}-{trial['mode']}-r{trial['repetition']}"
        print(json.dumps({"event": "trial_started", **trial}), flush=True)
        command = [sys.executable, str(root / "scripts/semantic-navigation/run_phase5_native.py"),
            "--oc", args.oc, "--suite", "hotel-guarded", "--contact-audit",
            "--fault-stop-probe", "--fault-stop-mode", trial["mode"],
            "--console-only-server", "--rear-casters",
            "--physics-step", "0.002", "--lidar-range", "12", "--odom-frequency", "200",
            "--image", args.image, "--output-dir", str(directory)]
        command.extend(placement_args(args.node_name, False, args.gpu_rendering))
        run = subprocess.run(command)
        path = directory / "runtime/summary.json"
        evidence = json.loads(path.read_text()) if path.is_file() else {}
        passed = trial_passed(evidence, run.returncode, trial["mode"])
        if hashes() != frozen:
            passed = False
        results.append({"trial": len(results) + 1, **trial, "passed": passed,
                        "returncode": run.returncode, "evidence": str(path)})
        summary = {"passed": len(results) == len(trials) and all(r["passed"] for r in results),
                   "planned": len(trials), "attempted": len(results),
                   "succeeded": sum(r["passed"] for r in results),
                   "results": results,
                   "scope": "moving fault-stop matrix on the private guarded fixture; "
                            "not the armed semantic fault matrix or full Phase 5"}
        (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps({"event": "trial_finished", **results[-1]}), flush=True)
        if not passed:
            raise RuntimeError("fault-stop matrix failed; no automatic retry")


if __name__ == "__main__":
    main()
