# Phase 7 blue-crate capture pilot

This is a small synthetic development pilot, not held-out recognition evidence
and not a Phase 2 pass. It contains four target-visible positives and two
negatives across three simulator episodes. One negative has the crate out of
the camera field of view; the other was captured with the crate model omitted
while the red mat remained visible. All frames use the same camera, hotel
floor, and default lighting. The positives show the crate over the red mat, so
the pilot does not establish generalization across backgrounds or lighting.

Each RGB/depth pair has 0 ms stamp skew and each CameraInfo stamp has 0 ms skew.
Odometry skew is 20–80 ms; all six odometry records indicate a stopped robot.
Every row stores the direct Gazebo `world_from_base_link` pose, intrinsics,
static transforms, timestamps, image/depth paths, and SHA-256 values. The
positive masks were projected from the fixture's box geometry and filtered
against measured uint16 depth with a 3 cm tolerance. The overlays align with
the visible crate. Both negatives have empty target masks; the crate-absent
scene was checked against Gazebo's entity list and retains the red-mat
distractor. Human label review is pending.

The six-row `manifest.jsonl` passes integrity validation only when run with
`--min-heldout-per-class 0`; it records 4 development positives, 2 development
negatives, and zero held-out samples. Recognition results from the pinned SAM3
candidate have not been collected. Full qualification still requires
human-reviewed labels, prompt/configuration freeze, episode-separated held-out
positives and negatives at the protocol quotas, model scoring, and applicable
Phase 3–6 gates.

Each sample directory contains an RGB frame, uint16 depth PNG, binary target
mask, overlay, and capture `manifest.json`. `manifest.jsonl` is the combined
development dataset record.

The [human label review packet](label-review-packet.md) links each RGB frame,
candidate overlay, mask, depth image, and capture metadata without showing
model predictions. A [decision template](review-decisions-template.json)
records primary reviews and two independent checks. Candidate labels remain
pending until reviewers record their decisions; this pilot remains
development-only.
