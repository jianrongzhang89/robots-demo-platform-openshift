# Live Phase 7 operator rejection + Nav2 cancellation — November 10, 2026

**Result: PASS for live mTLS rejection of an unapproved prompt, followed by actual Nav2 cancellation and native no-motion in one isolated topology.** Runtime candidate #60 (`sha256:61bdebda24415fd734311d118f6c02a6aef3c7971399fd57209984ebcd536a4a`) passed all 22 in-image Phase 7 tests, including explicit enabled-transition status verification and signal-driven API shutdown.

The temporary mTLS operator `operator-17` POSTed `blue crate` to the live API and received HTTP 400, `prompt is not approved`. No stop or cancel was applied by the rejection path. The adapter stayed ready on its only approved prompt, `red mat`, at policy generation 1; the fixture permit verifier was enabled. The model service identity and weights digest matched the pinned red-mat serving identity. At qualification it reported 47 paired triplets and 29 fresh results.

After the rejection check, the verifier submitted a real `/navigate_to_pose` goal. Nav2 accepted it on attempt 4. The cancellation proxy acknowledged the active goal (`goals_canceling: 1`), and Nav2 returned `STATUS_CANCELED` (5). Across 416 native watchdog samples, motion remained disarmed, applied linear/angular commands remained zero, and maximum measured speed was 0.0010036285 m/s, below the 0.002 m/s threshold. All 15 containers exited 0, including graceful operator API shutdown.

The ephemeral pod and validation-only Secret `semantic-phase7-fixture-credentials` were deleted after evidence capture. The accepted Phase 6 simulator, Nav2, and SAM3 pods remained Running on their original nodes; see `phase6-unchanged.txt`.

This closes the combined live rejection + actual Nav2 cancellation/no-motion subgate. It does not qualify a successful live prompt change, restart/stale-result recovery, production identity and signing-key lifecycle, production network policy, or an additional object category. One intervening retry failed because the adapter received no RGB-D triplets; that diagnostic is retained at `../attempts/live-operator-rejection-inference-timeout-20261110/`. Overall Phase 7 remains **HOLD** for those gates and human sign-off.
