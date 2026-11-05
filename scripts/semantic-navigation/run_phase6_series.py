#!/usr/bin/env python3
"""Phase 6 paired semantic-navigation qualification series planner and runner.

Phase 6 entry requires completed Phase 5 qualification. This tool can emit a
trial plan for review at any time, but it refuses to execute unless a Phase 5
acceptance record is supplied, every trial is pinned to the frozen guarded
GPU-rendering profile (the user-approved October 26, 2026 placement
reconciliation: the qualified Phase 5 profile renders the RGB-D camera through
EGL on the pinned GPU worker, and a GPU-free software-rendering placement is
not qualified for motion — see the Phase 5 sign-off caveats), and the operator
confirms the reserved window in the evidence header. The speed ladder advances
only when braking, latency, and viewing-distance gates pass at the current
speed. Nothing here marks Phase 6 passed by itself; the series gate evaluates
recorded per-trial evidence only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ARMS = ("off", "on")
QUALIFIED_GPU_NODE = "ip-10-0-44-146.ec2.internal"
NOMINAL_CASE = "nominal"
NEGATIVE_CASES = ("target_absent", "target_removal", "perception_failure")
PHASE5_GATES = ("recovery_repeatability", "moving_fault_stop",
                "moving_sam3_registration_load", "armed_fault_matrix")
SPEED_LADDER = (0.15, 0.20, 0.25, 0.30, 0.35)
LADDER_GATES = ("braking", "latency", "viewing_distance")
EXPOSURE_SAMPLE_STEP_M = 0.01


def execution_placement_error(node_name, gpu_rendering):
    """Phase 6 execution placement contract (user-approved October 26, 2026).

    Every Phase 6 moving trial must run the frozen guarded GPU profile: the
    qualified Phase 5 motion evidence (all four moving gates) was gathered
    with EGL rendering on the pinned GPU worker, and a GPU-free
    software-rendering placement is not qualified for motion (the October 23
    thread-probe diagnosis: llvmpipe saturation produced the physics stalls
    the 100 ms command-freshness contract correctly fails on).
    """
    if not node_name:
        return "execution requires --node-name pinned to the qualified GPU-rendering worker"
    if not gpu_rendering:
        return ("execution requires --gpu-rendering (the frozen guarded profile; "
                "a GPU-free software-rendering placement is not qualified for motion)")
    return None


def phase5_evidence_error(document):
    if not isinstance(document, dict):
        return "phase 5 evidence is not an object"
    if document.get("passed") is not True:
        return "phase 5 evidence does not record a passed series"
    missing = [gate for gate in PHASE5_GATES if gate not in document.get("accepted_gates", [])]
    if missing:
        return "phase 5 evidence missing gates: " + ",".join(missing)
    return None


def build_trial_plan(pairs, negative_pairs, start_arm, speeds):
    if start_arm not in ARMS:
        raise ValueError("start_arm must be one of " + ",".join(ARMS))
    if pairs < 20:
        raise ValueError("qualification requires at least 20 nominal pairs")
    if negative_pairs < 1:
        raise ValueError("each negative/fault case needs at least one pair")
    if not speeds or any(speed not in SPEED_LADDER for speed in speeds):
        raise ValueError("speeds must be chosen from " + ",".join(str(s) for s in SPEED_LADDER))
    second_arm = ARMS[1 - ARMS.index(start_arm)]
    order = (start_arm, second_arm)
    trials = []
    for pair in range(pairs):
        for slot, arm in enumerate(order):
            trials.append({"pair": pair, "slot": slot, "arm": arm,
                           "case": NOMINAL_CASE, "speed_mps": speeds[0]})
    for case in NEGATIVE_CASES:
        for pair in range(negative_pairs):
            for slot, arm in enumerate(order):
                trials.append({"pair": pairs + pair, "slot": slot, "arm": arm,
                               "case": case, "speed_mps": speeds[0]})
    return {"pairs": pairs, "negative_pairs": negative_pairs,
            "start_arm": start_arm, "speeds_mps": list(speeds), "trials": trials}


def _distance_to_region(x, y, region):
    dx = max(region["xmin"] - x, 0.0, x - region["xmax"])
    dy = max(region["ymin"] - y, 0.0, y - region["ymax"])
    return (dx * dx + dy * dy) ** 0.5


def hull_exposure_m(trajectory_xy, region, hull_radius_m):
    """Arc length of the trajectory whose circumscribed hull enters the region.

    trajectory_xy is an ordered list of [x, y] map-frame samples. The hull is
    approximated by the circumscribed circle of the robot footprint, which
    overestimates exposure and is recorded as such in the evidence. Segments
    are sampled at EXPOSURE_SAMPLE_STEP_M so short clips cannot hide contact.
    """
    if hull_radius_m < 0:
        raise ValueError("hull radius must be non-negative")
    if region["xmax"] <= region["xmin"] or region["ymax"] <= region["ymin"]:
        raise ValueError("region must be a non-degenerate rectangle")
    exposed = 0.0
    for (x0, y0), (x1, y1) in zip(trajectory_xy, trajectory_xy[1:]):
        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if length == 0.0:
            continue
        steps = max(1, int(length / EXPOSURE_SAMPLE_STEP_M))
        sub = length / steps
        for step in range(steps):
            t = (step + 0.5) / steps
            if _distance_to_region(x0 + t * (x1 - x0), y0 + t * (y1 - y0), region) <= hull_radius_m:
                exposed += sub
    return exposed


def speed_ladder_advances(completed_speed, gates, ladder=SPEED_LADDER):
    if completed_speed not in ladder:
        return False, "completed speed is not on the ladder"
    index = ladder.index(completed_speed)
    if index + 1 >= len(ladder):
        return False, None  # already at the top; nothing to advance to
    missing = [gate for gate in LADDER_GATES if gates.get(gate) is not True]
    if missing:
        return False, "speed gates not passed: " + ",".join(missing)
    return True, ladder[index + 1]


def series_gate(trials, reduction_threshold=0.90):
    """Evaluate the Phase 6 pass gate over recorded per-trial evidence."""
    by_arm = {arm: [t for t in trials if t.get("arm") == arm] for arm in ARMS}
    problems = []
    for arm in ARMS:
        nominal = [t for t in by_arm[arm] if t.get("case") == NOMINAL_CASE]
        if len(nominal) < 20:
            problems.append(f"{arm} arm has {len(nominal)} nominal trials; 20 required")
        incomplete = [t.get("trial") for t in nominal if t.get("completed") is not True]
        if incomplete:
            problems.append(f"{arm} arm incomplete trials: {incomplete}")
        collided = [t.get("trial") for t in by_arm[arm] if t.get("collision") is True]
        if collided:
            problems.append(f"{arm} arm physical collisions: {collided}")
    exposure = {}
    for arm in ARMS:
        exposure[arm] = sum(t.get("hull_exposure_m") or 0.0 for t in by_arm[arm]
                            if t.get("case") == NOMINAL_CASE)
    if exposure["off"] <= 0.0:
        problems.append("baseline (off) aggregate exposure is zero; scene inconclusive")
    else:
        reduction = 1.0 - exposure["on"] / exposure["off"]
        if reduction < reduction_threshold:
            problems.append(f"exposure reduction {reduction:.3f} below {reduction_threshold:.2f}")
    for arm in ARMS:
        negative = [t for t in by_arm[arm] if t.get("case") in NEGATIVE_CASES]
        failed = [t.get("trial") for t in negative if t.get("completed") is not True]
        if failed:
            problems.append(f"{arm} arm negative/fault case failures: {failed}")
        unstopped = [t.get("trial") for t in negative
                     if t.get("case") == "perception_failure" and t.get("fault_stop_criteria_met") is not True]
        if unstopped:
            problems.append(f"{arm} arm perception-fault stops not meeting phase 5 criteria: {unstopped}")
    return {"passed": not problems, "problems": problems,
            "aggregate_hull_exposure_m": exposure}


def completion_divergence_summary(trials):
    """Descriptive completion-semantics summary (the October 28 fork decision).

    Makes the belief/truth divergence of every completed nominal arrival
    visible in the series result: the goal checker fires on the AMCL belief
    pose, and a passing trial can still end with the physical robot far from
    the goal. NOT a gate — whether a multi-metre-diverged arrival is
    acceptable belongs to the sign-off review with the user, not here.
    """
    summary = {}
    for arm in ARMS:
        arrivals = []
        for trial in trials:
            if (trial.get("arm") != arm or trial.get("case") != NOMINAL_CASE
                    or trial.get("completed") is not True):
                continue
            arrival = (trial.get("completion_divergence") or {}).get("at_arrival")
            if not arrival:
                continue
            arrivals.append({
                "trial": trial.get("trial"),
                "belief_truth_divergence_at_arrival_m":
                    arrival.get("belief_truth_divergence_m"),
                "physical_goal_distance_at_arrival_m":
                    arrival.get("physical_goal_distance_m")})
        summary[arm] = {
            "arrivals": len(arrivals),
            "max_belief_truth_divergence_at_arrival_m":
                max((a["belief_truth_divergence_at_arrival_m"] or 0.0) for a in arrivals)
                if arrivals else None,
            "max_physical_goal_distance_at_arrival_m":
                max((a["physical_goal_distance_at_arrival_m"] or 0.0) for a in arrivals)
                if arrivals else None,
            "trials": arrivals}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oc", default="oc")
    parser.add_argument("--serving-backend", choices=("local", "http"), default="local")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=20)
    parser.add_argument("--negative-pairs", type=int, default=3)
    parser.add_argument("--start-arm", choices=ARMS, default="off")
    parser.add_argument("--speeds", type=float, nargs="+", default=[0.15])
    parser.add_argument("--hull-radius", type=float, required=True,
                        help="circumscribed radius of the robot footprint in meters")
    parser.add_argument("--region-xmin", type=float, required=True)
    parser.add_argument("--region-xmax", type=float, required=True)
    parser.add_argument("--region-ymin", type=float, required=True)
    parser.add_argument("--region-ymax", type=float, required=True)
    parser.add_argument("--plan-only", action="store_true",
                        help="write the trial plan and exit without executing")
    parser.add_argument("--phase5-evidence", type=Path,
                        help="recorded Phase 5 acceptance JSON; required to execute")
    parser.add_argument("--reserved-window-note", help="operator confirmation that the moving window is reserved")
    parser.add_argument("--node-name", default=QUALIFIED_GPU_NODE,
                        help="pin every trial to one Kubernetes hostname (the qualified GPU-rendering worker)")
    parser.add_argument("--gpu-rendering", action="store_true",
                        help="run every trial on the frozen guarded GPU-rendering profile; required to execute")
    parser.add_argument("--trial-command", nargs="+",
                        help="per-trial command template; placeholders {arm} {case} {speed} {trial} {output} {node}")
    args = parser.parse_args()

    try:
        plan = build_trial_plan(args.pairs, args.negative_pairs, args.start_arm, args.speeds)
    except ValueError as error:
        parser.error(str(error))

    args.output_dir.mkdir(parents=True, exist_ok=False)
    region = {"xmin": args.region_xmin, "xmax": args.region_xmax,
              "ymin": args.region_ymin, "ymax": args.region_ymax}
    manifest = {
        "kind": "phase6_series_plan",
        "serving_backend": args.serving_backend,
        "pairs": plan["pairs"], "negative_pairs": plan["negative_pairs"],
        "start_arm": plan["start_arm"], "speeds_mps": plan["speeds_mps"],
        "ground_truth_region": region, "hull_radius_m": args.hull_radius,
        "hull_approximation": "circumscribed circle (conservative)",
        "trials": plan["trials"],
    }
    (args.output_dir / "plan.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.plan_only:
        print(json.dumps({"plan": str(args.output_dir / "plan.json"),
                          "trials": len(plan["trials"])}))
        return

    error = execution_placement_error(args.node_name, args.gpu_rendering)
    if error:
        parser.error("execution refused: " + error)
    if not args.phase5_evidence:
        parser.error("execution refused: --phase5-evidence is required (Phase 6 entry gate)")
    phase5 = json.loads(args.phase5_evidence.read_text())
    error = phase5_evidence_error(phase5)
    if error:
        parser.error("execution refused: " + error)
    if not args.reserved_window_note:
        parser.error("execution refused: confirm the reserved moving window with --reserved-window-note")
    if not args.trial_command:
        parser.error("execution refused: --trial-command is required")

    root = Path(__file__).resolve().parents[2]
    frozen = sorted((root / "apps").rglob("*.py")) + [
        root / "scripts/semantic-navigation/run_phase6_series.py",
        root / "scripts/semantic-navigation/run_phase5_baseline.py"]
    manifest["source_hashes"] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in frozen if p.exists()}
    manifest["phase5_evidence"] = {"file": str(args.phase5_evidence),
                                   "accepted_gates": phase5.get("accepted_gates")}
    manifest["reserved_window_note"] = args.reserved_window_note
    manifest["placement"] = {"node_name": args.node_name,
                             "gpu_rendering": args.gpu_rendering,
                             "contract": "frozen guarded GPU-rendering profile (Phase 5 sign-off caveat 2)"}
    (args.output_dir / "plan.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.serving_backend == "http":
        manifest["fresh_topology_each_trial"] = True
        for name in ("phase6_trial.py", "run_phase5_native.py", "g4_topology.py"):
            f = root / "scripts/semantic-navigation" / name
            manifest["source_hashes"][str(f.relative_to(root))] = hashlib.sha256(f.read_bytes()).hexdigest()
        (args.output_dir / "plan.json").write_text(json.dumps(manifest, indent=2) + "\n")
    results = []
    for trial in plan["trials"]:
        if args.serving_backend == "http":
            for name, digest in manifest["source_hashes"].items():
                if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
                    raise RuntimeError("source changed during frozen served-navigation series")
            from g4_topology import recycle
            recycle()
        output = args.output_dir / f"trial-{trial['pair']:03d}-{trial['arm']}-{trial['case']}.json"
        command = [part.format(arm=trial["arm"], case=trial["case"],
                               speed=trial["speed_mps"],
                               trial=f"{trial['pair']:03d}-{trial['arm']}-{trial['case']}",
                               node=args.node_name,
                               output=str(output)) for part in args.trial_command]
        completed = subprocess.run(command)
        if completed.returncode != 0:
            results.append({"trial": f"{trial['pair']:03d}-{trial['arm']}-{trial['case']}",
                            "arm": trial["arm"], "case": trial["case"],
                            "completed": False, "runner_returncode": completed.returncode})
            break
        record = json.loads(output.read_text())
        record.setdefault("trial", f"{trial['pair']:03d}-{trial['arm']}-{trial['case']}")
        record.setdefault("arm", trial["arm"])
        record.setdefault("case", trial["case"])
        record["hull_exposure_m"] = hull_exposure_m(
            record.get("trajectory_map_xy") or [], region, args.hull_radius)
        results.append(record)
    gate = series_gate(results)
    summary = {"kind": "phase6_series_result", "passed": gate["passed"],
               "problems": gate["problems"],
               "aggregate_hull_exposure_m": gate["aggregate_hull_exposure_m"],
               "completion_divergence": completion_divergence_summary(results),
               "trials": results}
    (args.output_dir / "series-result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"passed": gate["passed"], "problems": gate["problems"],
                      "aggregate_hull_exposure_m": gate["aggregate_hull_exposure_m"]}))
    if not gate["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
