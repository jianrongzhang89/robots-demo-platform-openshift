#!/usr/bin/env python3
"""Offline SAM3 scorer for a frozen image/ground-truth JSONL manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.model_builder import build_sam3_image_model
from manifest_validation import require_reviewed_rows


def mask_array(value: torch.Tensor, width: int, height: int) -> np.ndarray:
    tensor = value.detach().float()
    while tensor.ndim > 2:
        tensor = tensor.squeeze(0)
    if tensor.ndim != 2:
        raise ValueError(f"expected a 2-D mask, received shape {tuple(value.shape)}")
    if tuple(tensor.shape) != (height, width):
        tensor = torch.nn.functional.interpolate(
            tensor[None, None], size=(height, width), mode="nearest"
        )[0, 0]
    return tensor.cpu().numpy() > 0.5


def load_manifest(path: Path, split: str) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = [row for row in rows if row.get("split") == split]
    if not rows:
        raise ValueError(f"manifest has no rows for split={split!r}")
    require_reviewed_rows(rows)
    for row in rows:
        for key in ("image", "label"):
            value = Path(row[key])
            if not value.is_absolute():
                row[key] = str((path.parent / value).resolve())
            if not Path(row[key]).is_file():
                raise FileNotFoundError(row[key])
        if row.get("presence") not in ("positive", "negative"):
            raise ValueError(f"invalid presence label in row {row}")
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--split", choices=("development", "heldout"), required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--confidence-threshold", type=float, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.checkpoint.is_file():
        parser.error(f"checkpoint does not exist: {args.checkpoint}")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")

    rows = load_manifest(args.manifest, args.split)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        device_name = torch.cuda.get_device_name()
    else:
        device_name = "CPU"
    model = build_sam3_image_model(
        device=args.device, checkpoint_path=str(args.checkpoint),
        load_from_HF=False, eval_mode=True,
    )
    processor = Sam3Processor(
        model, device=args.device,
        confidence_threshold=args.confidence_threshold,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    positive_ious = []
    positive_hits = 0
    negative_frames = 0
    negative_false_positives = 0
    for index, row in enumerate(rows):
        with Image.open(row["image"]) as source:
            image = source.convert("RGB")
        width, height = image.size
        started = time.perf_counter()
        autocast = nullcontext()
        if args.device.startswith("cuda"):
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            autocast = torch.autocast("cuda", dtype=dtype)
        with torch.inference_mode(), autocast:
            state = processor.set_image(image)
            output = processor.set_text_prompt(state=state, prompt=args.prompt)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        latency = time.perf_counter() - started

        predicted = np.zeros((height, width), dtype=bool)
        masks = output["masks"]
        for mask in masks:
            predicted |= mask_array(mask, width, height)
        gt = np.asarray(Image.open(row["label"]).convert("L")) >= 128
        if gt.shape != predicted.shape:
            raise ValueError(f"label size differs from image for {row['image']}")
        intersection = int(np.logical_and(predicted, gt).sum())
        union = int(np.logical_or(predicted, gt).sum())
        iou = intersection / union if union else 0.0
        present = row["presence"] == "positive"
        if present:
            positive_ious.append(iou)
            positive_hits += int(iou >= 0.5)
        else:
            negative_frames += 1
            negative_false_positives += int(bool(predicted.any()))
        mask_path = args.output / f"{index:04d}-prediction.png"
        Image.fromarray(predicted.astype(np.uint8) * 255).save(mask_path)
        results.append({
            "image": row["image"], "presence": row["presence"],
            "iou": round(iou, 6), "detected": bool(predicted.any()),
            "scores": output["scores"].detach().float().cpu().tolist(),
            "inference_seconds": round(latency, 6),
            "prediction_mask": str(mask_path),
        })

    positives = sum(row["presence"] == "positive" for row in rows)
    report = {
        "status": "SCORED_NOT_ACCEPTED",
        "split": args.split,
        "model": "facebook/sam3 (local checkpoint)",
        "checkpoint_sha256": sha256_file(args.checkpoint),
        "device": args.device,
        "device_name": device_name,
        "prompt": args.prompt,
        "confidence_threshold": args.confidence_threshold,
        "image_count": len(rows),
        "positive_count": positives,
        "negative_count": negative_frames,
        "positive_recall_iou_ge_0_5": positive_hits / positives if positives else None,
        "positive_median_iou_including_misses": statistics.median(positive_ious) if positive_ious else None,
        "negative_false_positive_frame_rate": negative_false_positives / negative_frames if negative_frames else None,
        "inference_seconds_median": statistics.median(r["inference_seconds"] for r in results),
        "inference_seconds_p95": float(np.percentile([r["inference_seconds"] for r in results], 95)),
        "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None,
        "peak_gpu_reserved_bytes": torch.cuda.max_memory_reserved() if torch.cuda.is_available() else None,
        "results": results,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
