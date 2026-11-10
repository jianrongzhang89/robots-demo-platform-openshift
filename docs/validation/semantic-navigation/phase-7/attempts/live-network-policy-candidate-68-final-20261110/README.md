# Phase 7 minimal-DNS policy attempt — candidate #68

**Result: FAIL CLOSED; not a qualification pass.** This attempt tested the
narrower variant that allowed DNS only to selected CoreDNS pods on port 5353.
It was scheduled on `ip-10-0-46-92.ec2.internal` because the original pinned
node temporarily lacked enough requested CPU for the 19-container pod.

The ROS stream probes did not receive all five streams. Nav2 failed its
required `/odom` startup wait. Candidate #68's redacted startup diagnostic
reported that the adapter was not ready, native capture had gone stale, and
the cancellation proxy was ready while the adapter parameter service was
ready. The operator API remained unavailable and both verifiers failed closed.
All containers shut down; Phase 6 and shared Phase 5 router snapshots were
identical before and after.

The [policy-qualified repeat](../live-network-policy-candidate-68-repeat-20261110/README.md)
passed with both the exact cluster DNS Service VIP on port 53 and the selected
OpenShift DNS pods on translated target port 5353. The deployed policy and the
test manifest were restored to that passing configuration and the original
test node selection. See `network-policy.yaml` and `manifest.yaml` for this
failed attempt's exact configuration. Verify the bundle with
`sha256sum -c SHA256SUMS`.
