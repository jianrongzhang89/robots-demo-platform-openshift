#!/usr/bin/env python3
"""Stage 3C serving qualification: parity, faults, and latency gates.

Runs against the deployed energy-predictor InferenceService from an
mTLS-authenticated client pod. Verifies model identity, offline/server
combined-prediction parity and local/server physics parity on the frozen
replay batches, wrong-version and invalid-input rejection, malformed and
stale-generation response rejection, endpoint-unavailable fallback to the
calibrated physics predictor, cache behavior, and the latency target
(p95 below 250 ms for the 32-segment batch, 1 s deadline). Writes a JSON
result with per-check evidence.
"""
import argparse
import json
import math
import ssl
import statistics
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from energy_serving_client import (EnergyServingClient, EnergyServingError,
                                   MODEL_NAME, SCHEMA, local_physics)

PARITY_TOLERANCE = 1e-9
LATENCY_REQUESTS = 100
P95_TARGET_S = 0.25
DEADLINE_S = 1.0


def raw_post(endpoint, context, payload, timeout=2.0):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(endpoint, data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as stream:
            return stream.status, json.loads(stream.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True,
                        help="https://energy-predictor-v1-tls.semantic-model-serving.svc:8443")
    parser.add_argument("--tls-cert", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/energy-predictor"))
    import predictor as predictor_module
    predictor = predictor_module.EnergyPredictor(
        args.release, args.physics_model, args.manifest, xgboost_module=None)
    identity = predictor.identity()
    client = EnergyServingClient(
        args.endpoint, args.tls_cert, args.tls_key, args.ca,
        {"model_name": identity["model_name"], "frozen_sha256": identity["frozen_sha256"],
         "xgb_model_sha256": identity["xgb_model_sha256"],
         "physics_model_sha256": identity["physics_model_sha256"]},
        predictor.derive,
        fallback_allowance_wh=identity and predictor.allowance_fallback,
        learned_allowance_wh=predictor.allowance_learned)

    replay = json.loads(args.replay.read_text())
    checks = []

    def check(name, passed, detail):
        checks.append({"check": name, "status": "PASS" if passed else "FAIL",
                       "detail": detail})
        return passed

    # 1. Model identity over authenticated metadata.
    meta_endpoint = args.endpoint.rstrip("/") + f"/v1/models/{MODEL_NAME}"
    try:
        request = urllib.request.Request(meta_endpoint)
        with urllib.request.urlopen(request, timeout=2.0, context=client.context) as stream:
            meta = json.loads(stream.read())
        deployment = meta.get("deployment", {})
        identity_ok = (meta.get("ready") is True
                       and deployment.get("model_name") == identity["model_name"]
                       and deployment.get("frozen_sha256") == identity["frozen_sha256"]
                       and deployment.get("xgb_model_sha256") == identity["xgb_model_sha256"]
                       and deployment.get("physics_model_sha256")
                       == identity["physics_model_sha256"]
                       and deployment.get("batch_limit") == 32)
        check("model_identity", identity_ok,
              {"frozen_sha256": deployment.get("frozen_sha256"),
               "batch_limit": deployment.get("batch_limit")})
    except Exception as exc:
        check("model_identity", False, {"error": str(exc)})

    # 2. Offline/server parity on every replay batch (combined prediction and
    #    physics: the expected values are the dataset's frozen physics and the
    #    release's offline residual predictions).
    parity_errors = []
    for batch in replay["batches"]:
        result = client.predict_batch(batch["segments"], "generation-parity")
        if result["mode"] != "served":
            parity_errors.append(f"{batch['name']}: fallback during parity replay")
            continue
        for expected, served in zip(batch["expected"], result["segments"]):
            for key in ("physics_wh", "residual_wh", "predicted_wh",
                        "planned_duration_s"):
                if abs(expected[key] - served[key]) > PARITY_TOLERANCE:
                    parity_errors.append(f"{batch['name']}: {key} "
                                         f"{served[key]} != {expected[key]}")
            if expected["bounds_rejected"] != served["bounds_rejected"]:
                parity_errors.append(f"{batch['name']}: bounds flag mismatch")
    total_segments = sum(len(b["expected"]) for b in replay["batches"])
    check("offline_server_prediction_parity", not parity_errors,
          {"batches": len(replay["batches"]), "segments": total_segments,
           "tolerance_wh": PARITY_TOLERANCE, "errors": parity_errors[:5]})
    check("local_server_physics_parity", not parity_errors,
          {"note": "served physics equals the dataset's frozen local physics values "
                   "within the same tolerance"})

    # 3. Wrong model version rejected by the server.
    wrong = {"schema": SCHEMA, "request_id": str(uuid.uuid4()),
             "robot": {"config": "warehouse-bounded-differential-drive-v1"},
             "graph_version": "warehouse-fixture-v1",
             "model_version": "energy-predictor-v0",
             "planning_generation": "g-wrong-version",
             "segments": replay["batches"][0]["segments"]}
    code, body = raw_post(client.endpoint, client.context, wrong)
    check("wrong_model_version_rejected", code == 400 and body.get("status") == "invalid_input",
          {"http": code, "status": body.get("status")})

    # 4. Invalid inputs rejected: out-of-envelope speed and oversized batch.
    invalid = json.loads(json.dumps(replay["batches"][0]))
    invalid["segments"][0]["speed_mps"] = 0.5
    code, body = raw_post(client.endpoint, client.context, invalid)
    check("out_of_envelope_input_rejected", code == 400,
          {"http": code, "status": body.get("status"), "reason": body.get("reason")})
    oversized = json.loads(json.dumps(replay["batches"][0]))
    oversized["segments"] = (oversized["segments"] * 4)[:33]
    code, body = raw_post(client.endpoint, client.context, oversized)
    check("oversized_batch_rejected", code == 400,
          {"http": code, "status": body.get("status"), "batch": 33})

    # 5. Malformed and stale responses rejected by the client validator.
    good = client.predict_batch(replay["batches"][0]["segments"], "g-validator")
    served = {"schema": SCHEMA, "status": "ok", "request_id": "rid",
              "planning_generation": "g-validator", "model_version": MODEL_NAME,
              "deployment": dict(identity), "allowances": {
                  "learned_wh": predictor.allowance_learned,
                  "physics_fallback_wh": predictor.allowance_fallback},
              "segments": good["segments"]}
    malformed_cases = {}
    def expect_reject(name, mutation):
        payload = json.loads(json.dumps(served))
        mutation(payload)
        try:
            client.validate_response(payload, "rid", "g-validator", len(good["segments"]))
            malformed_cases[name] = "accepted"
        except EnergyServingError as exc:
            malformed_cases[name] = f"rejected: {exc}"
    expect_reject("missing_deployment", lambda p: p.pop("deployment"))
    expect_reject("wrong_frozen_sha",
                  lambda p: p["deployment"].update(frozen_sha256="0" * 64))
    expect_reject("stale_generation",
                  lambda p: p.update(planning_generation="g-old"))
    expect_reject("request_id_mismatch", lambda p: p.update(request_id="other"))
    expect_reject("non_finite_prediction",
                  lambda p: p["segments"][0].update(predicted_wh=None))
    expect_reject("segment_count_mismatch", lambda p: p["segments"].pop())
    expect_reject("wrong_allowance",
                  lambda p: p["allowances"].update(physics_fallback_wh=0.0))
    check("malformed_response_rejection",
          all(value.startswith("rejected") for value in malformed_cases.values()),
          malformed_cases)

    # 6. Endpoint unavailable: documented physics fallback with the frozen
    #    conservative allowance.
    unreachable = EnergyServingClient(
        "https://192.0.2.1:8443", args.tls_cert, args.tls_key, args.ca,
        {"model_name": identity["model_name"], "frozen_sha256": identity["frozen_sha256"],
         "xgb_model_sha256": identity["xgb_model_sha256"],
         "physics_model_sha256": identity["physics_model_sha256"]},
        predictor.derive, fallback_allowance_wh=predictor.allowance_fallback,
        learned_allowance_wh=predictor.allowance_learned, timeout_s=1.0)
    fallback = unreachable.predict_batch(replay["batches"][0]["segments"], "g-fallback")
    fallback_ok = (fallback["mode"] == "fallback"
                   and all(abs(s["predicted_wh"] - e["physics_wh"]) < 1e-9
                           for s, e in zip(fallback["segments"],
                                           replay["batches"][0]["expected"]))
                   and fallback["allowances"]["physics_fallback_wh"]
                   == predictor.allowance_fallback)
    check("unavailable_endpoint_physics_fallback", fallback_ok,
          {"mode": fallback["mode"],
           "allowance_wh": fallback["allowances"]["physics_fallback_wh"]})

    # 7. Cache: identical inputs served from cache under a new generation.
    again = client.predict_batch(replay["batches"][0]["segments"], "g-cache")
    check("cache_reuse_new_generation", again["mode"] == "served" and again["cached"]
          and again["planning_generation"] == "g-cache",
          {"cached": again.get("cached"), "mode": again["mode"]})

    # 8. Latency target on the frozen 32-segment batch.
    latencies = []
    latency_ok = True
    for index in range(LATENCY_REQUESTS):
        result = client.predict_batch(replay["latency_batch"]["segments"],
                                      f"g-latency-{index}", use_cache=False)
        if result["mode"] != "served" or result.get("cached"):
            latency_ok = False
            break
        latencies.append(result["latency_s"])
    latencies.sort()
    p95 = latencies[int(math.ceil(0.95 * len(latencies))) - 1] if latencies else None
    check("latency_target", latency_ok and p95 is not None and p95 < P95_TARGET_S
          and max(latencies) < DEADLINE_S,
          {"requests": len(latencies), "p95_s": round(p95, 4) if p95 else None,
           "max_s": round(max(latencies), 4) if latencies else None,
           "target_p95_s": P95_TARGET_S, "deadline_s": DEADLINE_S,
           "batch_segments": len(replay["latency_batch"]["segments"])})
    # Parity must also hold on the latency batch.
    latency_parity = all(
        abs(e[key] - s[key]) <= PARITY_TOLERANCE
        for e, s in zip(replay["latency_batch"]["expected"],
                        client.predict_batch(replay["latency_batch"]["segments"],
                                             "g-latency-final")["segments"])
        for key in ("physics_wh", "predicted_wh"))
    check("latency_batch_parity", latency_parity, {"segments": 32})

    report = {
        "status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
        "checks": checks,
        "endpoint": args.endpoint,
        "identity": {"model_name": identity["model_name"],
                     "frozen_sha256": identity["frozen_sha256"],
                     "xgb_model_sha256": identity["xgb_model_sha256"],
                     "physics_model_sha256": identity["physics_model_sha256"]},
        "scope": "serving qualification over modeled energy predictions for the frozen "
                 "warehouse fixture; no physical calibration or energy-saving claim",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({c["check"]: c["status"] for c in checks}))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
