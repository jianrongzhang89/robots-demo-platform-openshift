#!/usr/bin/env python3
"""Compare frozen local responses with the isolated HTTPS endpoint (no ROS).

Manifest rows contain case, request, request_sha256, local_response and
local_response_sha256. Relative files resolve from the manifest directory.
Only hashes and per-frame scores are written to the report, not RGB or masks.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import ssl
import sys
import time
from urllib.parse import urlsplit

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/semantic-model-server"), str(ROOT / "apps/semantic-perception")]
from artifact import verify_deployment_identity
from inference_contract import MAX_WIRE_BYTES, decode_response, dumps, loads, validate_request


def compare(request, local, remote):
    left = decode_response(request, local)[0] != 0
    right = decode_response(request, remote)[0] != 0
    union = int(np.logical_or(left, right).sum())
    iou = float(np.logical_and(left, right).sum() / union) if union else 1.0
    difference = abs(float(left.mean()) - float(right.mean()))
    agreement = bool(left.any()) == bool(right.any())
    return {"union_mask_iou": iou, "empty_agreement": agreement,
            "occupied_fraction_difference": difference,
            "passed": iou >= 0.99 and agreement and difference <= 0.005}


def checked_file(root, row, field):
    data = (root / row[field]).read_bytes()
    if hashlib.sha256(data).hexdigest() != row[field + "_sha256"]:
        raise ValueError("frozen replay file checksum mismatch")
    return loads(data)


def replay(args):
    manifest_bytes = args.manifest.read_bytes()
    manifest = loads(manifest_bytes)
    rows = manifest["frames"]
    if not rows or not {"mat", "absent-target", "empty-mask"} <= {r["case"] for r in rows}:
        raise ValueError("frozen mat, absent-target and empty-mask cases required")
    identity = loads(args.identity.read_bytes())
    # The local baseline must have a separately recorded matching model/precision.
    for key in ("weights_sha256", "source_revision", "versions", "precision", "prompt", "threshold", "policy"):
        if manifest["local_identity"][key] != identity[key]:
            raise ValueError("local/served baseline configuration mismatch: " + key)
    endpoint = urlsplit(args.endpoint)
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.query or endpoint.fragment:
        raise ValueError("verified HTTPS endpoint required")
    if endpoint.path.rstrip("/"):
        raise ValueError("endpoint must be the origin without a path")
    context = ssl.create_default_context(cafile=str(args.ca))
    context.load_cert_chain(args.cert, args.key)
    connection = http.client.HTTPSConnection(endpoint.hostname, endpoint.port or 443, context=context, timeout=5)
    results = []
    try:
        connection.request("GET", "/v1/models/sam3-mat-v1")
        meta = connection.getresponse()
        data = meta.read(MAX_WIRE_BYTES + 1)
        if meta.status != 200:
            raise ValueError("model is not ready")
        verify_deployment_identity(loads(data)["deployment"], identity)
        for row in rows:
            item = {"case": row["case"], "request_sha256": row["request_sha256"]}
            try:
                request = checked_file(args.manifest.parent, row, "request")
                local = checked_file(args.manifest.parent, row, "local_response")
                validate_request(request)
                baseline = decode_response(request, local)[0]
                if row["case"] == "empty-mask" and baseline.any():
                    raise ValueError("empty-mask baseline is not empty")
                if row["case"] == "mat" and not baseline.any():
                    raise ValueError("mat baseline is empty")
                started = time.monotonic()
                connection.request("POST", "/v1/models/sam3-mat-v1:predict", dumps(request),
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                raw = response.read(MAX_WIRE_BYTES + 1)
                item.update(http_status=response.status,
                            round_trip_ms=(time.monotonic() - started) * 1000,
                            response_sha256=hashlib.sha256(raw).hexdigest())
                if response.status != 200:
                    item.update(passed=False, error="non-success HTTP response")
                else:
                    remote = loads(raw)
                    verify_deployment_identity(remote.get("deployment"), identity)
                    item.update(compare(request, local, remote))
            except Exception as error:
                item.update(passed=False, error_type=type(error).__name__)
                connection.close()
            results.append(item)
    finally:
        connection.close()
    return {"scope": "G1 backend parity only; not recognition or live navigation qualification",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_set_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "deployment": identity,
        "thresholds": {"union_mask_iou_min": 0.99, "empty_agreement": 1.0,
                       "occupied_fraction_difference_max": 0.005},
        "sample_count": len(results), "frames": results,
        "status": "PASS" if all(r["passed"] for r in results) else "FAIL"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("manifest", "identity", "ca", "cert", "key", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a new output path; preserve earlier attempts")
    try:
        report = replay(args)
    except Exception as error:
        report = {"status": "FAIL", "error_type": type(error).__name__,
                  "reason": "Replay failed; check frozen inputs, TLS, identity, and endpoint health."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "output": str(args.output)}))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
