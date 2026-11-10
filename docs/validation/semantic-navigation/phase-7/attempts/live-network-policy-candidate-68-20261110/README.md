# Phase 7 live workflow under initial NetworkPolicy — candidate #68

**Result: FAIL CLOSED; retained for diagnosis.** Candidate #68
(`sha256:b344a05fe7f3b8d31246c9af50d3436a03389704640e474fcfda2e091ed06f1b`)
started under the first DNS policy revision. The two-sided publisher/subscriber
barriers and both 20-second ROS stream probes passed, but the operator API did
not start. The new redacted startup diagnostic reported:

- adapter status was received, but the adapter was not ready;
- native status had fault `native_capture_stale`;
- the Nav2 cancel proxy was not ready;
- the adapter parameter service was ready.

An in-pod resolver probe timed out for the model Service. The initial policy
allowed DNS Service port 53 but not the OpenShift CoreDNS pod target port 5353.
The policy was corrected to permit UDP/TCP 5353 only to the labeled DNS pods,
while retaining the cluster DNS Service IP allowance. A policy-selected
DNS/mTLS probe then succeeded, followed by the full passing
[candidate #68 repeat](../live-network-policy-candidate-68-repeat-20261110/README.md).

Phase 6 and the shared Phase 5 router snapshots were identical before and after
this failed attempt. All candidate containers shut down; temporary pod and
fixture Secret were removed. The bundle contains pod status, events, policy,
every container log, and normalized before/after snapshots. Verify it with
`sha256sum -c SHA256SUMS`.
