"""ROS-independent, bounded JSON wire contract and client-side result guard.

Only remaining budget crosses the wire. Absolute monotonic deadlines, original
headers and retained RGB-D bundles belong to the client, never to the model.
"""
from __future__ import annotations

import base64
import copy
import json
import time
import uuid
from dataclasses import dataclass

import numpy as np

from sam3_runtime_core import normalize_masks

SCHEMA = "semantic-inference/v1"
VERSIONS = {
    "model": "3c879f39826c281e95690f02c7821c4de09afae7",
    "preprocess": "sam3-pil-rgb/v1",
    "decoder": "sam3-binary-instances/v1",
}
POLICY = "avoid-target/v1"
MAX_PIXELS = 640 * 480
MAX_INSTANCES = 64
MAX_WIRE_BYTES = 28 * 1024 * 1024
ERRORS = {"not_ready", "timeout", "invalid_input", "overload", "inference_error"}


def dumps(value):
    data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    if len(data) > MAX_WIRE_BYTES:
        raise ValueError("wire payload exceeds limit")
    return data


def loads(data):
    if len(data) > MAX_WIRE_BYTES:
        raise ValueError("wire payload exceeds limit")
    return json.loads(data, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def dimensions(width, height):
    if type(width) is not int or type(height) is not int or min(width, height) < 1:
        raise ValueError("invalid dimensions")
    if width * height > MAX_PIXELS:
        raise ValueError("image exceeds pixel limit")


def decode_bytes(value, size):
    if not isinstance(value, str) or len(value) != 4 * ((size + 2) // 3):
        raise ValueError("invalid encoded payload length")
    raw = base64.b64decode(value, validate=True)
    if len(raw) != size:
        raise ValueError("invalid decoded payload length")
    return raw


def make_request(image, *, sequence, epoch, generation, stamp, frame, prompt,
                 threshold, budget_ms, robot="robot_1", stream="camera/color"):
    width, height = image.size
    dimensions(width, height)
    return {
        "schema": SCHEMA,
        "identity": {"request_id": str(uuid.uuid4()), "robot": robot, "stream": stream,
                     "sequence": sequence, "epoch": epoch, "generation": generation},
        "capture": {"stamp_ns": stamp, "frame_id": frame},
        "versions": dict(VERSIONS), "policy": POLICY,
        "width": width, "height": height, "encoding": "rgb8/base64",
        "image": base64.b64encode(image.convert("RGB").tobytes()).decode(),
        "prompt": prompt, "threshold": threshold, "budget_ms": budget_ms,
    }


def validate_request(request):
    if request["schema"] != SCHEMA or request["versions"] != VERSIONS or request["policy"] != POLICY:
        raise ValueError("unsupported schema/model/policy versions")
    identity = request["identity"]
    for key in ("request_id", "robot", "stream", "epoch"):
        if not isinstance(identity[key], str) or not 0 < len(identity[key]) <= 256:
            raise ValueError("invalid identity")
    for key in ("sequence", "generation"):
        if type(identity[key]) is not int or identity[key] < 0:
            raise ValueError("invalid sequence/generation")
    if (type(request["capture"]["stamp_ns"]) is not int or request["capture"]["stamp_ns"] < 0
            or not request["capture"]["frame_id"]):
        raise ValueError("invalid capture header")
    dimensions(request["width"], request["height"])
    if request["encoding"] != "rgb8/base64":
        raise ValueError("unsupported image encoding")
    if not isinstance(request["prompt"], str) or not 0 < len(request["prompt"]) <= 256:
        raise ValueError("invalid prompt")
    if not 0 <= request["threshold"] <= 1 or not 0 < request["budget_ms"] <= 5000:
        raise ValueError("invalid threshold/budget")
    return decode_bytes(request["image"], request["width"] * request["height"] * 3)


def response_base(request, status="ok", reason=None):
    return {"schema": SCHEMA, "identity": copy.deepcopy(request["identity"]),
            "capture": copy.deepcopy(request["capture"]), "versions": dict(VERSIONS),
            "policy": POLICY, "width": request["width"], "height": request["height"],
            "status": status, "reason": reason}


def success_response(request, masks, scores):
    # Validate native model output before converting it to the declared wire type.
    normalize_masks(masks, scores, request["width"], request["height"])
    masks = np.asarray(masks).reshape(-1, request["height"], request["width"])
    if len(masks) > MAX_INSTANCES:
        raise ValueError("too many instance masks")
    binary = (masks > 0.5).astype(np.uint8)
    response = response_base(request)
    response.update(encoding="uint8-nhw/base64", count=len(binary),
                    masks=base64.b64encode(binary.tobytes()).decode(),
                    scores=np.asarray(scores).reshape(-1).tolist(),
                    score_meaning="sam3-instance-confidence-not-calibrated")
    return response


def decode_response(request, response):
    for key in ("schema", "identity", "capture", "versions", "policy", "width", "height"):
        if response[key] != request[key]:
            raise ValueError(f"response mismatch: {key}")
    if response["status"] != "ok":
        if response["status"] not in ERRORS:
            raise ValueError("unknown backend status")
        raise RuntimeError(f"backend {response['status']}: {response.get('reason')}")
    count = response["count"]
    if type(count) is not int or not 0 <= count <= MAX_INSTANCES:
        raise ValueError("invalid instance count")
    if (response["encoding"] != "uint8-nhw/base64" or
            response["score_meaning"] != "sam3-instance-confidence-not-calibrated"):
        raise ValueError("unsupported mask/score encoding")
    raw = decode_bytes(response["masks"], count * request["width"] * request["height"])
    masks = np.frombuffer(raw, dtype=np.uint8).reshape(count, request["height"], request["width"])
    return normalize_masks(masks, response["scores"], request["width"], request["height"])


@dataclass
class Retained:
    request: dict
    deadline: float
    cloud_deadline: float
    bundle: object


class ResultGuard:
    """Single-owner guard; caller serializes reset/register/accept operations."""
    def __init__(self, epoch, generation=1, max_pending=1):
        self.epoch, self.generation, self.max_pending = epoch, generation, max_pending
        self.pending = {}
        self.last_sequence = -1

    def reset(self, epoch, generation):
        self.epoch, self.generation = epoch, generation
        self.pending.clear()
        self.last_sequence = -1

    def register(self, request, deadline, cloud_deadline, bundle):
        identity = request["identity"]
        if identity["epoch"] != self.epoch or identity["generation"] != self.generation:
            raise ValueError("request epoch/policy is no longer current")
        if len(self.pending) >= self.max_pending or identity["request_id"] in self.pending:
            raise ValueError("in-flight capacity exceeded or duplicate request")
        self.pending[identity["request_id"]] = Retained(copy.deepcopy(request), deadline, cloud_deadline, bundle)

    def cancel(self, request_id):
        self.pending.pop(request_id, None)

    def accept(self, response, now=None):
        now = time.monotonic() if now is None else now
        identity = response["identity"]
        retained = self.pending.pop(identity["request_id"], None)
        if retained is None:
            raise ValueError("unknown, duplicate, or expired retained request")
        if identity["epoch"] != self.epoch or identity["generation"] != self.generation:
            raise ValueError("old epoch/policy generation")
        if now >= min(retained.deadline, retained.cloud_deadline):
            raise TimeoutError("request or retained cloud expired")
        if identity["sequence"] <= self.last_sequence:
            raise ValueError("out-of-order completion")
        mask, scores = decode_response(retained.request, response)
        self.last_sequence = identity["sequence"]
        return mask, scores, retained.bundle
