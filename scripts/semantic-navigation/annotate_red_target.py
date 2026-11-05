#!/usr/bin/env python3
"""Create a provisional simulator-ground-truth mask for the uniquely red mat."""

import argparse
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("mask", type=Path)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--negative", action="store_true",
                        help="write an empty target mask and fail if red target pixels exist")
    args = parser.parse_args()
    bgr = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if bgr is None:
        parser.error(f"cannot read image: {args.image}")
    blue, green, red = cv2.split(bgr)
    target_pixels = (red > 70) & (red > green * 1.6) & (red > blue * 1.4)
    if args.negative and np.count_nonzero(target_pixels):
        raise SystemExit("negative frame contains target-colored pixels")
    mask = np.zeros(red.shape, dtype=np.uint8) if args.negative else target_pixels.astype(np.uint8) * 255
    if not args.negative and int(np.count_nonzero(mask)) < 20:
        raise SystemExit("red target mask is empty or implausibly small")
    args.mask.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.mask), mask):
        raise SystemExit(f"cannot write mask: {args.mask}")
    if args.overlay:
        overlay = bgr.copy()
        overlay[mask > 0] = (0, 255, 0)
        cv2.addWeighted(overlay, 0.4, bgr, 0.6, 0, overlay)
        if not cv2.imwrite(str(args.overlay), overlay):
            raise SystemExit(f"cannot write overlay: {args.overlay}")
    print(f"mask_pixels={int(np.count_nonzero(mask))} image={bgr.shape[1]}x{bgr.shape[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
