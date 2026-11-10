# Live semantic adapter full topology attempt — November 10, 2026

**Result: FAIL before goal submission.** The candidate pod ran the real simulator, RGB-D compressor, candidate semantic HTTP adapter, and Nav2 image. The compressor produced synchronized RGB-D pairs with zero observed skew. The verifier failed before sending a goal because Nav2's `navigate_to_pose` action server never appeared.

Diagnosis from the captured bridge logs: remote camera publishers crossed to domain 182, but scan, odometry, and TF publishers did not. Their exact bridge regexes expected leading slashes while the remote Zenoh publisher names were announced without them. This prevented the Nav2 entrypoint's required-input checks from completing. No navigation goal was submitted, cancellation was not attempted, and no live SAM3 inference result was verified. This is diagnostic evidence, not a pass.

The Phase 6 simulator, Nav2, and SAM3 pods remained Running on their original nodes; see `phase6-unchanged.txt`. The bridge filters have since been corrected for the next run. Per-container logs, pod state, and hashes are retained here.
