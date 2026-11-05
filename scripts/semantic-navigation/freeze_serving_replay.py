#!/usr/bin/env python3
"""Freeze requests and local GPU responses before any served parity run.

Run in an isolated GPU job with the built runtime, not in an active robot pod.
The output is parity evidence and does not close the recognition waiver.
"""
import argparse
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/semantic-model-server"), str(ROOT / "apps/semantic-perception")]
from artifact import sha256, verify_artifact
from inference_contract import decode_response, dumps, make_request
from sam3_backend import LocalSam3Backend, Sam3ModelRunner


def freeze(args):
    selection = json.loads(args.selection.read_text())
    if {row["case"] for row in selection["frames"]} != {"mat", "absent-target", "empty-mask"}:
        raise ValueError("all three replay cases required")
    checkpoint, identity = verify_artifact(args.model_manifest, args.model_dir,
                                          args.build_identity, args.runtime_image_digest)
    runner = Sam3ModelRunner(str(checkpoint), identity["threshold"])
    if str(runner.dtype).split(".")[-1] != identity["precision"]:
        raise ValueError("precision mismatch")
    runner.infer(Image.new("RGB", (640, 480)), identity["prompt"], identity["threshold"])
    backend = LocalSam3Backend(runner)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, row in enumerate(selection["frames"]):
        if "repo_path" in row:
            path = ROOT / row["repo_path"]
            if sha256(path) != row["source_sha256"]:
                raise ValueError("source capture checksum mismatch")
            with Image.open(path) as source:
                image = source.convert("RGB")
        elif row.get("synthetic") == "black-rgb8-640x480":
            image = Image.new("RGB", (640, 480))
        else:
            raise ValueError("unrecognized source")
        request = make_request(image, sequence=index, epoch="s1-frozen-replay", generation=1,
            stamp=0, frame="offline-optical", prompt=identity["prompt"], threshold=identity["threshold"],
            budget_ms=5000, robot="robot_1", stream="camera/color")
        response = backend.predict(request)
        mask, _ = decode_response(request, response)
        if row["case"] == "empty-mask" and mask.any():
            raise ValueError("candidate empty-mask image did not produce an empty baseline")
        if row["case"] == "mat" and not mask.any():
            raise ValueError("candidate mat image did not produce a nonempty baseline")
        frozen = {"case": row["case"]}
        for key, value in (("request", request), ("local_response", response)):
            filename = f"{index:03d}-{key}.json"
            path = args.output / filename
            path.write_bytes(dumps(value))
            frozen[key] = filename
            frozen[key + "_sha256"] = sha256(path)
        rows.append(frozen)
    manifest = {"schema": "semantic-serving-replay/v1", "selection_sha256": sha256(args.selection),
                "local_identity": identity, "frames": rows}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"sample_count": len(rows), "manifest_sha256": sha256(args.output / "manifest.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("selection", "model-manifest", "model-dir", "build-identity", "output"):
        parser.add_argument("--" + flag, required=True, type=Path)
    parser.add_argument("--runtime-image-digest", required=True)
    freeze(parser.parse_args())
