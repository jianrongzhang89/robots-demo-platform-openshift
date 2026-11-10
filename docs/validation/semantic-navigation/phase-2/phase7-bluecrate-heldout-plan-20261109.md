# Blue-crate held-out capture plan — November 9, 2026

**Status: capture matrix preregistered; recognition configuration is not frozen.**
The matrix was specified before any blue-crate SAM3 result was viewed. Do not
capture or score it until the development labels are reviewed and the prompt,
threshold, inference resolution, and visibility envelope are frozen. The
100-row assignment is in [`phase7-bluecrate-heldout-plan-20261109.json`](phase7-bluecrate-heldout-plan-20261109.json).
SHA-256: `68832768d91d8606d684666f1e2914f638254ff7b6011f4942afac437af607ae`.

The matrix reserves five complete held-out episodes. Each includes ten positive
and ten negative unique stopped views. This produces the required 50 per class
and meets the protocol's overlapping coverage quotas:

- Each class: 25 baseline and 25 dim-light views; 25 frontal and 25 oblique.
- Positives: 20 near, 15 mid, 15 far; 20 partially occluded views.
- Negatives: 20 similar-tile distractors, 20 ordinary-floor views, and 10
  target-out-of-view views.

Episode identifiers are disjoint from the three development episodes in the
current pilot. The deterministic per-episode assignment seed is recorded in the
JSON. Each sample has one planned scene/lighting/view/occlusion stratum; capture
operators must record actual pose, target distance, camera/depth/calibration,
lighting profile, synchronized timestamps, and simulator image digest. Reject
and document any sample that cannot meet its planned stratum; do not replace it
based on a model output.

This plan is not capture evidence, a frozen model configuration, or a Phase 2
pass. The pilot still needs blind label review and a larger development set
before configuration freeze. Occlusion rows require depth-ray labels and
independent review; all other labels receive primary review and the preregistered
random second-review subset.
