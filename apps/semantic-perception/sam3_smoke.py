#!/usr/bin/env python3
"""Phase-0 SAM3 image smoke test; does not download or upload model weights."""

from __future__ import annotations

import argparse
import json
import time
from contextlib import nullcontext
from pathlib import Path

import torch
from PIL import Image
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.model_builder import build_sam3_image_model


def sync_cuda() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--prompt", default="floor mat")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--confidence-threshold", type=float, default=0.5)
    args = parser.parse_args()

    if not args.checkpoint.is_file():
        parser.error(f"checkpoint does not exist: {args.checkpoint}")
    if not args.image.is_file():
        parser.error(f"image does not exist: {args.image}")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        device_name = torch.cuda.get_device_name()
    else:
        device_name = "CPU"

    started = time.perf_counter()
    model = build_sam3_image_model(
        device=args.device,
        checkpoint_path=str(args.checkpoint),
        load_from_HF=False,
        eval_mode=True,
    )
    sync_cuda()
    load_seconds = time.perf_counter() - started

    processor = Sam3Processor(
        model, device=args.device, confidence_threshold=args.confidence_threshold
    )
    with Image.open(args.image) as source:
        image = source.convert("RGB")
    inference_started = time.perf_counter()
    autocast_dtype = None
    autocast_context = nullcontext()
    if args.device.startswith("cuda"):
        autocast_dtype = (
            torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        )
        autocast_context = torch.autocast("cuda", dtype=autocast_dtype)
    with torch.inference_mode(), autocast_context:
        state = processor.set_image(image)
        output = processor.set_text_prompt(state=state, prompt=args.prompt)
    sync_cuda()
    inference_seconds = time.perf_counter() - inference_started

    masks = output["masks"]
    scores = output["scores"]
    if not torch.isfinite(masks).all().item():
        raise RuntimeError("model returned non-finite mask values")
    if not torch.isfinite(scores).all().item():
        raise RuntimeError("model returned non-finite confidence scores")

    report = {
        "status": "PASS",
        "model": "facebook/sam3 (original SAM3, local checkpoint)",
        "device": args.device,
        "device_name": device_name,
        "autocast_dtype": str(autocast_dtype) if autocast_dtype else None,
        "image_size": list(image.size),
        "prompt": args.prompt,
        "confidence_threshold": args.confidence_threshold,
        "mask_shape": list(masks.shape),
        "mask_count": int(masks.shape[0]) if masks.ndim else 0,
        "mask_values_finite": True,
        "scores_finite": True,
        "scores": scores.detach().float().cpu().tolist(),
        "model_load_seconds": round(load_seconds, 3),
        "inference_seconds": round(inference_seconds, 3),
        "peak_gpu_allocated_bytes": (
            torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None
        ),
        "peak_gpu_reserved_bytes": (
            torch.cuda.max_memory_reserved() if torch.cuda.is_available() else None
        ),
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
