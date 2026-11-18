#!/usr/bin/env python3
"""Energy-aware warehouse delivery demonstration (showcase run).

Executes the approved proposal's demonstration sequence as one scripted,
operator-presentable run:

  1. Briefing: the frozen warehouse, candidate routes, battery reserve,
     deadlines, and side-by-side estimates from all three estimators.
  2. Three matched delivery round trips (loading -> transfer loaded,
     transfer -> loading empty): the distance baseline (arm A), physics
     energy routing (arm B), and learned energy routing (arm C, served).
  3. The comparison: consumed Wh, completion time, route selection, and
     prediction error across the three deliveries.
  4. Payload sensitivity: predictions and route choice at 0 / 0.25 / 0.5 kg.
  5. Resilience: the serving endpoint made unavailable before a new route
     decision, demonstrating the documented physics fallback.

Every mission reuses the audited Stage 4 trial machinery. The run writes a
machine-readable evidence file and a self-contained HTML operator summary
with inline SVG charts and robot camera snapshots.
"""
import argparse
import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from physics_model import PhysicsModel
import route_selector

ROOT = Path(__file__).resolve().parents[2]
ARMS = [("A", "Distance baseline"), ("B", "Physics energy routing"),
        ("C", "Learned energy routing (served)")]


def select_view(model, fixture, release, args, arm, payload, return_payload=None):
    sys.path.insert(0, str(ROOT / "apps/energy-predictor"))
    estimator = None
    if arm == "C":
        from energy_serving_client import EnergyServingClient
        import predictor as predictor_module
        predictor = predictor_module.EnergyPredictor(
            args.release_dir, args.physics_model,
            ROOT / "apps/energy-predictor/model-manifest.json", xgboost_module=None)
        frozen = release["frozen"]
        client = EnergyServingClient(
            args.serving_endpoint, args.tls_cert, args.tls_key, args.tls_ca,
            {"model_name": "energy-predictor-v1",
             "frozen_sha256": release["frozen_sha256"],
             "xgb_model_sha256": frozen["xgb_model_sha256"],
             "physics_model_sha256": hashlib.sha256(
                 args.physics_model.read_bytes()).hexdigest()},
            predictor.derive,
            fallback_allowance_wh=frozen["uncertainty_calibration"]["allowance_physics_fallback_wh"],
            learned_allowance_wh=frozen["uncertainty_calibration"]["allowance_learned_wh"])
        estimator = route_selector.ServedEstimator(client, fixture)
    return route_selector.select_stage4(
        model, fixture, arm, payload, 0.8,
        estimator=estimator, round_trip_return_payload_kg=return_payload,
        physics_allowance_wh=release["frozen"]["uncertainty_calibration"][
            "allowance_physics_fallback_wh"])


def run_leg(args, name, arm, mission, payload, direction, extra=(), extra_env=None):
    output = args.output / name
    command = [sys.executable, str(Path(__file__).parent / "run_stage4_trial.py"),
               "--source", str(args.source), "--fixture", str(args.fixture),
               "--physics-model", str(args.physics_model),
               "--release-dir", str(args.release_dir),
               "--output", str(output), "--arm", arm, "--mission", mission,
               "--payload", str(payload), "--direction", direction,
               "--speed", str(args.speed)]
    if mission.startswith("roundtrip"):
        command += ["--outbound-payload", "0.5", "--return-payload", "0.0"]
    command += list(extra)
    print(f"  >> {name}: {mission} arm {arm} payload {payload} kg {direction}", flush=True)
    import os
    env = dict(os.environ, **(extra_env or {}))
    log = open(args.output / f"{name}.log", "w")
    try:
        code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                              env=env).returncode
    finally:
        log.close()
    result = json.loads((output / "stage4-result.json").read_text())
    if code != 0 or result["status"] != "PASS":
        raise RuntimeError(f"{name} failed: {result.get('errors')}")
    return result


def svg_chart(deliveries):
    """Predicted versus consumed Wh per delivery as inline SVG bars."""
    width, height, margin = 720, 260, 150
    bar_width = 60
    maximum = max(max(d["predicted"], d["observed"]) for d in deliveries) * 1.25
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}">',
             f'<rect width="{width}" height="{height}" fill="white"/>',
             '<text x="10" y="20" font-size="14" font-family="sans-serif">'
             'Round-trip energy: predicted vs consumed (Wh)</text>']
    scale = (height - 70) / maximum
    for index, delivery in enumerate(deliveries):
        x = margin + index * 190
        for order, (key, color, label) in enumerate(
                [("predicted", "#4477aa", "predicted"), ("observed", "#ee6677", "consumed")]):
            value = delivery[key]
            bar_height = value * scale
            bx = x + order * (bar_width + 8)
            parts.append(f'<rect x="{bx}" y="{height - 40 - bar_height}" '
                         f'width="{bar_width}" height="{bar_height}" fill="{color}"/>')
            parts.append(f'<text x="{bx + bar_width / 2}" y="{height - 44 - bar_height}" '
                         f'font-size="12" text-anchor="middle" font-family="sans-serif">'
                         f'{value:.3f}</text>')
        parts.append(f'<text x="{x + bar_width}" y="{height - 20}" font-size="13" '
                     f'text-anchor="middle" font-family="sans-serif">'
                     f'{delivery["label"]}</text>')
        error = delivery["observed"] - delivery["predicted"]
        parts.append(f'<text x="{x + bar_width}" y="{height - 5}" font-size="11" '
                     f'text-anchor="middle" font-family="sans-serif" fill="#555">'
                     f'error {error:+.4f} Wh</text>')
    parts.append('</svg>')
    return "".join(parts)


def svg_map(fixture):
    """The frozen warehouse route graph as inline SVG."""
    nodes = fixture["geometry"]["nodes"]
    scale, offset_x, offset_y = 22.0, 80.0, 300.0
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="620" height="360" '
             'viewBox="0 0 620 360">',
             '<rect width="620" height="360" fill="white"/>',
             '<text x="10" y="20" font-size="14" font-family="sans-serif">'
             'Frozen warehouse fixture: two ramps, one charger</text>']
    colors = {"A": "#4477aa", "B": "#228833"}

    def position(name):
        x, y, z = nodes[name]
        return offset_x + x * scale, offset_y - y * scale * 2 - z * scale * 4
    for route_name, route in fixture["geometry"]["routes"].items():
        points = [position(n) for n in route]
        path = " ".join(f"{x},{y}" for x, y in points)
        parts.append(f'<polyline points="{path}" fill="none" stroke="{colors[route_name]}" '
                     f'stroke-width="4" opacity="0.75"/>')
        parts.append(f'<text x="{points[0][0] + 6}" y="{points[0][1] - 8}" '
                     f'font-size="12" font-family="sans-serif" fill="{colors[route_name]}">'
                     f'Route {route_name}</text>')
    for name, (x, y, z) in nodes.items():
        px, py = position(name)
        fill = "#ccbb44" if name == "charger" else "white"
        parts.append(f'<circle cx="{px}" cy="{py}" r="7" fill="{fill}" stroke="#333"/>')
        parts.append(f'<text x="{px + 9}" y="{py + 4}" font-size="11" '
                     f'font-family="sans-serif">{name}</text>')
    parts.append('</svg>')
    return "".join(parts)


def snapshot_tags(directory, count=2):
    images = sorted((directory / "rgb-snapshots").glob("frame-*.png")) if directory else []
    chosen = ([images[0], images[-1]] if len(images) >= 2 else images)[:count]
    tags = []
    for image in chosen:
        data = base64.b64encode(image.read_bytes()).decode()
        tags.append(f'<img src="data:image/png;base64,{data}" width="240" '
                    f'style="border:1px solid #ccc; margin:4px"/>')
    return "".join(tags)


def build_html(evidence, fixture):
    deliveries = evidence["deliveries"]
    rows = []
    for delivery in deliveries:
        rows.append(
            f"<tr><td>{delivery['label']}</td><td>{delivery['route']}</td>"
            f"<td>{delivery['predicted']:.4f} Wh</td><td>{delivery['observed']:.4f} Wh</td>"
            f"<td>{delivery['error']:+.4f} Wh ({delivery['error'] / delivery['observed']:+.1%})"
            f"</td><td>{delivery['duration_s']:.0f} s</td>"
            f"<td>{delivery['estimator_mode']}</td></tr>")
    payload_rows = []
    for row in evidence["payload_sensitivity"]:
        payload_rows.append(
            f"<tr><td>{row['payload_kg']:.2f} kg</td><td>{row['route']}</td>"
            f"<td>{row['physics_wh']:.4f} Wh</td><td>{row['served_wh']:.4f} Wh</td>"
            f"<td>{row['predicted_final_soc']:.3f}</td></tr>")
    snapshots = "".join(snapshot_tags(Path(d["snapshots_dir"])) for d in deliveries)
    fallback = evidence["fallback"]
    html = f"""<!DOCTYPE html>
<html><head><title>Energy-aware warehouse delivery demonstration</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 32px; color: #222; }}
h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; }}
table {{ border-collapse: collapse; margin: 12px 0; }}
td, th {{ border: 1px solid #bbb; padding: 6px 12px; font-size: 13px; }}
th {{ background: #f0f0f0; }}
.note {{ background: #fff8e1; border-left: 4px solid #f0a500; padding: 10px 14px;
         font-size: 13px; }}
.panel {{ border: 1px solid #ddd; border-radius: 8px; padding: 14px; margin: 12px 0; }}
</style></head><body>
<h1>Energy-aware warehouse delivery demonstration</h1>
<p>{evidence['date']} &middot; frozen warehouse fixture v1 &middot; modeled simulated energy
under the frozen Phase 1 accounting assumptions</p>
<h2>1. Warehouse briefing</h2>
<div class="panel">{svg_map(fixture)}</div>
<p>Battery 24 Wh at 80% state of charge, 20% reserve after the mission plus charger
access, 900 s one-way / 1800 s round-trip deadlines, planned speed 0.10 m/s.
Both candidate corridors are qualified; the selection below is the arm C
(learned) planning view for the loaded round trip.</p>
<h2>2. Three matched deliveries (loading &rarr; transfer loaded, return empty)</h2>
<table><tr><th>Delivery</th><th>Route</th><th>Predicted</th><th>Consumed</th>
<th>Prediction error</th><th>Duration</th><th>Estimator</th></tr>
{''.join(rows)}</table>
<div class="panel">{svg_chart(deliveries)}</div>
<h2>3. Robot camera snapshots (arm C delivery)</h2>
<div>{snapshots}</div>
<h2>4. Payload sensitivity (served planning view, one-way loading &rarr; transfer)</h2>
<table><tr><th>Payload</th><th>Selected route</th><th>Physics estimate</th>
<th>Learned estimate</th><th>Predicted final SOC</th></tr>
{''.join(payload_rows)}</table>
<p>The same corridor remains the energy-optimal choice at every payload in this
same-surface fixture; the learned estimator sharpens the energy estimate, not
the route ranking.</p>
<h2>5. Resilience: serving endpoint unavailable</h2>
<div class="panel">Before a new route decision the energy endpoint was made
unreachable. The planner activated its documented fallback to the local
calibrated physics model with the conservative uncertainty allowance, selected
route <b>{fallback['route']}</b>, and completed the mission
({fallback['observed_wh']:.4f} Wh consumed, {fallback['duration_s']:.0f} s,
estimator mode <b>{fallback['estimator_mode']}</b>). No mission starts on an
unvalidated prediction.</div>
<div class="note"><b>Scope.</b> Simulation demonstration over modeled energy.
The consumed values are outputs of the frozen telemetry model, not physical
battery measurements; no energy saving is claimed. Route A is both the
shortest and the energy-optimal corridor in this fixture, so the three arms
select the same route by design of the physics, not by failure.</div>
</body></html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--speed", type=float, default=0.1)
    parser.add_argument("--serving-endpoint",
                        default="https://energy-predictor-v1-tls.semantic-model-serving.svc:8443")
    parser.add_argument("--tls-cert", type=Path, default=Path("/tls/tls.crt"))
    parser.add_argument("--tls-key", type=Path, default=Path("/tls/tls.key"))
    parser.add_argument("--tls-ca", type=Path, default=Path("/tls/client-ca.crt"))
    parser.add_argument("--hold-file", type=Path, default=None,
                        help="pause delivery 1 before dispatch until this file exists")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(args.fixture.read_text())
    model = PhysicsModel.load(args.physics_model)
    release = json.loads((args.release_dir / "release.json").read_text())
    evidence = {"date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                "deliveries": [], "payload_sensitivity": [], "fallback": None}

    print("=== Energy-aware warehouse delivery demonstration ===", flush=True)
    print("[1] Briefing: candidate corridors and estimates", flush=True)
    briefing = {}
    for arm, label in ARMS:
        view = select_view(model, fixture, release, args, arm, 0.5, return_payload=0.0)
        briefing[arm] = view
        route = view["selected_route"]
        row = view["routes"][route]
        print(f"    arm {arm} ({label}): selects route {route} "
              f"({row['distance_m']:.0f} m, predicted round trip "
              f"{row['round_trip_predicted_total_wh']:.4f} Wh, "
              f"estimator {row['estimator_mode']})", flush=True)
    evidence["briefing"] = briefing

    print("[2] Matched deliveries (round trips, 0.5 kg out, empty back)", flush=True)
    for index, (arm, label) in enumerate(ARMS, start=1):
        hold_env = ({"WAREHOUSE_DEMO_HOLD": str(args.hold_file.resolve())}
                    if index == 1 and args.hold_file else None)
        if index == 1 and args.hold_file:
            print(f"    [HOLD] delivery 1 will wait before dispatch until "
                  f"'{args.hold_file}' exists (robot visible at the loading station)",
                  flush=True)
        out = run_leg(args, f"delivery{index}-arm{arm}-out", arm, "roundtrip-out",
                      0.5, "up", extra_env=hold_env)
        back = run_leg(args, f"delivery{index}-arm{arm}-return", arm, "roundtrip-return",
                       0.0, "down")
        predicted = (out["prediction"]["predicted_mission_wh"]
                     + back["prediction"]["predicted_mission_wh"])
        observed = (out["observation"]["observed_mission_wh"]
                    + back["observation"]["observed_mission_wh"])
        duration = (out["observation"]["observed_duration_s"]
                    + back["observation"]["observed_duration_s"])
        print(f"    delivery {index} (arm {arm}, {label}): route {out['selected_route']}, "
              f"predicted {predicted:.4f} Wh, consumed {observed:.4f} Wh, "
              f"{duration:.0f} s", flush=True)
        evidence["deliveries"].append({
            "label": f"Delivery {index}: arm {arm}", "arm": arm,
            "route": out["selected_route"], "predicted": round(predicted, 6),
            "observed": round(observed, 6), "error": round(observed - predicted, 6),
            "duration_s": round(duration, 1),
            "estimator_mode": out["prediction"]["estimator_mode"],
            "snapshots_dir": str(args.output / f"delivery{index}-arm{arm}-out"),
            "final_soc": back["observation"]["observed_final_soc"]})

    print("[3] Payload sensitivity (served planning view)", flush=True)
    for payload in (0.0, 0.25, 0.5):
        view = select_view(model, fixture, release, args, "C", payload)
        route = view["selected_route"]
        rows = view["routes"]
        physics_view = route_selector.select_stage4(model, fixture, "B", payload, 0.8)
        print(f"    payload {payload:.2f} kg: selects route {route} "
              f"(physics {physics_view['routes'][route]['predicted_mission_wh']:.4f} Wh, "
              f"served {rows[route]['predicted_mission_wh']:.4f} Wh)", flush=True)
        evidence["payload_sensitivity"].append({
            "payload_kg": payload, "route": route,
            "physics_wh": physics_view["routes"][route]["predicted_mission_wh"],
            "served_wh": rows[route]["predicted_mission_wh"],
            "predicted_final_soc": rows[route]["predicted_final_soc"]})

    print("[4] Resilience: serving endpoint unavailable (physics fallback)", flush=True)
    fallback = run_leg(args, "fallback-armC-serving-unavailable", "C", "oneway",
                       0.5, "up", extra=["--serving-unavailable"])
    evidence["fallback"] = {
        "route": fallback["selected_route"],
        "observed_wh": fallback["observation"]["observed_mission_wh"],
        "duration_s": fallback["observation"]["observed_duration_s"],
        "estimator_mode": fallback["prediction"]["estimator_mode"]}
    print(f"    fallback delivery: route {fallback['selected_route']}, "
          f"{evidence['fallback']['observed_wh']:.4f} Wh, "
          f"estimator {evidence['fallback']['estimator_mode']}", flush=True)

    evidence["scope"] = ("simulation demonstration over modeled energy; no physical "
                         "battery-saving claim")
    (args.output / "demo-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (args.output / "demo-summary.html").write_text(build_html(evidence, fixture))
    print("=== demonstration complete: demo-evidence.json, demo-summary.html ===",
          flush=True)


if __name__ == "__main__":
    main()
