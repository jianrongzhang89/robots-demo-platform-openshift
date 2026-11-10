# Phase 7 initial NetworkPolicy attempt — candidate #66

**Result: FAIL CLOSED; superseded by the candidate #68 diagnosis and repeat.**
The isolated NetworkPolicy was first applied with DNS allowed only to the
selected `openshift-dns` pods on port 53. Both ROS endpoint startup barriers
and the source/destination stream probes completed, but the operator runtime
did not meet its startup gate before timeout. The operator loopback check then
failed because the API correctly remained unavailable.

The failure prompted a focused policy probe and improved startup diagnostics.
They showed the resolver path also needs the OpenShift CoreDNS pod target port
5353. See the detailed [candidate #68 diagnostic failure](../live-network-policy-candidate-68-20261110/README.md)
and [corrected pass](../live-network-policy-candidate-68-repeat-20261110/README.md).

The Phase 6 pods were observed Running after this attempt, and the temporary
pod and fixture Secret were removed. This older bundle does not contain a
pre-run Phase 6 snapshot, so it is not independent before/after evidence. The
candidate #68 diagnostic failure and corrected repeat bundles do contain
normalized Phase 6/shared Phase 5 snapshots. This attempt's pod state, events,
container logs, and policy are checksummed in this directory.
