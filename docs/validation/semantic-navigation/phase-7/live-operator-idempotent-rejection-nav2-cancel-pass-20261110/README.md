# Phase 7 live operator and Nav2 cancellation — November 10, 2026

**Result: PASS for this isolated simulator subgate.** The pod exercised the live Phase 7 mTLS operator runtime, the pinned red-mat SAM3 model adapter, active Nav2 cancellation, and the native watchdog together. All 15 containers exited with code 0. The accepted Phase 6 simulator, Nav2, SAM3, and router pods remained Running on their original nodes; before/after snapshots are included.

The operator policy check authenticated `operator-17`. An idempotent request for the already active `red mat` returned HTTP 200 with `changed: false`, generation 1. The subsequent unapproved `blue crate` request returned HTTP 400 before any stop, Nav2 cancellation, or prompt change. The adapter remained ready on `red mat`, generation 1, with prompt-transition permit verification enabled; native drive stayed disarmed with zero applied commands and no stop event.

The corrected adapter received CameraInfo and capture/compression trace streams using compatible best-effort QoS, paired 49 RGB-D-CameraInfo triplets, and emitted 31 fresh results during the verifier window. The real `/navigate_to_pose` action accepted a goal after four submissions. The cancel proxy acknowledged one active goal; Nav2 returned `STATUS_CANCELED`. The native watchdog recorded 411 samples; maximum applied linear/angular commands were both zero, max physical speed was 0.0010036451 m/s, below the 0.002 m/s gate.

## Pinned candidates and build checks

- Adapter: `sha256:d5b22eae66497af2bd3230d43767f862d6b0923d73ffb8f54a865e21c9258c28`; 46 unit tests and 17 ROS integration tests passed, including a regression check that metadata and trace subscriptions request BEST_EFFORT QoS.
- Runtime: `sha256:81df532f19a65e8de4b8c895918d8bc64702e7ace1d0667f47197efe6fbcbdb5` (build #62); all 24 Phase 7 tests passed.
- Pinned serving identity: `sam3-mat-v1`, `red mat`, model revision `3c879f39826c281e95690f02c7821c4de09afae7`, weights SHA-256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`.

The failure that exposed the QoS mismatch is retained in [the preceding diagnostic attempt](../attempts/live-metadata-best-effort-qos-failure-20261110/README.md). The ephemeral pod and validation-only Secret were deleted after evidence capture. This pass is a live simulator subgate only; it does not qualify a successful approved prompt transition/restart/stale-result workflow, an additional object category, production credentials or network policy, or overall Phase 7 PASS.
