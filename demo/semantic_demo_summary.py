#!/usr/bin/env python3
"""Narrated summary of one semantic-navigation demo act (read-only).

Reads a fixture evidence directory (the run_phase5_native.py output) and
prints the demo-relevant numbers: pass/fail, the mat-exposure contrast,
arrival divergence, and the stop reason. Demo narration only — the
qualification evidence is the trial's own summary.json.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/semantic-navigation"))
from phase6_trial import completion_divergence, distance_to_region  # noqa: E402
from run_phase6_series import hull_exposure_m  # noqa: E402

REGION = {"xmin": 16.9514, "xmax": 17.8514, "ymin": -31.919, "ymax": -31.269}
HULL = 0.246


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: semantic_demo_summary.py <evidence-dir>")
    evidence = Path(sys.argv[1])
    runtime = evidence / "runtime"
    if not runtime.is_dir():
        runtime = evidence / "runtime-partial"
    summary = json.loads((runtime / "summary.json").read_text())
    checks = summary.get("checks", [])
    goal = next((c for c in checks if c.get("case") == "guarded_real_hotel_one_meter_goal"), {})
    fault = next((c for c in checks if c.get("case", "").startswith("semantic_fault_")), {})

    physical = []
    for line in (runtime / "trace.jsonl").read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        p = row.get("physical")
        if p and p.get("velocity_valid"):
            physical.append(p)

    lines = []
    ok = summary.get("passed") is True
    lines.append(f"  checks: {sum(1 for c in checks if c.get('passed'))}/{len(checks)} passed"
                 f" — {'PASS' if ok else 'FAIL'}")
    if goal:
        lines.append(f"  goal: {goal.get('reason')} (terminal {goal.get('terminal_status')})")
    if fault:
        lines.append(f"  fault stop: {'met Phase 5 criteria' if fault.get('passed') else 'NOT met'}")
    if physical:
        xy = [[p["x"], p["y"]] for p in physical]
        lines.append(f"  route: {len(physical)} samples, "
                     f"{sum(math.hypot(b['x']-a['x'], b['y']-a['y']) for a, b in zip(physical, physical[1:])):.2f} m")
        lines.append(f"  hull exposure inside the mat: {hull_exposure_m(xy, REGION, HULL):.3f} m")
        lines.append(f"  closest centerline approach to the mat: "
                     f"{min(distance_to_region(p['x'], p['y'], REGION) for p in physical):.3f} m")
        d = completion_divergence(evidence, physical) or {}
        arrival = d.get("at_arrival") or d.get("final") or {}
        if arrival:
            label = "arrival" if d.get("at_arrival") else "at stop"
            lines.append(f"  {label}: belief/truth divergence {arrival.get('belief_truth_divergence_m')} m, "
                         f"physical goal distance {arrival.get('physical_goal_distance_m')} m "
                         "(belief-frame completion, recorded per sign-off)")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
