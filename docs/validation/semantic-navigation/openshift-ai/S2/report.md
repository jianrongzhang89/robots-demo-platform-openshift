# S2 CPU ROS adapter qualification

October 31, 2026. **G2 PASS; user signed off on October 31, 2026.** G1 is PASS and user-approved, recorded in [its gate result](../S1/gate-result.json). The user's G1 sign-off authorized this G2 implementation.

The remote backend is implemented and deployed as `semantic-navigation/semantic-s2-adapter` on non-GPU worker `ip-10-0-53-174.ec2.internal`. It consumes the G1 endpoint through mTLS and the complete pinned deployment identity. The accepted local SAM3 pod, serving deployment and rendering reservation remain running. The model's three shared source hashes are unchanged from G1.

| G2 requirement | Evidence and result |
| --- | --- |
| CPU-only startup without weights | Image build asserts Torch absent; deployed replay verifies no Torch, `/models`, or NVIDIA devices. Node advertises no GPU resource. No GPU request or checkpoint volume in pod. PASS |
| Explicit backend, robot and stream | `backend=http`, `robot_id=robot_1`, `stream_id=camera/color`; immutable runtime configuration, no automatic fallback. PASS |
| Bounded HTTP transport and buffers | Whole-operation deadline, maximum 28 MiB response, one client request in flight, one queued bundle, at most 20 sensor entries. Tests cover DNS stall, slow headers, hang, overload and bursts. PASS |
| Reset, correlation and retained data | Real ROS tests suppress delayed results after clock reset, missing retained bundle, duplicate inputs/replayed replies, wrong robot/sequence and expired requests. Contract tests also reject reordered replies. PASS |
| Authentication, network and model failures | Real mTLS fixture injects 401/403/429/500/503/504, connection loss, truncation, oversized responses and hangs. Actual ROS tests verify no publication for 401/403/429/503, network loss and hang. Identity mismatch latches failure. PASS |
| Readiness follows fresh sensor results | Model metadata alone leaves readiness false. Valid RGB-D results grant readiness only to their capture deadline; idle status and Kubernetes readiness return false. PASS |
| Live served ROS outputs | Three frozen cases across two replay batches match G1 union masks exactly; original mask/cloud headers preserved; synthetic depth remains organized and pixel-aligned. PASS |
| Diagnostic isolation | Private DDS domain 188, loopback interface, `/g2/robot_1/...` topics; observed graph contains only adapter and replay probe. No costmap or motion connection. PASS |

Validation passed on the first build and both live replays: **42 unit tests**, **12 actual ROS tests during build**, and the same **12 ROS tests in the deployed CPU container** on private domain 189. ROS fault tests use an in-process deterministic mTLS server; they are not live endpoint fault injections. The live G1 endpoint supplied six predictions across two three-frame batches. Before the second batch, the replay harness was made repeatable by letting `/clock` rollback processing settle before generating a fresh capture trace; all output assertions remain unchanged.

| Frozen case | Mask pixels | Exact G1 parity | Capture-to-observer latency, batches 1 / 2 |
| --- | ---: | --- | ---: |
| Mat | 5,870 | Yes | 405.106 / 273.689 ms |
| Absent target | 0 | Yes | 172.389 / 153.056 ms |
| Empty mask | 0 | Yes | 165.061 / 460.500 ms |

These are six functional samples, not sustained latency statistics. RGB comes from the frozen G1 cases; depth is synthetic at one metre, intrinsics are synthetic and timestamps are freshly generated. This verifies adapter data handling, not capture-time scene geometry, recognition accuracy or moving navigation. The standing recognition waiver remains unchanged.

The CPU image is `image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-cpu-adapter@sha256:20ea4f5e6bc30646f48b29895eb071d40403f8c20b0c1526aeacf06dce716d4b`. The pod requests 1 CPU/1 GiB and limits 2 CPU/2 GiB; it has zero restarts at evidence capture. The pod stays Running and intentionally not Ready while no fresh input is supplied. The G1 InferenceService remains Ready. Client/server certificates retain their November 7, 2026, 02:58:59 UTC expiry.

Evidence is in [g2-qualification-20261031](g2-qualification-20261031/): [build log](g2-qualification-20261031/build-1.log), [deployed ROS tests](g2-qualification-20261031/cpu-ros-tests.txt), [first replay](g2-qualification-20261031/live-1.json), [second replay](g2-qualification-20261031/live-2.json), [pod resources](g2-qualification-20261031/adapter-resources.json), [idle status](g2-qualification-20261031/idle-status.json), [source hashes](g2-qualification-20261031/source-hashes.json), and [gate result](gate-result.json). The [adapter README](../../../../../apps/semantic-perception/README.md) describes configuration and reproduction.

G3 remains: connect the served adapter to the controlled real sensor path, measure sustained capture-to-consumer timing and freshness, and verify capture-time projection/TF geometry under delay and reset conditions. G4 remains the paired navigation experiment. G2 does not authorize claims about either result.
