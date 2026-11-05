#!/usr/bin/env python3
"""Bounded opt-in camera delay fault; removes its own trigger in finally."""
import json
import os
import time
import uuid
from pathlib import Path

assert os.getenv("GZ_PARTITION") == "semantic_phase3_inference"
path = Path(os.environ["PHASE3_CAMERA_FAULT_FILE"])
assert str(path) == "/tmp/phase3-camera-fault.json"
assert not path.exists(), "refusing to overwrite an existing fault trigger"
try:
    with path.open("x") as handle:
        json.dump({"mode": "delay", "seconds": 8, "token": str(uuid.uuid4())}, handle)
    print("camera delay trigger installed", flush=True)
    time.sleep(9)
finally:
    path.unlink(missing_ok=True)
print("camera delay trigger removed", flush=True)
