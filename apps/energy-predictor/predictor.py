#!/usr/bin/env python3
"""Frozen energy predictor: feature derivation, physics, residual, bounds.

Reproduces the Stage 3A dataset builder's per-segment derivation exactly
(same physics code, same profile sampling, same rounding) so that served
predictions match the model's training features bit for bit. Validates
planning-time inputs against the frozen envelope, computes the physics
baseline with the frozen Stage 2 model, applies the frozen XGBoost residual
with the physical-bounds rule, and returns the uncertainty allowances from
the frozen release. No request-time training or state.
"""
import hashlib
import json
import math
from pathlib import Path

import physics_model as shared

MODEL_NAME = "energy-predictor-v1"
SCHEMA = "energy-prediction/v1"
GRAPH_VERSION = "warehouse-fixture-v1"
BATCH_LIMIT = 32
MAX_WIRE_BYTES = 1 << 20

SUPPORTED_ROBOTS = {"warehouse-bounded-differential-drive-v1": (1.6, 2.2)}
SEGMENT_BOUNDS = {
    "length_m": (0.0, 100.0, True, False),
    "ramp_run_m": (1.0, 50.0, True, False),
    "signed_rise_m": (-0.25, 0.25, True, True),
    "speed_mps": (0.02, 0.10, True, True),
    "heading_change_rad": (-math.pi, math.pi, True, True),
    "planned_stops": (0, 3, True, True),
    "planned_dwell_s": (0.0, 600.0, True, True),
    "total_mass_kg": (1.6, 2.2, True, True),
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class InputError(ValueError):
    pass


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_segment(segment):
    if not isinstance(segment, dict):
        raise InputError("segment must be an object")
    if segment.get("class") not in ("scripted", "nav"):
        raise InputError("unsupported segment class")
    for key, (low, high, low_inclusive, high_inclusive) in SEGMENT_BOUNDS.items():
        value = segment.get(key)
        if key == "ramp_run_m" and value is None:
            continue
        if not finite_number(value):
            raise InputError(f"{key} must be a finite number")
        if not (low <= value if low_inclusive else low < value):
            raise InputError(f"{key} below the frozen envelope")
        if not (value <= high if high_inclusive else value < high):
            raise InputError(f"{key} above the frozen envelope")
    if segment.get("ramp_run_m") is None:
        if segment["signed_rise_m"] != 0.0:
            raise InputError("level segment must not declare a rise")
    else:
        if abs(segment["signed_rise_m"]) < 1e-12:
            raise InputError("ramp segment must declare a nonzero rise")
    return segment


def validate_request(request, robots=SUPPORTED_ROBOTS):
    if not isinstance(request, dict):
        raise InputError("object required")
    if request.get("schema") != SCHEMA:
        raise InputError("unsupported schema")
    if request.get("model_version") != MODEL_NAME:
        raise InputError("model version mismatch")
    if request.get("graph_version") != GRAPH_VERSION:
        raise InputError("graph version mismatch")
    if not isinstance(request.get("request_id"), str) or not request["request_id"]:
        raise InputError("request_id required")
    if not isinstance(request.get("planning_generation"), str) or \
            not request["planning_generation"]:
        raise InputError("planning_generation required")
    robot = request.get("robot")
    if not isinstance(robot, dict) or robot.get("config") not in robots:
        raise InputError("unsupported robot configuration")
    segments = request.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= BATCH_LIMIT:
        raise InputError(f"batch must contain 1 to {BATCH_LIMIT} segments")
    for segment in segments:
        validate_segment(segment)
    return segments


class EnergyPredictor:
    """Loads the frozen release and serves per-segment predictions."""

    def __init__(self, release_dir, physics_model_path, manifest_path,
                 xgboost_module=None):
        self.release_dir = Path(release_dir)
        self.release = json.loads((self.release_dir / "release.json").read_text())
        frozen = self.release["frozen"]
        self.frozen = frozen
        self.physics = shared.PhysicsModel(json.loads(Path(physics_model_path).read_text()))
        self.manifest = json.loads(Path(manifest_path).read_text())
        # Fail closed on any artifact digest mismatch.
        if sha256(self.release_dir / "xgb-model.json") != frozen["xgb_model_sha256"]:
            raise ValueError("XGBoost artifact digest mismatch")
        if sha256(self.release_dir / "linear-model.json") != frozen["linear_model_sha256"]:
            raise ValueError("linear artifact digest mismatch")
        if sha256(physics_model_path) != self.manifest["physics_model_sha256"]:
            raise ValueError("physics model digest mismatch")
        if frozen["schema_version"] != self.manifest["release_schema"] or \
                frozen["uncertainty_calibration"]["allowance_learned_wh"] is None:
            raise ValueError("release/manifest mismatch")
        self.allowance_learned = frozen["uncertainty_calibration"]["allowance_learned_wh"]
        self.allowance_fallback = frozen["uncertainty_calibration"]["allowance_physics_fallback_wh"]
        self.xgboost = xgboost_module
        self.booster = None

    def load_booster(self):
        """Load the XGBoost booster; single-threaded, no request-time training."""
        if self.booster is None:
            if self.xgboost is None:
                raise RuntimeError("xgboost unavailable")
            booster = self.xgboost.Booster()
            booster.load_model(str(self.release_dir / "xgb-model.json"))
            booster.set_param("nthread", 1)
            self.booster = booster
        return self.booster

    def identity(self):
        return {
            "schema": "energy-deployment/v1",
            "model_name": MODEL_NAME,
            "release_schema": self.frozen["schema_version"],
            "frozen_sha256": self.release["frozen_sha256"],
            "xgb_model_sha256": self.frozen["xgb_model_sha256"],
            "linear_model_sha256": self.frozen["linear_model_sha256"],
            "physics_model_sha256": self.manifest["physics_model_sha256"],
            "feature_schema": self.frozen["feature_schema"]["names"],
            "batch_limit": BATCH_LIMIT,
            "graph_version": GRAPH_VERSION,
            "versions": self.frozen["environment"],
        }

    def derive(self, segment):
        """Feature derivation and physics, matching the dataset builder exactly."""
        length = float(segment["length_m"])
        run = segment.get("ramp_run_m")
        rise = float(segment["signed_rise_m"])
        speed = float(segment["speed_mps"])
        turn = float(segment["heading_change_rad"])
        dwell = float(segment["planned_dwell_s"])
        mass = float(segment["total_mass_kg"])
        if run is None:
            def elevation(u):
                return 0.0
            ascent = descent = 0.0
            max_grade = 0.0
        else:
            run = float(run)
            magnitude = abs(rise)

            def elevation(u):
                # Ramp meshes begin at the lower node; flip for descent.
                return shared.ramp_height(run - u if rise < 0 else u, run, magnitude)
            # Forty-step profile sampling, as in the Stage 3A builder.
            steps = 40
            previous = magnitude if rise < 0 else 0.0
            ascent = descent = max_grade = 0.0
            for step in range(1, steps + 1):
                u = length * step / steps
                local = run - u if rise < 0 else u
                height = shared.ramp_height(local, run, magnitude)
                change = height - previous if rise > 0 else previous - height
                ascent += max(change, 0.0)
                descent += max(-change, 0.0)
                max_grade = max(max_grade, abs(change) / (length / steps))
                previous = height
        # Sample order matches the Stage 3A builder's per-segment integration
        # (edge samples, then rotation, then dwell) so float sums are identical.
        samples = (self.physics.stop_to_stop(length, elevation, speed)
                   + self.physics.rotation(turn)
                   + self.physics.dwell(dwell))
        integrated = self.physics.integrate(samples, mass)
        features = [
            round(length, 3),
            round(run, 3) if run is not None else 0.0,
            round(ascent, 4),
            round(descent, 4),
            round(max_grade, 6),
            round(rise / length, 6),
            round(abs(turn), 4),
            float(segment["speed_mps"]),
            float(segment.get("planned_stops", 0)),
            round(dwell, 2),
            mass,
            round(integrated["wh"], 6),
            round(integrated["duration_s"], 2),
            1.0 if segment["class"] == "nav" else 0.0,
        ]
        return {"features": features, "physics_wh": round(integrated["wh"], 6),
                "planned_duration_s": round(integrated["duration_s"], 2)}

    def predict_segments(self, segments):
        """Per-segment physics, residual, and combined estimate with bounds."""
        derived = [self.derive(segment) for segment in segments]
        booster = self.load_booster()
        corrections = booster.predict(booster_make_matrix(self.xgboost,
                                                          [d["features"] for d in derived]))
        results = []
        for item, correction in zip(derived, corrections):
            correction = float(correction)
            physics = item["physics_wh"]
            combined = physics + correction
            rejected = combined < 0.0 or abs(correction) > physics
            results.append({
                "physics_wh": physics,
                "planned_duration_s": item["planned_duration_s"],
                "residual_wh": round(correction, 9),
                "predicted_wh": round(physics if rejected else combined, 9),
                "bounds_rejected": bool(rejected),
            })
        return results


def booster_make_matrix(xgboost_module, feature_rows):
    return xgboost_module.DMatrix(feature_rows)
