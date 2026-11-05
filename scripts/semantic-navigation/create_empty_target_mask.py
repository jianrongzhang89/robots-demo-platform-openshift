#!/usr/bin/env python3
"""Create a candidate empty target mask for a visually verified negative frame."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reason", choices=(
        "similar_tile_distractor", "ordinary_floor", "target_out_of_view",
    ), required=True)
    args = parser.parse_args()

    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        parser.error(f"cannot read image: {args.image}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    if not cv2.imwrite(str(args.output), mask):
        parser.error(f"cannot write mask: {args.output}")
    print(json.dumps({
        "status": "CANDIDATE_LABEL_REQUIRES_VISUAL_REVIEW",
        "presence": "negative",
        "negative_reason": args.reason,
        "image": str(args.image),
        "mask": str(args.output),
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
        "mask_pixels": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
