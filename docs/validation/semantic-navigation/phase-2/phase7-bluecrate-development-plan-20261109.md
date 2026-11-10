# Blue-crate development expansion — November 9, 2026

**Status: preregistered capture matrix; not captured or scored.** The six pilot
rows remain candidates until their blind label review is complete. Once
accepted/corrected/rejected decisions are recorded, capture the 34 new rows in
[`phase7-bluecrate-development-plan-20261109.json`](phase7-bluecrate-development-plan-20261109.json)
to reach at least 20 positive and 20 negative development examples across
seven distinct episodes. SHA-256:
`98aa76a92578b11a521a59c7e7d502abb98e39166c56b8bc4488112d0a9c8b39`.

The plan allocates 16 positive and 18 negative views over four new episodes.
It includes near/mid/far target distances, frontal and oblique views, baseline
and dim lighting, partially occluded targets, red-mat distractors, ordinary
floor, and crate-out-of-view negatives. Keep each frame on a distinct stopped
pose or scene condition, capture synchronized RGB-D/calibration/direct pose,
and record the actual condition rather than the intended one.

Complete blind label review before viewing SAM3 predictions. Preserve candidate
masks and version any corrections. Second-review all partial-occlusion masks
and a random 20% of other masks. These are development samples used to select
and freeze the prompt, threshold, inference resolution, and visibility
contract. They cannot be counted toward the held-out 50/50 acceptance set.
