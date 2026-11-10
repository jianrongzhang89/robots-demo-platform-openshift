# Blue-crate Phase 2 development-label review

**Status: awaiting independent human review.** This packet contains no SAM3 predictions.
Review every RGB frame against its candidate binary mask, overlay, depth image, and capture metadata.
Accept, correct into a new versioned mask, or reject each row. Do not overwrite source masks.

[Open the six-frame RGB/candidate-mask contact sheet](label-review-contact-sheet.jpg).

The crate-absent row was generated with the model omitted from the Gazebo scene while the red-mat distractor remained; its metadata records the scene/entity verification. Confirm visual target absence and the stated negative reason.

| ID | Candidate class / stratum | RGB | Candidate overlay | Mask | Depth | Review decision |
|---|---|---|---|---|---|---|
| `initial-0000` | positive; mid; front; simulator-default | [RGB](initial/initial-0000.jpg) | [overlay](initial/initial-0000-overlay.jpg) | [mask](initial/initial-0000-mask.png) | [depth](initial/initial-0000-depth.png) | pending |
| `near-0000` | positive; near; front; simulator-default | [RGB](near/near-0000.jpg) | [overlay](near/near-0000-overlay.jpg) | [mask](near/near-0000-mask.png) | [depth](near/near-0000-depth.png) | pending |
| `oblique-0000` | positive; near; oblique; simulator-default | [RGB](oblique/oblique-0000.jpg) | [overlay](oblique/oblique-0000-overlay.jpg) | [mask](oblique/oblique-0000-mask.png) | [depth](oblique/oblique-0000-depth.png) | pending |
| `out_of_view-0000` | negative; out_of_view; out_of_view; simulator-default; reason: blue-crate-fixture-out-of-camera-field-of-view | [RGB](out_of_view/out_of_view-0000.jpg) | [overlay](out_of_view/out_of_view-0000-overlay.jpg) | [mask](out_of_view/out_of_view-0000-mask.png) | [depth](out_of_view/out_of_view-0000-depth.png) | pending |
| `far-0000` | positive; far; front; simulator-default | [RGB](far/far-0000.jpg) | [overlay](far/far-0000-overlay.jpg) | [mask](far/far-0000-mask.png) | [depth](far/far-0000-depth.png) | pending |
| `no_object-0000` | negative; target_absent; front; simulator-default; reason: blue-crate-model-absent; red-mat-distractor-visible | [RGB](no_object/no_object-0000.jpg) | [overlay](no_object/no_object-0000-overlay.jpg) | [mask](no_object/no_object-0000-mask.png) | [depth](no_object/no_object-0000-depth.png) | pending |

## Review instructions

- Judge whether the object is present and visibly detectable in the RGB image, independently of the current presence label.
- Check whether all and only visible crate pixels are in the mask. Use the depth image and direct Gazebo capture pose/calibration in the linked per-frame manifest to inspect projection boundaries.
- For any corrected mask, save a new file/version, preserve the original, and record the new SHA-256 and correction reason.
- Record `accepted`, `corrected`, or `rejected`; include reviewer name, date, notes, and presence/mask decisions in `review-decisions-template.json`.
- Protocol requires a second reviewer for all partial-occlusion masks and a random 20% check of the other masks. This pilot has no partial-occlusion views; the template selects two rows for independent second review.
- These are development samples only. Reviewing them does not make them held out or authorize SAM3 scoring as an acceptance result.

Capture metadata for each frame is in the linked `manifest.json` under its sample directory. The root `manifest.jsonl` preserves the candidate record and hashes.
