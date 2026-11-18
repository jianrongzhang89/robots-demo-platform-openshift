#!/usr/bin/env python3
"""Analyze the Stage 4 comparative demonstration and decide AI value.

Loads every trial's selection and result, chains round-trip legs, computes
paired mission-energy comparisons between arms with 95 percent t-based
confidence intervals, evaluates prediction MAE, upper-estimate coverage,
route agreement, completion time, reserve and deadline compliance, and the
frozen acceptance criteria, then states the explicit AI-value decision.
Standard library only.
"""
import argparse
import json
import math
from pathlib import Path


def lgamma(x):
    return math.lgamma(x)


def betacf(a, b, x):
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln = (lgamma(a + b) - lgamma(a) - lgamma(b) + a * math.log(x) + b * math.log(1.0 - x))
    front = math.exp(ln)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * betacf(a, b, x) / a
    return 1.0 - front * betacf(b, a, 1.0 - x) / b


def t_quantile_975(df):
    """Two-sided 97.5 percent point of Student's t via the incomplete beta."""
    low, high = -200.0, 200.0
    target = 0.975
    for _ in range(200):
        mid = (low + high) / 2.0
        cdf = 1.0 - 0.5 * betai(df / 2.0, 0.5, df / (df + mid * mid))
        if cdf < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def paired_summary(differences):
    """Mean, 95 percent t CI, and paired t statistics."""
    n = len(differences)
    if n < 2:
        return {"n": n, "mean": None, "ci": None}
    mean = sum(differences) / n
    variance = sum((d - mean) ** 2 for d in differences) / (n - 1)
    sd = math.sqrt(variance)
    half = t_quantile_975(n - 1) * sd / math.sqrt(n)
    return {"n": n, "mean": round(mean, 8), "ci95": [round(mean - half, 8),
                                                      round(mean + half, 8)],
            "sd": round(sd, 8)}


def load_series(series):
    trials = []
    for directory in sorted(p for p in series.iterdir() if p.is_dir()):
        result_path = directory / "stage4-result.json"
        selection_path = directory / "route-selection.json"
        if not result_path.exists() or not selection_path.exists():
            continue
        trials.append({"name": directory.name,
                       "result": json.loads(result_path.read_text()),
                       "selection": json.loads(selection_path.read_text())})
    return trials


def triplet_key(name):
    """Group trials into matched triplets (stratum/round-trip + triplet id)."""
    parts = name.split("-")
    if name.startswith("ow-"):
        return "-".join(parts[:4])  # ow-p0.5-dup-t2
    if name.startswith("rt-"):
        return "-".join(parts[:3])  # rt-t2-armA -> rt-t2
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series", type=Path)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment = json.loads(args.experiment.read_text())
    trials = load_series(args.series)
    errors = []

    passing = [t for t in trials if t["result"]["status"] == "PASS"]
    rejected = [t for t in trials if t["result"]["status"] == "REJECTED"]
    if len(passing) + len(rejected) != len(trials):
        errors.append("trials with missing status")

    oneway = [t for t in passing if t["result"]["mission"] == "oneway"]
    # Round-trip chaining: pair outbound and return legs by triplet and arm.
    roundtrips = {}
    for trial in passing:
        if trial["result"]["mission"] == "roundtrip-out":
            key = triplet_key(trial["name"])
            roundtrips.setdefault(key, {})["out"] = trial
        elif trial["result"]["mission"] == "roundtrip-return":
            key = triplet_key(trial["name"])
            roundtrips.setdefault(key, {})["return"] = trial
    complete_roundtrips = []
    for key, legs in sorted(roundtrips.items()):
        if "out" in legs and "return" in legs:
            out, back = legs["out"], legs["return"]
            complete_roundtrips.append({
                "key": key, "arm": out["result"]["arm"],
                "route": out["result"]["selected_route"],
                "observed_wh": round(out["result"]["observation"]["observed_mission_wh"]
                                     + back["result"]["observation"]["observed_mission_wh"], 6),
                "predicted_wh": round(out["result"]["prediction"]["predicted_mission_wh"]
                                      + back["result"]["prediction"]["predicted_mission_wh"], 6),
                "chained_final_soc": back["result"]["observation"]["observed_final_soc"],
                "duration_s": round(out["result"]["observation"]["observed_duration_s"]
                                    + back["result"]["observation"]["observed_duration_s"], 1),
                "estimator_mode": out["result"]["prediction"]["estimator_mode"],
                "upper_covers": bool(
                    out["result"]["upper_estimate_covers_observation"]
                    and back["result"]["upper_estimate_covers_observation"])})

    # Paired comparisons within matched triplets (one-way).
    groups = {}
    for trial in oneway:
        key = triplet_key(trial["name"])
        groups.setdefault(key, {})[trial["result"]["arm"]] = trial
    matched = [g for g in groups.values() if set(g) == {"A", "B", "C"}]
    energy_diff_ba, energy_diff_cb, time_diff_ba, time_diff_cb = [], [], [], []
    for group in matched:
        wh = {arm: group[arm]["result"]["observation"]["observed_mission_wh"]
              for arm in "ABC"}
        dur = {arm: group[arm]["result"]["observation"]["observed_duration_s"]
               for arm in "ABC"}
        energy_diff_ba.append(wh["B"] - wh["A"])
        energy_diff_cb.append(wh["C"] - wh["B"])
        time_diff_ba.append(dur["B"] - dur["A"])
        time_diff_cb.append(dur["C"] - dur["A"])

    def mae(trial_list):
        errors = [abs(t["result"]["prediction_error_wh"]) for t in trial_list]
        return sum(errors) / len(errors) if errors else None

    arm_b = [t for t in oneway if t["result"]["arm"] == "B"]
    arm_c_served = [t for t in oneway if t["result"]["arm"] == "C"
                    and t["result"]["prediction"]["estimator_mode"] == "served"]
    arm_c_fallback = [t for t in oneway if t["result"]["arm"] == "C"
                      and t["result"]["prediction"]["estimator_mode"] != "served"]
    mae_b, mae_c = mae(arm_b), mae(arm_c_served)
    improvement = (1.0 - mae_c / mae_b) if mae_b and mae_c else None

    def coverage(trial_list):
        if not trial_list:
            return None
        covered = sum(1 for t in trial_list
                      if t["result"]["upper_estimate_covers_observation"])
        return round(covered / len(trial_list), 4)

    route_agreement = None
    if matched:
        agreeing = sum(1 for group in matched
                       if len({group[a]["result"]["selected_route"] for a in "ABC"}) == 1)
        route_agreement = round(agreeing / len(matched), 4)

    mean_duration = {arm: (sum(t["result"]["observation"]["observed_duration_s"]
                               for t in oneway if t["result"]["arm"] == arm)
                           / max(1, sum(1 for t in oneway if t["result"]["arm"] == arm)))
                     for arm in "ABC"}
    time_increase_c_vs_a = (mean_duration["C"] / mean_duration["A"] - 1.0
                            if mean_duration["A"] else None)

    fallback_demo = [t for t in trials
                     if t["name"].startswith("fallback-armC")]
    fallback_ok = bool(fallback_demo) and all(
        t["result"]["status"] == "PASS"
        and t["result"]["prediction"]["estimator_mode"] != "served"
        for t in fallback_demo)

    criteria = experiment["criteria"]
    b_vs_a = paired_summary(energy_diff_ba)
    c_vs_b = paired_summary(energy_diff_cb)
    aggregate_b = (sum(t["result"]["observation"]["observed_mission_wh"] for t in arm_b)
                   / len(arm_b)) if arm_b else None
    aggregate_c = (sum(t["result"]["observation"]["observed_mission_wh"] for t in arm_c_served)
                   / len(arm_c_served)) if arm_c_served else None
    ai_energy_improvement = (1.0 - aggregate_c / aggregate_b
                             if aggregate_b and aggregate_c else None)

    checks = {
        "motion_and_task_completion": {
            "status": "PASS" if not errors and len(passing) + len(rejected) == len(trials)
            else "FAIL",
            "passed_trials": len(passing), "rejected_trials": len(rejected)},
        "prediction_mae_improvement": {
            "status": ("PASS" if improvement is not None
                       and improvement >= criteria["prediction_mae_improvement_fraction"]
                       else "FAIL"),
            "arm_b_mae_wh": round(mae_b, 6) if mae_b else None,
            "arm_c_served_mae_wh": round(mae_c, 6) if mae_c else None,
            "improvement_fraction": round(improvement, 4) if improvement is not None else None,
            "target": criteria["prediction_mae_improvement_fraction"]},
        "uncertainty_coverage": {
            "status": "PASS" if (coverage(arm_c_served) or 0) >= criteria[
                "mission_upper_coverage_fraction"] else "FAIL",
            "served_mode": coverage(arm_c_served),
            "physics_mode": coverage(arm_b),
            "target": criteria["mission_upper_coverage_fraction"]},
        "route_coordination": {
            "status": "PASS" if route_agreement == criteria["route_agreement_fraction"]
            else "FAIL",
            "route_agreement_fraction": route_agreement},
        "mission_utility_time": {
            "status": "PASS" if time_increase_c_vs_a is not None
            and time_increase_c_vs_a <= criteria["maximum_time_increase_fraction_vs_A"]
            else "FAIL",
            "mean_duration_s": {k: round(v, 1) for k, v in mean_duration.items()},
            "time_increase_fraction_c_vs_a": round(time_increase_c_vs_a, 4)
            if time_increase_c_vs_a is not None else None},
        "added_ai_value_energy": {
            "status": ("PASS" if ai_energy_improvement is not None
                       and ai_energy_improvement >= criteria["ai_energy_improvement_fraction"]
                       and c_vs_b["ci95"] and c_vs_b["ci95"][0] > 0 else "FAIL"),
            "aggregate_mission_wh": {"B": round(aggregate_b, 6) if aggregate_b else None,
                                      "C": round(aggregate_c, 6) if aggregate_c else None},
            "improvement_fraction": round(ai_energy_improvement, 4)
            if ai_energy_improvement is not None else None,
            "paired_c_vs_b_wh": c_vs_b,
            "target": criteria["ai_energy_improvement_fraction"]},
        "energy_aware_routing_b_vs_a": {
            "paired_b_minus_a_wh": b_vs_a,
            "note": "reported independently; not attributed to AI"},
        "fallback_demonstration": {
            "status": "PASS" if fallback_ok else "FAIL",
            "trials": [t["name"] for t in fallback_demo],
            "estimator_modes": [t["result"]["prediction"]["estimator_mode"]
                                for t in fallback_demo]},
    }

    # Explicit AI-value decision per the proposal's legitimate outcomes.
    prediction_win = (improvement is not None
                      and improvement >= criteria["prediction_mae_improvement_fraction"])
    energy_win = (ai_energy_improvement is not None
                  and ai_energy_improvement >= criteria["ai_energy_improvement_fraction"]
                  and c_vs_b["ci95"] and c_vs_b["ci95"][0] > 0)
    if prediction_win and energy_win:
        decision = ("AI VALUE CONFIRMED: arm C improves both held-out prediction and "
                    "aggregate mission energy versus arm B beyond the frozen thresholds.")
    elif prediction_win:
        decision = ("PREDICTION RESULT ONLY: arm C materially improves mission-energy "
                    "prediction over arm B, but produces no route-energy benefit in this "
                    "fixture because every arm selects the same (energy-optimal) corridor. "
                    "Per the proposal this is a recorded research outcome, not a failure; "
                    "an energy-routing benefit requires conditions where the estimators "
                    "disagree on the chosen corridor (for example a qualified second "
                    "surface or a fixture change).")
    else:
        decision = ("NO AI VALUE DEMONSTRATED: neither the prediction nor the "
                    "energy criterion was met; retain the physics planner per the "
                    "proposal and document the limiting conditions.")

    report = {
        "status": "FAIL" if errors or any(c["status"] == "FAIL" for c in checks.values()
                                          if isinstance(c, dict)) else "PASS",
        "errors": errors,
        "trials": {"total": len(trials), "passed": len(passing), "rejected": len(rejected),
                   "oneway_by_arm": {arm: sum(1 for t in oneway if t["result"]["arm"] == arm)
                                     for arm in "ABC"},
                   "matched_triplets": len(matched),
                   "complete_roundtrips": len(complete_roundtrips)},
        "checks": checks,
        "roundtrips": complete_roundtrips,
        "ai_value_decision": decision,
        "scope": "Stage 4 comparative demonstration over modeled simulated energy; "
                 "no physical battery-saving claim",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"],
                      "checks": {k: v.get("status", "reported")
                                 for k, v in checks.items()},
                      "decision": decision}))


if __name__ == "__main__":
    main()
