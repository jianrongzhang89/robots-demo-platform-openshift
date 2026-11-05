"""Fail-closed artifact identity, independent of the request's version claims."""
import hashlib
import json
from pathlib import Path
import re

from inference_contract import POLICY, VERSIONS

SOURCE_REVISION = "0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc"
WEIGHTS_SHA256 = "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(manifest_path, model_dir, build_path, image_digest):
    manifest = json.loads(Path(manifest_path).read_text())
    build = json.loads(Path(build_path).read_text())
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise ValueError("a deployment-pinned container digest is required")
    expected = {
        "schema": "semantic-model-artifact/v1", "model_name": "sam3-mat-v1",
        "checkpoint": "sam3.pt", "weights_sha256": WEIGHTS_SHA256,
        "source_revision": SOURCE_REVISION, "versions": VERSIONS,
        "policy": POLICY, "prompt": "red mat", "threshold": 0.5,
    }
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise ValueError("unqualified artifact or prompt policy")
    if manifest.get("precision") not in ("bfloat16", "float16"):
        raise ValueError("unqualified precision")
    if build["source_revision"] != SOURCE_REVISION:
        raise ValueError("build source revision mismatch")
    for filename in ("sam3_backend.py", "inference_contract.py", "sam3_runtime_core.py"):
        if sha256(Path(build_path).parent / filename) != build["shared_sha256"][filename]:
            raise ValueError("shared source hash mismatch")
    checkpoint = Path(model_dir) / manifest["checkpoint"]
    actual = sha256(checkpoint)
    if actual != manifest["weights_sha256"]:
        raise ValueError("checkpoint checksum mismatch")
    identity = {
        "schema": "semantic-deployment/v1", "model_name": manifest["model_name"],
        "weights_sha256": actual, "source_revision": build["source_revision"],
        "container_digest": image_digest, "shared_sha256": build["shared_sha256"],
        "versions": manifest["versions"], "precision": manifest["precision"],
        "policy": manifest["policy"], "prompt": manifest["prompt"],
        "threshold": manifest["threshold"],
    }
    return checkpoint, identity


def verify_deployment_identity(actual, expected):
    """Replay/remote consumers pin the complete additive identity, not a subset."""
    if not isinstance(actual, dict) or actual != expected:
        raise ValueError("served deployment identity mismatch")
