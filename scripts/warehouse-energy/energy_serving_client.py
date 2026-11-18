#!/usr/bin/env python3
"""Robot-side client for the energy-predictor serving endpoint.

Batches segment planning inputs into one bounded request, mutually
authenticated. Every response is validated fail-closed before use: schema,
status, echoed request identity and planning generation, deployment
identity (model name, frozen release hash, artifact digests), allowances,
segment completeness, and finite values. Any transport failure, HTTP
error, or validation failure activates the local calibrated physics
predictor with the frozen fallback uncertainty allowance. Results are
cached by the inputs that affect energy (model version and segment
inputs); responses from an obsolete planning generation are rejected.
"""
import json
import math
import ssl
import time
import urllib.error
import urllib.request
import uuid

SCHEMA = "energy-prediction/v1"
MODEL_NAME = "energy-predictor-v1"
GRAPH_VERSION = "warehouse-fixture-v1"
REQUEST_TIMEOUT_S = 1.0
CACHE_LIMIT = 64


class EnergyServingError(Exception):
    pass


def local_physics(derive, segments):
    """Physics-only fallback using the shared frozen derivation."""
    results = []
    for segment in segments:
        derived = derive(segment)
        results.append({"physics_wh": derived["physics_wh"],
                        "planned_duration_s": derived["planned_duration_s"],
                        "residual_wh": 0.0,
                        "predicted_wh": derived["physics_wh"],
                        "bounds_rejected": False})
    return results


class EnergyServingClient:
    def __init__(self, endpoint, tls_cert, tls_key, ca, expected_identity,
                 derive, fallback_allowance_wh, learned_allowance_wh,
                 timeout_s=REQUEST_TIMEOUT_S):
        self.endpoint = endpoint.rstrip("/") + f"/v1/models/{MODEL_NAME}:predict"
        self.expected = dict(expected_identity)
        self.derive = derive
        self.fallback_allowance_wh = float(fallback_allowance_wh)
        self.learned_allowance_wh = float(learned_allowance_wh)
        self.timeout_s = float(timeout_s)
        self.cert_path, self.key_path, self.ca_path = tls_cert, tls_key, ca
        self._context = None
        self.cache = {}
        self._context = None
        self.cache = {}

    @property
    def context(self):
        """Lazy mTLS context: the physics fallback path never needs TLS."""
        if self._context is None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.check_hostname = False  # cluster-local service, CA-pinned
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(self.ca_path)
            context.load_cert_chain(self.cert_path, self.key_path)
            self._context = context
        return self._context

    def validate_response(self, response, request_id, generation, count):
        if not isinstance(response, dict):
            raise EnergyServingError("response is not an object")
        if response.get("schema") != SCHEMA or response.get("status") != "ok":
            raise EnergyServingError("response schema/status mismatch")
        if response.get("request_id") != request_id:
            raise EnergyServingError("response request identity mismatch")
        if response.get("planning_generation") != generation:
            raise EnergyServingError("stale planning generation")
        if response.get("model_version") != MODEL_NAME:
            raise EnergyServingError("wrong model version")
        deployment = response.get("deployment")
        if not isinstance(deployment, dict):
            raise EnergyServingError("deployment identity missing")
        for key in ("model_name", "frozen_sha256", "xgb_model_sha256",
                    "physics_model_sha256"):
            if deployment.get(key) != self.expected[key]:
                raise EnergyServingError(f"deployment identity mismatch: {key}")
        allowances = response.get("allowances")
        if not isinstance(allowances, dict):
            raise EnergyServingError("allowances missing")
        if abs(float(allowances["physics_fallback_wh"]) - self.fallback_allowance_wh) > 1e-12:
            raise EnergyServingError("fallback allowance mismatch")
        if abs(float(allowances["learned_wh"]) - self.learned_allowance_wh) > 1e-12:
            raise EnergyServingError("learned allowance mismatch")
        segments = response.get("segments")
        if not isinstance(segments, list) or len(segments) != count:
            raise EnergyServingError("segment count mismatch")
        for segment in segments:
            for key in ("physics_wh", "residual_wh", "predicted_wh",
                        "planned_duration_s"):
                value = segment.get(key)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise EnergyServingError(f"non-finite {key}")
            if segment.get("bounds_rejected") not in (True, False):
                raise EnergyServingError("bounds flag missing")
        return response

    def predict_batch(self, segments, planning_generation,
                      robot_config="warehouse-bounded-differential-drive-v1",
                      use_cache=True):
        """Serve or fall back; never raises for transport/service failures."""
        key = (MODEL_NAME, json.dumps(segments, sort_keys=True))
        cached = self.cache.get(key) if use_cache else None
        if cached is not None:
            return {"mode": "served", "cached": True,
                    "planning_generation": planning_generation,
                    "segments": cached["segments"],
                    "allowances": cached["allowances"]}
        request_id = str(uuid.uuid4())
        request = {"schema": SCHEMA, "request_id": request_id,
                   "robot": {"config": robot_config},
                   "graph_version": GRAPH_VERSION, "model_version": MODEL_NAME,
                   "planning_generation": planning_generation,
                   "segments": list(segments)}
        body = json.dumps(request).encode()
        headers = {"Content-Type": "application/json",
                   "Content-Length": str(len(body))}
        started = time.monotonic()
        try:
            req = urllib.request.Request(self.endpoint, data=body,
                                         headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout_s,
                                        context=self.context) as stream:
                if stream.status != 200:
                    raise EnergyServingError(f"HTTP {stream.status}")
                raw = stream.read()
            response = self.validate_response(json.loads(raw), request_id,
                                              planning_generation, len(segments))
        except Exception:
            # Documented fallback: local calibrated physics with the frozen
            # conservative allowance. No prediction from a failed exchange.
            return {"mode": "fallback", "cached": False,
                    "planning_generation": planning_generation,
                    "segments": local_physics(self.derive, segments),
                    "allowances": {"learned_wh": self.fallback_allowance_wh,
                                   "physics_fallback_wh": self.fallback_allowance_wh}}
        if len(self.cache) >= CACHE_LIMIT:
            self.cache.clear()
        if use_cache:
            self.cache[key] = {"segments": response["segments"],
                               "allowances": response["allowances"]}
        return {"mode": "served", "cached": False,
                "planning_generation": planning_generation,
                "segments": response["segments"],
                "allowances": response["allowances"],
                "latency_s": time.monotonic() - started}
