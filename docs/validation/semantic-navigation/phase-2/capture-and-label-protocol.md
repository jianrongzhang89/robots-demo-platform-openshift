# Phase 2 capture and labeling protocol

Status: proposed operational protocol; the acceptance dataset has not been collected.

## Evaluation split

- Keep the target, camera, resolution, simulator version, and target dimensions fixed while qualifying this demo configuration.
- Use `development` episodes to select prompt, confidence threshold, inference size, and the visibility envelope. Do not count these toward acceptance.
- Reserve complete capture episodes for `heldout`; never split neighboring frames or repeated takes from one pose sequence across the two splits. Keep episode IDs disjoint and verify exact image hashes do not cross splits.
- Acceptance minimum: 50 target-visible positive and 50 target-absent negative held-out images. Use overlapping, preregistered quotas rather than a full Cartesian product:
  - Per class: at least 20 baseline and 20 dim-light captures; at least 15 frontal and 15 oblique views.
  - Positives: at least 15 near (0.8–1.5 m median target depth), 15 mid (1.5–2.5 m), and 10 far (2.5–3.5 m); at least 15 partially occluded visible targets.
  - Negatives: at least 15 similar-tile distractors, 15 ordinary-floor views, and 10 target-out-of-view views. Negative labels must state the reason; a fully occluded target counts as not visible only if that is the intended detection contract.
  Use a preregistered matrix and reserve complete capture episodes; do not rebalance after seeing SAM3 outputs. These are engineering coverage quotas, not a full Cartesian product or a claim of statistical generalization.
- Collect at least 20 positive and 20 negative development images across separate episodes so prompt/threshold choices are not made from a single frame. If the frozen envelope excludes any condition, document the exclusion before held-out collection and retain that condition as a separate diagnostic, not silently relabel it.

## Labeling and review

- Record binary target presence separately from the mask. A positive means some visible target surface is in-frame; a fully occluded or out-of-frame target is negative for visible-target detection.
- For all scored views, save the capture-time Gazebo `robot_1` model pose as `world_from_base_link`, along with CameraInfo, static TF, odometry, and RGB-D timestamps. Use that direct world pose for projection. Do not reuse one pitched world-to-odom anchor across planar odometry translations: it creates a pose-dependent vertical error because odometry omits roll/pitch.
- For unoccluded simulator views, generate a candidate silhouette by projecting the known target box using the direct Gazebo base-link pose and capture-time intrinsics/extrinsics. A reviewer must inspect every candidate against RGB/depth and correct boundaries where required.
- For partial occlusion, the projected full-box silhouette is not ground truth. Intersect each camera ray with the known target box and retain pixels whose measured depth agrees with the predicted target-surface depth (initial diagnostic tolerance: 3 cm); review the result visually and correct any mismatch. Have a second reviewer verify all occlusion labels and a random 20% of other masks. Reviewers must not see SAM3 predictions while labeling.
- Negative images have an empty mask and an explicit reason/category. Reject frames with ambiguous target presence, invalid synchronization, missing calibration/pose, or a failed reviewer check.
- Save immutable raw RGB/depth and metadata, label masks, reviewer decision, annotation method, and SHA-256 values. Do not overwrite a label; version it and preserve the prior review record.

## Capture and deduplication

- Capture one scored frame after the robot has stopped and odometry reports zero velocity. Store RGB, depth, CameraInfo, static TF, odometry, direct per-capture Gazebo `world_from_base_link` pose, profile, episode ID, target state, intended distance/view/occlusion stratum, and simulator image digest. Do not use a reused world-to-odom anchor for scoring. Use odometry-feedback motion endpoints rather than a fixed number of velocity messages; simulator real-time factor makes message count a poor proxy for displacement.
- Capture an episode as a planned pose sequence. Do not treat repeated frames at one stationary pose as independent examples. Require a different pose or scene condition for each scored view; preserve all episode membership in the manifest.
- Verify timestamp skew, image dimensions, valid target-region depth, image/label alignment, and exact file hashes before scoring. Visually inspect overlays from every condition, not only selected examples.
- Use the supplied dataset validator before evaluation. It requires linked capture metadata, direct Gazebo pose, synchronized RGB-D/calibration, a stopped robot, valid masks, and split integrity. A valid manifest still requires human review and does not establish model performance by itself.

## Current gap and exit criteria

The original nine development labels were independently accepted; exact decisions and mask hashes are in [`capture-pilot-v3/label-review-decisions.json`](capture-pilot-v3/label-review-decisions.json). The development-only [prompt sweep](prompt-sweep-20261015/report.md) found `red mat` improves recall from 4/8 to 7/8 versus `red floor mat`, but one ~24%-visible view remains missed and recovered scores are close to the confidence threshold. A 40-row review manifest contains 20 positive and 20 negative samples across six episode IDs and passes structural validation. On 2026-10-15, the user deferred independent review of the 31 new candidates; the [expansion packet](development-expansion-20261015/label-review-packet.md) and decision template record that deferral, with all candidate decisions blank. No held-out acceptance set exists. Phase 2 remains on hold; resume label review before development scoring, resolve the demo's severe-occlusion contract, then collect the episode-separated held-out set, freeze configuration, and score held-out once. Any model/prompt/threshold change after that requires a fresh held-out set.
