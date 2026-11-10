# Phase 7 live workflow under scoped NetworkPolicy — candidate #68

**Result: PASS for the isolated, single-pod qualification topology.** The
NetworkPolicy denied inbound pod traffic and allowed DNS plus TLS egress only
to the pinned `sam3-mat-v1` predictor. The first policy draft allowed DNS
Service port 53 but omitted the OpenShift DNS pod target port 5353; its failed
attempt is retained in [`live-network-policy-candidate-68-20261110`](../live-network-policy-candidate-68-20261110/README.md).
After adding 5353 for the exact `openshift-dns` pod selector, a scoped probe
resolved the model Service and completed a client-authenticated TLS 1.3
handshake. The full workflow then passed under that policy.

Runtime candidate #68 is pinned at
`sha256:b344a05fe7f3b8d31246c9af50d3436a03389704640e474fcfda2e091ed06f1b`;
its OpenShift build ran all 26 Phase 7 tests. In the live pod, ROS domains 181
and 182 each received all five required camera streams (78–80 messages per
topic). The adapter paired 97 RGB-D-CameraInfo triplets and emitted 67 fresh
results from the pinned red-mat model.

The mTLS verifier confirmed the operator listener was loopback-only. The
approved `red mat` request returned HTTP 200 with `changed:false` at generation
1; unapproved `blue crate` returned HTTP 400 without transition effects. Nav2
accepted a real goal after four submissions, both cancellation services
acknowledged, and the goal finished `STATUS_CANCELED`. All 410 native samples
remained disarmed with zero applied commands; maximum measured physical speed
was 0.0010071496 m/s. All 19 containers exited zero with no restarts.

The normalized Phase 6 and shared Phase 5 router snapshots are identical before
and after. Temporary pod and fixture credentials were deleted after evidence
capture. The NetworkPolicy remains installed, but its exact selector matches
no current pod; accepted Phase 6 pods do not match. This qualifies the network
boundary for this one-pod simulator topology only. It does not qualify
production identities, a multi-pod production topology, or a successful
approved prompt transition.

The bundle includes the exact manifest, applied policy, candidate build and
logs, pod YAML/description/events, every container log, and before/after
workload snapshots. Verify the bundle with `sha256sum -c SHA256SUMS`.
