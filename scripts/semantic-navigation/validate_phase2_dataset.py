#!/usr/bin/env python3
"""Validate Phase 2 SAM3 manifest integrity and held-out sample counts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(path: Path, min_heldout_per_class: int = 50) -> dict:
    errors: list[str] = []
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc}")
            continue
        row["_line"] = line_number
        rows.append(row)

    required = (
        "image", "label", "split", "presence", "episode", "capture_id",
        "distance_bin", "view_bin", "occlusion", "lighting", "label_method",
        "review_status", "capture_metadata",
    )
    episode_splits: dict[str, set[str]] = defaultdict(set)
    hash_splits: dict[str, set[str]] = defaultdict(set)
    counts: Counter[tuple[str, str]] = Counter()
    seen_hashes: dict[str, int] = {}
    valid_rows = 0
    for row in rows:
        line = row["_line"]
        missing = [key for key in required if not row.get(key)]
        if missing:
            errors.append(f"line {line}: missing fields {missing}")
            continue
        split = row["split"]
        presence = row["presence"]
        if split not in ("development", "heldout"):
            errors.append(f"line {line}: invalid split {split!r}")
            continue
        if presence not in ("positive", "negative"):
            errors.append(f"line {line}: invalid presence {presence!r}")
            continue

        episode_splits[row["episode"]].add(split)
        counts[(split, presence)] += 1
        image_path = Path(row["image"])
        label_path = Path(row["label"])
        metadata_path = Path(row["capture_metadata"])
        if not image_path.is_absolute():
            image_path = path.parent / image_path
        if not label_path.is_absolute():
            label_path = path.parent / label_path
        if not metadata_path.is_absolute():
            metadata_path = path.parent / metadata_path
        if not image_path.is_file() or not label_path.is_file() or not metadata_path.is_file():
            errors.append(f"line {line}: image, label, or capture-metadata file missing")
            continue
        try:
            metadata_rows = json.loads(metadata_path.read_text())
            metadata = metadata_rows[row.get("metadata_index", 0)]
        except (json.JSONDecodeError, IndexError, TypeError, KeyError) as exc:
            errors.append(f"line {line}: invalid capture metadata: {exc}")
            continue
        metadata_required = (
            "world_from_base_link", "depth_frame_id", "camera_info",
            "static_transforms", "odometry", "rgb_stamp_ns", "depth_stamp_ns",
            "camera_info_stamp_ns", "odometry_stamp_ns",
        )
        if any(key not in metadata for key in metadata_required):
            errors.append(f"line {line}: capture metadata lacks direct pose/calibration/time fields")
            continue
        if len(metadata["world_from_base_link"]) != 7:
            errors.append(f"line {line}: invalid Gazebo world_from_base_link pose")
            continue
        if max(metadata.get("skew_ms", float("inf")),
               metadata.get("camera_info_skew_ms", float("inf")),
               metadata.get("odometry_skew_ms", float("inf"))) > 100:
            errors.append(f"line {line}: capture metadata skew exceeds 100 ms")
            continue
        odometry = metadata["odometry"]
        if (abs(odometry.get("linear_velocity_x_mps", float("inf"))) > 0.01
                or abs(odometry.get("angular_velocity_z_radps", float("inf"))) > 0.01):
            errors.append(f"line {line}: capture metadata indicates robot was moving")
            continue
        stored_image = Path(metadata["rgb"])
        if not stored_image.is_absolute():
            stored_image = metadata_path.parent / stored_image
        if stored_image.resolve() != image_path.resolve():
            errors.append(f"line {line}: manifest image differs from capture metadata image")
            continue
        stored_depth = Path(metadata.get("depth", ""))
        if not stored_depth.is_absolute():
            stored_depth = metadata_path.parent / stored_depth
        if not stored_depth.is_file():
            errors.append(f"line {line}: capture metadata depth image is missing")
            continue
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(label_path), cv2.IMREAD_GRAYSCALE)
        if image is None or mask is None:
            errors.append(f"line {line}: image or label cannot be decoded")
            continue
        if image.shape[:2] != mask.shape:
            errors.append(f"line {line}: image/mask dimensions differ")
            continue
        values = set(np.unique(mask).tolist())
        if not values.issubset({0, 255}):
            errors.append(f"line {line}: mask is not binary 0/255 (values={sorted(values)})")
            continue
        has_pixels = bool(np.any(mask))
        if (presence == "positive") != has_pixels:
            errors.append(f"line {line}: presence label conflicts with mask")
            continue
        digest = sha256(image_path)
        hash_splits[digest].add(split)
        if digest in seen_hashes:
            errors.append(
                f"line {line}: exact duplicate image of line {seen_hashes[digest]}"
            )
        else:
            seen_hashes[digest] = line
        valid_rows += 1

    for episode, splits in episode_splits.items():
        if len(splits) > 1:
            errors.append(f"episode {episode!r} leaks across splits: {sorted(splits)}")
    for digest, splits in hash_splits.items():
        if len(splits) > 1:
            errors.append(f"image hash leaks across splits: {digest}")
    for presence in ("positive", "negative"):
        observed = counts[("heldout", presence)]
        if observed < min_heldout_per_class:
            errors.append(
                f"heldout {presence}: {observed} < required {min_heldout_per_class}"
            )

    return {
        "status": "PASS" if not errors else "FAIL",
        "manifest": str(path),
        "row_count": len(rows),
        "valid_row_count": valid_rows,
        "counts": {
            f"{split}_{presence}": counts[(split, presence)]
            for split in ("development", "heldout")
            for presence in ("positive", "negative")
        },
        "episode_count": len(episode_splits),
        "minimum_heldout_per_class": min_heldout_per_class,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--min-heldout-per-class", type=int, default=50)
    args = parser.parse_args()
    if args.min_heldout_per_class < 0:
        parser.error("--min-heldout-per-class must be non-negative")
    result = validate(args.manifest, args.min_heldout_per_class)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
