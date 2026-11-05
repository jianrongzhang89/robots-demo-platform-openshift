#!/usr/bin/env python3
"""Measure repeated single-image SAM3 latency after model warmup."""

from __future__ import annotations

import argparse
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


def sync_cuda() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--prompt", default="red floor mat")
    parser.add_argument("--confidence-threshold", type=float, default=0.5)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    if args.warmups < 1 or args.iterations < 2:
        parser.error("use at least one warmup and two measured iterations")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this benchmark")

    torch.cuda.reset_peak_memory_stats()
    device_name = torch.cuda.get_device_name()
    load_started = time.perf_counter()
    model = build_sam3_image_model(
        device="cuda", checkpoint_path=str(args.checkpoint),
        load_from_HF=False, eval_mode=True,
    )
    sync_cuda()
    load_seconds = time.perf_counter() - load_started
    processor = Sam3Processor(
        model, device="cuda", confidence_threshold=args.confidence_threshold,
    )
    with Image.open(args.image) as source:
        image = source.convert("RGB")
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    def infer() -> tuple[float, int]:
        started = time.perf_counter()
        with torch.inference_mode(), torch.autocast("cuda", dtype=dtype):
            state = processor.set_image(image)
            output = processor.set_text_prompt(state=state, prompt=args.prompt)
        sync_cuda()
        return time.perf_counter() - started, int(output["masks"].shape[0])

    for _ in range(args.warmups):
        infer()
    timings = []
    mask_counts = []
    for _ in range(args.iterations):
        elapsed, count = infer()
        timings.append(elapsed)
        mask_counts.append(count)
    report = {
        "status": "BENCHMARK_ONLY",
        "device_name": device_name,
        "image_size": list(image.size),
        "prompt": args.prompt,
        "confidence_threshold": args.confidence_threshold,
        "warmups": args.warmups,
        "iterations": args.iterations,
        "model_load_seconds": round(load_seconds, 6),
        "latency_seconds_median": round(statistics.median(timings), 6),
        "latency_seconds_p95": round(float(np.percentile(timings, 95)), 6),
        "latency_seconds_max": round(max(timings), 6),
        "mask_counts": mask_counts,
        "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_gpu_reserved_bytes": torch.cuda.max_memory_reserved(),
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
