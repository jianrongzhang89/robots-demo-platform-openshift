#!/usr/bin/env python3
"""Replay development RGB images through real SAM3 and the wire boundary.

Contract verification only: never loads annotations or computes recognition scores.
"""
import argparse
import copy
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from inference_contract import ResultGuard, decode_response, dumps, loads, make_request
from sam3_backend import LocalSam3Backend, Sam3ModelRunner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True)
    args = parser.parse_args()
    runner = Sam3ModelRunner("/models/sam3.pt", .5)
    runner.infer(Image.new("RGB", (640, 480)), "red mat", .5)
    backend = LocalSam3Backend(runner)
    results = []
    for sequence, path in enumerate(sorted(Path(args.images).rglob("*.jpg"))):
        image = Image.open(path).convert("RGB")
        request = make_request(image, sequence=sequence, epoch="replay", generation=1,
            stamp=sequence * 100000000, frame="camera_color_optical_frame", prompt="red mat",
            threshold=.5, budget_ms=5000)
        started = time.monotonic()
        response = backend.predict(loads(dumps(request)))
        direct, _ = decode_response(request, response)
        # Deterministic recorded-response test double: no claim about a remote server.
        transported = loads(dumps(response))
        guard = ResultGuard("replay")
        guard.register(request, time.monotonic() + 1, time.monotonic() + 1, "original-depth")
        mask, _, cloud = guard.accept(transported)
        np.testing.assert_array_equal(direct, mask)
        assert cloud == "original-depth"
        rejected = []
        for section, key, value in [("identity", "robot", "wrong"), ("identity", "epoch", "old"),
                                     ("versions", "model", "wrong")]:
            altered = copy.deepcopy(response)
            altered[section][key] = value
            try:
                decode_response(request, altered)
            except ValueError:
                rejected.append(f"{section}.{key}")
        assert len(rejected) == 3
        results.append({"file": str(path), "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "instances": response["count"], "avoid_pixels": int(np.count_nonzero(mask)),
            "labels": np.unique(mask).tolist(), "elapsed_ms": (time.monotonic() - started) * 1000,
            "wire_roundtrip_identical": True, "invalid_response_rejections": rejected})
    assert results, "no replay images supplied"
    print(json.dumps({"kind": "real_model_backend_replay_contract", "recognition_scored": False,
                      "results": results}), flush=True)


if __name__ == "__main__":
    main()
