#!/usr/bin/env python3
"""Build a deduplicated Phase 2 development review manifest and packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def resolved(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase2-root", type=Path, required=True)
    parser.add_argument("--expansion-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    args = parser.parse_args()
    phase2 = args.phase2_root.resolve()
    root = args.expansion_root.resolve()
    selection = json.loads(args.selection.read_text())

    rows = []
    image_hashes: dict[str, str] = {}
    held = load_jsonl(phase2 / "capture-pilot-v3/combined-visibility-manifest.jsonl")
    for row in held:
        for key in ("image", "label", "capture_metadata"):
            value = row[key]
            if value.startswith("../capture-pilot-v2/"):
                row[key] = value
            else:
                row[key] = "../capture-pilot-v3/" + value.removeprefix("./")
        image_path = resolved(root, row["image"])
        label_path = resolved(root, row["label"])
        if not image_path.is_file() or not label_path.is_file():
            raise FileNotFoundError(f"reviewed source row is missing files: {row}")
        image_hashes[digest(image_path)] = str(image_path)
        rows.append(row)

    new_rows = []
    for presence in ("positive", "negative"):
        for item in selection[presence]:
            capture_dir = root / item["capture_dir"]
            metadata_path = capture_dir / "manifest.json"
            capture_rows = json.loads(metadata_path.read_text())
            if len(capture_rows) != 1:
                raise ValueError(f"expected exactly one capture in {metadata_path}")
            capture = capture_rows[0]
            image = capture_dir / capture["rgb"]
            depth = capture_dir / capture["depth"]
            label = capture_dir / item["mask"]
            if not all(path.is_file() for path in (image, depth, label)):
                raise FileNotFoundError(f"capture artifact missing in {capture_dir}")
            image_sha = digest(image)
            if image_sha in image_hashes:
                raise ValueError(
                    f"duplicate image across review set: {image} equals {image_hashes[image_sha]}"
                )
            image_hashes[image_sha] = str(image)

            world_pose = capture.get("world_from_base_link")
            if not world_pose or len(world_pose) != 7:
                raise ValueError(f"missing direct Gazebo pose in {metadata_path}")
            target_x, target_y = 17.4014, -31.5940
            distance = math.hypot(target_x - world_pose[0], target_y - world_pose[1])
            qx, qy, qz, qw = world_pose[3:]
            yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
            bearing = math.atan2(target_y - world_pose[1], target_x - world_pose[0])
            relative_yaw = math.atan2(math.sin(bearing - yaw), math.cos(bearing - yaw))
            capture_id = capture.get("label", capture_dir.name)
            row = {
                "image": image.relative_to(root).as_posix(),
                "label": label.relative_to(root).as_posix(),
                "split": "development",
                "presence": presence,
                "episode": item["episode"],
                "capture_id": capture_id,
                "metadata_index": 0,
                "capture_metadata": metadata_path.relative_to(root).as_posix(),
                "distance_m": round(distance, 4),
                "distance_bin": "near" if distance < 1.5 else "mid" if distance < 2.5 else "far",
                "view_bin": "frontal" if abs(relative_yaw) < math.radians(15) else "oblique",
                "relative_yaw_rad": round(relative_yaw, 5),
                "occlusion": "not_adjudicated",
                "lighting": "baseline",
                "label_method": item["label_method"],
                "review_status": "pending_independent_review",
                "negative_reason": item.get("negative_reason"),
                "image_sha256": image_sha,
                "label_sha256": digest(label),
                "capture_depth_sha256": digest(depth),
            }
            new_rows.append(row)

    if len([row for row in rows if row["presence"] == "positive"]) + len(selection["positive"]) != 20:
        raise ValueError("review set must contain exactly 20 positive development samples")
    if len([row for row in rows if row["presence"] == "negative"]) + len(selection["negative"]) != 20:
        raise ValueError("review set must contain exactly 20 negative development samples")

    rows.extend(new_rows)
    output = root / "development-review-manifest.jsonl"
    output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))

    packet = [
        "# Phase 2 development label-review packet",
        "",
        "Status: deferred at user request on 2026-10-15. No review decisions have been recorded. When resumed, review every candidate image and mask without SAM3 predictions; correct or reject labels before scoring.",
        "",
        "The 9 prior pilot samples were independently accepted by JZ on 2026-10-15. The following 31 newly captured samples are candidates; they are not accepted ground truth until review decisions are recorded.",
        "",
        "| ID | Presence / reason | Episode | Range | View | RGB | Candidate label | Overlay |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for row in new_rows:
        image = Path(row["image"])
        directory = image.parent
        overlay_name = "target-candidate-overlay.jpg"
        overlay = directory / overlay_name
        if not overlay.is_file():
            overlay_name = "target-depth-candidate-v2-overlay.jpg"
            overlay = directory / overlay_name
        overlay_link = f"[{overlay_name}]({overlay.as_posix()})" if overlay.is_file() else "—"
        reason = row["negative_reason"] or "visible target"
        packet.append(
            f"| `{row['capture_id']}` | {row['presence']}: {reason} | {row['episode']} | "
            f"{row['distance_m']:.2f} m | {row['view_bin']} ({row['relative_yaw_rad']:+.2f} rad) | "
            f"[RGB]({row['image']}) | [mask]({row['label']}) | {overlay_link} |"
        )
    packet.extend([
        "",
        "For each candidate, record accept/correct/reject, reviewer initials, date, and final mask SHA-256 in [`review-decisions-template.json`](review-decisions-template.json). The original candidate masks are retained; corrections must be saved as new versioned files.",
    ])
    (root / "label-review-packet.md").write_text("\n".join(packet) + "\n")
    decisions = {
        "status": "DEFERRED_BY_USER",
        "deferred_date": "2026-10-15",
        "reviewer": None,
        "review_date": None,
        "accepted_count": 0,
        "corrected_count": 0,
        "rejected_count": 0,
        "notes": "Deferred at user request on 2026-10-15; no decisions are recorded. When resumed, review every new candidate without viewing SAM3 predictions. Preserve candidates and save corrections as new versioned masks.",
        "decisions": [
            {
                "capture_id": row["capture_id"],
                "episode": row["episode"],
                "decision": None,
                "image": row["image"],
                "image_sha256": row["image_sha256"],
                "mask": row["label"],
                "mask_sha256": row["label_sha256"],
                "corrected_mask": None,
                "corrected_mask_sha256": None,
                "notes": None,
            }
            for row in new_rows
        ],
    }
    decisions_path = root / "review-decisions-template.json"
    decisions_path.write_text(json.dumps(decisions, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "manifest": str(output),
        "review_packet": str(root / "label-review-packet.md"),
        "decisions_template": str(decisions_path),
        "sample_count": len(rows),
        "positive_count": sum(row["presence"] == "positive" for row in rows),
        "negative_count": sum(row["presence"] == "negative" for row in rows),
        "new_pending_review_count": len(new_rows),
        "unique_image_count": len(image_hashes),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
