# Phase 2 candidate-label review packet

Status: **Reviewed and approved by JZ on 2026-10-15**. All nine rows were approved; none were corrected or rejected, and the candidate masks remain unchanged. This packet intentionally omits all SAM3 predictions, confidence scores, and per-image model results. The images and masks were generated from simulator geometry and RGB-D depth, not SAM3 output.

## Review instructions

For each sample, inspect the RGB image and candidate overlay together. Confirm whether any target surface is visible, whether the green overlay covers the visible target and only the target, and whether the stated occlusion condition matches the image. For the negative, confirm the red target is absent and the neutral tile is visible. Mark each row `accept`, `correct`, or `reject`; for a correction, save a new mask and record its path and SHA-256 without overwriting the candidate. Record reviewer name/ID and UTC date. A second reviewer should adjudicate every partial-occlusion sample and a random 20% of other samples.

These nine distinct captures are a development-only sample from two episodes. They are not the held-out set, and acceptance requires the episode-separated dataset and counts in `[capture-and-label-protocol.md](capture-and-label-protocol.md)`.

## Samples


| Episode / capture                  | Condition                                             | RGB                                                                      | Geometry/depth candidate overlay                                                     | Candidate pixels     | Reviewer decision / notes |
| ---------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ | -------------------- | ------------------------- |
| pilot-v2 / initial-0000            | Positive; about 25% visible, frontal                  | [image](capture-pilot-v2/initial/initial-0000.jpg)                       | [overlay](capture-pilot-v2/initial/target-depth-overlay.jpg)                         | 1,445                | approved                  |
| pilot-v2 / moved-0000              | Positive; about 25% visible after 0.115 m translation | [image](capture-pilot-v2/moved/moved-0000.jpg)                           | [overlay](capture-pilot-v2/moved/target-depth-overlay.jpg)                           | 1,474                | approved                  |
| pilot-v2 / oblique-0000            | Positive; about 25% visible after yaw change          | [image](capture-pilot-v2/oblique/oblique-0000.jpg)                       | [overlay](capture-pilot-v2/oblique/target-depth-overlay.jpg)                         | 1,697                | approved                  |
| pilot-v2 / tile-negative-0000      | Negative; tile distractor present                     | [image](capture-pilot-v2/tile-negative/tile-negative-0000.jpg)           | [target-empty / tile overlay](capture-pilot-v2/tile-negative/tile-depth-overlay.jpg) | 0 target; 2,344 tile | approved                  |
| pilot-v2 / unoccluded-0000         | Positive; unoccluded control                          | [image](capture-pilot-v2/unoccluded-control/unoccluded-0000.jpg)         | [overlay](capture-pilot-v2/unoccluded-control/target-depth-overlay.jpg)              | 5,760                | approved                  |
| pilot-v2 / moderate-0000           | Positive; about 51% visible                           | [image](capture-pilot-v2/moderate-occlusion/moderate-0000.jpg)           | [overlay](capture-pilot-v2/moderate-occlusion/target-depth-overlay.jpg)              | 2,949                | approved                  |
| pilot-v3 / ep2-yaw-unoccluded-0000 | Positive; unoccluded, about +6° view                  | [image](capture-pilot-v3/ep2-yaw-unoccluded/ep2-yaw-unoccluded-0000.jpg) | [overlay](capture-pilot-v3/ep2-yaw-unoccluded/target-depth-overlay.jpg)              | 5,924                | approved                  |
| pilot-v3 / ep2-yaw-moderate-0000   | Positive; about 51% visible, about +6° view           | [image](capture-pilot-v3/ep2-yaw-moderate/ep2-yaw-moderate-0000.jpg)     | [overlay](capture-pilot-v3/ep2-yaw-moderate/target-depth-overlay.jpg)                | 3,011                | approved                  |
| pilot-v3 / ep2-yaw-severe-0000     | Positive; about 24% visible, about +6° view           | [image](capture-pilot-v3/ep2-yaw-severe/ep2-yaw-severe-0000.jpg)         | [overlay](capture-pilot-v3/ep2-yaw-severe/target-depth-overlay.jpg)                  | 1,431                | approved                  |




## Decision record


| Reviewer | UTC date   | Accepted rows | Corrected rows and new mask hashes | Rejected rows | Overall notes |
| -------- | ---------- | ------------- | ---------------------------------- | ------------- | ------------- |
| JZ       | 2026-10-15 | 9             | 0                                  | 0             | Approved all candidate masks and presence labels; no label files changed. |


