#!/usr/bin/env python3
"""Phase 6 series trial wrapper: run one trial and emit the evaluator record.

The series runner (run_phase6_series.py) executes this per trial with
{arm} {case} {speed} {trial} {output} {node} placeholders and then reads the
record JSON at {output}. The record carries the fields the series gate
consumes: completed (the trial's full check suite), collision (the contact
window), trajectory_map_xy (the physical trace for hull-exposure
measurement), fault_stop_criteria_met (the perception-failure case), and the
descriptive path/completion/clearance metrics the plan asks to report
alongside the semantic benefit.

The candidate includes the endpoint-capture controller overlay (the October
28, 2026 fork decision, user-approved): the goal checker evaluates the fixed
map goal at the robot pose's capture timestamp instead of the path's original
stamp, without relaxing the 0.20 m arrival tolerance — the documented
October 19 stale-stamp mismatch class that kept the checker from firing
while the belief sat on the goal. The fixture fail-closes on the
opt_in_controller_overlay_loaded check; file presence proves nothing.

Every record also carries completion_divergence (descriptive, not a gate):
the goal checker fires on the AMCL belief pose, and the series-18 finding
showed the belief/truth divergence reaching 2.7 m through the goal approach
— a "goal_succeeded" arrival can end with the physical robot metres from
the goal. The divergence is measured at the arrival instant (the
controller's own "Reached the goal!" wall stamp) and at the final row, so a
multi-metre-diverged arrival is visible in every trial record instead of
silently passing. The pass/fail decision on such an arrival belongs to the
sign-off review, not to this code.

Case mapping (the plan's verification: nominal pairs plus target-absent,
target-removal and perception-failure cases):
- nominal: the paired arm (off = the Phase 5 candidate; on = the lethal-254
  exclusion experiment) with the capture-time TF witness.
- target_absent: the staged mat omitted; completion must not regress.
- target_removal: the mat removed mid-trial through the pre-warmed mover.
- perception_failure: the armed-semantic supervisor plus the in-fixture
  camera-path-loss fault; both arms must stop meeting the Phase 5 criteria.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
OC = "/Users/zhangj/bin/oc"
IMAGE = ("image-registry.openshift-image-registry.svc:5000/semantic-navigation/"
         "semantic-safety@sha256:348fc584e70b07c6f73f9e428623240da5fc4c81ead630f0cb051c18de2d4371")
NODE = "ip-10-0-44-146.ec2.internal"
SPEED = 0.15  # the first ladder rung only; the candidate's frozen cap


def distance_to_region(x, y, region):
    dx = max(region["xmin"] - x, 0.0, x - region["xmax"])
    dy = max(region["ymin"] - y, 0.0, y - region["ymax"])
    return math.hypot(dx, dy)


def recycle_topology():
    """Recycle the private zenoh router and the SAM3 pod (the documented
    remedy for the never-re-dials session class). The router's data plane
    degrades stochastically across fixture-pod sessions (series-6 through -9:
    ~3 sessions per fresh router; the SAM3-pod-only recycle recovers ~1) —
    the costs-gate liveness death is this class, not a trial result."""
    import subprocess
    import time as _time
    # Idempotent deletes: the recycle must also work when the pod or the
    # router deployment is already gone (the demo preflight path, or a
    # partial earlier recycle).
    subprocess.run(["/Users/zhangj/bin/oc", "-n", "semantic-navigation",
                    "delete", "pod", "semantic-phase5-sam3",
                    "--ignore-not-found=true",
                    "--wait=true", "--timeout=60s"], check=True, capture_output=True)
    subprocess.run(["/Users/zhangj/bin/oc", "-n", "semantic-navigation",
                    "delete", "deploy", "semantic-phase5-sam3-router",
                    "--ignore-not-found=true",
                    "--wait=true", "--timeout=60s"], check=True, capture_output=True)
    import sys
    sys.path.insert(0, str(ROOT / "scripts/semantic-navigation"))
    from phase6_topology import topology_objects, sam3_pod_spec, wait_router_available
    sam3_image = (
            "image-registry.openshift-image-registry.svc:5000/semantic-navigation/"
        "sam3-runtime@sha256:478ec01a7a47fbb0c862fbbef495c71b4a512ff59ed8d6ed5b7234422cc35686")
    for obj in topology_objects(sam3_image):
        if obj["kind"] == "Deployment" and obj["metadata"]["name"] == "semantic-phase5-sam3-router":
            subprocess.run(["/Users/zhangj/bin/oc", "-n", "semantic-navigation",
                            "create", "-f", "-"], input=json.dumps(obj),
                           text=True, check=True, capture_output=True)
    if not wait_router_available(OC):
        raise RuntimeError("private router did not recover before SAM3 restart")
    subprocess.run(["/Users/zhangj/bin/oc", "-n", "semantic-navigation",
                    "create", "-f", "-"], input=json.dumps(sam3_pod_spec(sam3_image)),
                   text=True, check=True, capture_output=True)
    deadline = _time.monotonic() + 300
    while _time.monotonic() < deadline:
        result = subprocess.run(
            ["/Users/zhangj/bin/oc", "-n", "semantic-navigation", "get",
             "pod", "semantic-phase5-sam3", "-o", "jsonpath={.status.phase} "
             "{.status.containerStatuses[*].ready}"],
            capture_output=True, text=True)
        if result.stdout.strip() == "Running true true":
            return
        _time.sleep(5)
    raise RuntimeError("SAM3 pod did not return ready after the recycle")


def costs_gate_liveness_death(evidence):
    """The zenoh data-plane death signature: the SAM3 observations never
    arrived — either the costs gate timed out with zero semantic cells (and
    the witness never qualified a scan), or the trial died earlier at the
    SAM3 observation readiness gate (series-12: the stale router blocked the
    stream before the costmaps ever pulled). This is infrastructure
    liveness, not a trial result."""
    for summary in (evidence / "runtime/summary.json",
                    evidence / "runtime-partial/summary.json"):
        if not summary.is_file():
            continue
        checks = json.loads(summary.read_text()).get("checks", [])
        gate = next((c for c in checks
                     if c.get("case") == "phase6_costs_gate_diagnostic"), None)
        if gate is not None and not gate.get("passed", False):
            costs = gate.get("last_costs") or {}
            if costs.get("global_soft_cells") == 0:
                return True
        for marker in ("semantic soft costs accepted at the mat",
                       "SAM3 observation readiness before arming",
                       "camera liveness from the observation worker"):
            if any(marker in str(c.get("error", ""))
                   for c in checks if not c.get("passed", False)):
                return True
    # Pre-check WaitTimeout labels (the SAM3 readiness gate dies before any
    # check records it) surface only in the retained fixture traceback.
    log = evidence / "test.log"
    if log.is_file():
        text = log.read_text(errors="replace")[-20000:]
        for marker in ("timeout: SAM3 observation readiness before arming",
                       "timeout: camera liveness from the observation worker",
                       "timeout: semantic soft costs accepted at the mat"):
            if marker in text:
                return True
    return False


def completion_divergence(evidence, physical):
    """Completion-semantics evidence: belief/truth divergence at arrival.

    The goal checker fires on the AMCL-localized pose; through the goal
    approach the belief can diverge from the physical robot by metres (the
    series-18 finding: belief 0.11 m from the goal, robot 2.6 m away). Match
    control-geometry.json map poses (the belief) to the trace's physical rows
    by simulation stamp and measure at the arrival instant — the controller's
    own "Reached the goal!" wall stamp mapped through the trace — plus the
    final row. Descriptive only: the series gate does not consume these
    fields; a multi-metre-diverged arrival stays visible for the sign-off
    review instead of silently passing.
    """
    geometry = evidence / "runtime/control-geometry.json"
    if not geometry.is_file():
        geometry = evidence / "runtime-partial/control-geometry.json"
    if not geometry.is_file() or not physical:
        return None
    try:
        rows = [r for r in json.loads(geometry.read_text()) if "map_x" in r]
    except ValueError:
        return None
    if not rows:
        return None
    endpoint = rows[0].get("planner_endpoint") or {}
    goal = (endpoint["x"], endpoint["y"]) if "x" in endpoint and "y" in endpoint else None
    stamps = [p["sim_ns"] for p in physical]

    def nearest_physical(sim_ns):
        index = min(bisect.bisect_left(stamps, sim_ns), len(stamps) - 1)
        if index > 0 and abs(stamps[index - 1] - sim_ns) < abs(stamps[index] - sim_ns):
            index -= 1
        return physical[index]

    def measure(row):
        p = nearest_physical(row["stamp"])
        out = {"sim_ns": row["stamp"],
               "belief_truth_divergence_m": round(
                   math.hypot(row["map_x"] - p["x"], row["map_y"] - p["y"]), 3)}
        if goal:
            out["physical_goal_distance_m"] = round(
                math.hypot(p["x"] - goal[0], p["y"] - goal[1]), 3)
            out["belief_goal_distance_m"] = round(
                math.hypot(row["map_x"] - goal[0], row["map_y"] - goal[1]), 3)
        return out

    result = {"final": measure(rows[-1])}
    controller_log = evidence / "runtime/controller_server.log"
    if not controller_log.is_file():
        controller_log = evidence / "runtime-partial/controller_server.log"
    wall_ns = None
    if controller_log.is_file():
        for line in controller_log.read_text(errors="replace").splitlines():
            if "Reached the goal!" not in line:
                continue
            stamp = re.search(r"\[(\d+\.\d+)\]", line)
            if stamp:
                wall_ns = int(float(stamp.group(1)) * 1e9)
    if wall_ns is not None:
        walls = [p["wall_ns"] for p in physical]
        index = min(bisect.bisect_left(walls, wall_ns), len(walls) - 1)
        if index > 0 and abs(walls[index - 1] - wall_ns) < abs(walls[index] - wall_ns):
            index -= 1
        arrival_sim = physical[index]["sim_ns"]
        arrival_row = min(rows, key=lambda r: abs(r["stamp"] - arrival_sim))
        result["at_arrival"] = measure(arrival_row)
        result["arrival_wall_ns"] = wall_ns
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # Positional on purpose: the series runner passes the trial command
    # through argparse's nargs="+" — any --prefixed argument here would be
    # captured by the series' own parser. Everything else is derived from
    # the series directory's plan.json (the region) and layout (trial-runs).
    parser.add_argument("arm", choices=("off", "on"))
    parser.add_argument("case",
                        choices=("nominal", "target_absent", "target_removal",
                                 "perception_failure"))
    parser.add_argument("trial")
    parser.add_argument("output", type=Path,
                        help="the record JSON path the series evaluator reads")
    args = parser.parse_args()

    series_dir = args.output.parent
    plan = json.loads((series_dir / "plan.json").read_text())
    region = plan["ground_truth_region"]
    args.runs_dir = series_dir / "trial-runs"
    evidence = args.runs_dir / f"trial-{args.trial}"
    command = [
        sys.executable, str(ROOT / "scripts/semantic-navigation/run_phase5_native.py"),
        "--oc", OC,
        "--suite", "hotel-guarded", "--contact-audit", "--sam3-observation",
        "--semantic-arm", args.arm, "--phase6-tf-witness",
        "--controller-endpoint-capture",
        "--console-only-server", "--rear-casters",
        "--physics-step", "0.002", "--lidar-range", "12", "--odom-frequency", "200",
        "--gpu-rendering", "--node-name", NODE, "--image", IMAGE,
        "--output-dir", str(evidence)]
    if plan.get("serving_backend") == "http":
        command.append("--served-topology")
    if args.arm == "on":
        command.append("--phase6-lethal")
    if args.case == "target_absent":
        command.append("--phase6-target-absent")
    elif args.case == "target_removal":
        command.append("--phase6-target-removal")
    elif args.case == "perception_failure":
        command += ["--semantic-fault-probe", "--semantic-fault-mode", "camera_path_loss"]

    completed = subprocess.run(command).returncode == 0
    # The documented infrastructure-liveness classes, both failing CLOSED at
    # the pre-arm readiness gates (no motion, no evidence contamination):
    # (a) the per-fixture-session gz-transport capture_trace delivery race
    #     (October 29, series-20/probe evidence: every other topic flows,
    #     a fresh fixture pod on the SAME topology recovers it, the router
    #     is not at fault) — remedy: retry with a fresh fixture pod, up to
    #     twice before any recycle;
    # (b) the router data-plane degradation (~sessions per router) — remedy:
    #     the topology recycle, one final retry after the bare retries.
    # Every attempt is retained under -liveness-N suffixes and counted in the
    # record. A trial whose CHECKS fail is never retried: the
    # stop-on-first-failure discipline only tolerates infrastructure deaths.
    retries = recycles = 0
    while not completed and costs_gate_liveness_death(evidence) and retries < 2:
        retries += 1
        liveness = args.runs_dir / f"trial-{args.trial}-liveness-{retries}"
        if liveness.exists():
            import shutil
            shutil.rmtree(liveness)
        evidence.rename(liveness)
        completed = subprocess.run(command).returncode == 0
    if not completed and costs_gate_liveness_death(evidence):
        recycles = 1
        liveness = args.runs_dir / f"trial-{args.trial}-liveness-{retries + 1}"
        if liveness.exists():
            import shutil
            shutil.rmtree(liveness)
        evidence.rename(liveness)
        if plan.get("serving_backend") == "http":
            from g4_topology import recycle
            recycle()
        else:
            recycle_topology()
        completed = subprocess.run(command).returncode == 0
        if not completed and costs_gate_liveness_death(evidence):
            raise RuntimeError("the data plane did not recover after "
                               f"{retries} retries and one recycle")
    record = {"trial": args.trial, "arm": args.arm, "case": args.case,
              "speed_mps": SPEED, "completed": completed,
              "collision": None, "fault_stop_criteria_met": None,
              "infrastructure_recycles": recycles,
              "infrastructure_retries": retries,
              "controller_endpoint_capture": True,
              "trajectory_map_xy": []}
    summary_path = evidence / "runtime/summary.json"
    partial_path = evidence / "runtime-partial/summary.json"
    source = summary_path if summary_path.is_file() else (
        partial_path if partial_path.is_file() else None)
    if source is not None:
        summary = json.loads(source.read_text())
        record["completed"] = bool(summary.get("passed")) and completed
        for check in summary.get("checks", []):
            case = check.get("case", "")
            if case == "baseline_contact_window":
                record["collision"] = not check.get("passed", False)
            if case.startswith("semantic_fault_") or case == "fault_stop_camera_path_loss":
                record["fault_stop_criteria_met"] = bool(check.get("passed"))
        record["terminal_status"] = next(
            (c.get("terminal_status") for c in summary.get("checks", [])
             if c.get("case") == "guarded_real_hotel_one_meter_goal"), None)
        record["stop_reason"] = next(
            (c.get("reason") for c in summary.get("checks", [])
             if c.get("case") == "guarded_real_hotel_one_meter_goal"), None)
    trace = evidence / "runtime/trace.jsonl"
    if not trace.is_file():
        trace = evidence / "runtime-partial/trace.jsonl"
    if trace.is_file():
        physical = []
        for line in trace.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            item = row.get("physical")
            if item and item.get("velocity_valid"):
                physical.append(item)
        record["trajectory_map_xy"] = [[p["x"], p["y"]] for p in physical]
        divergence = completion_divergence(evidence, physical)
        if divergence is not None:
            record["completion_divergence"] = divergence
        if len(physical) >= 2:
            length = sum(math.hypot(b["x"] - a["x"], b["y"] - a["y"])
                         for a, b in zip(physical, physical[1:]))
            record["path_length_m"] = round(length, 3)
            record["completion_time_s"] = round(
                (physical[-1]["wall_ns"] - physical[0]["wall_ns"]) / 1e9, 2)
            record["min_centerline_clearance_m"] = round(
                min(distance_to_region(p["x"], p["y"], region)
                    for p in physical), 3)
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"trial": args.trial, "completed": record["completed"]}))
    # The series runner treats a nonzero exit as a failed trial; a trial whose
    # checks failed must exit nonzero so the stop-on-first-failure discipline
    # holds, but the record is written first either way.
    if not record["completed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
