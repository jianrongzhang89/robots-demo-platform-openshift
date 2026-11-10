# Phase 7 managed credential fixture — November 10, 2026

**Result: PASS for Secret consumption in the isolated integration fixture.**
The candidate runtime loaded its signing key, operator map, server certificate
and key, client CA, and operator client certificate and key from a read-only
Kubernetes Secret mount. The fixture then exercised the candidate operator
runtime against the Gazebo native watchdog and fixture ROS adapter/Nav2
endpoints.

The integration result is recorded in [`result.json`](result.json). It reports
20 alternating mTLS prompt changes through generation 22, 21 atomic applies,
stationary watchdog proof at every apply, rejection of a failed Nav2 cancel,
recovery after terminating the runtime during a pending transition, an
idempotent retry, and no motion resume. The fixture adapter and Nav2 services
are test endpoints; this does not qualify a production Phase 7 topology or
operator identity lifecycle.

The latest rerun used the runtime candidate digest
`sha256:1c4175d7d3b8a59f685387fa3aff64ac1d20965b6d0a7df34ac704cd267fe080`.
Its image build ran all 17 Phase 7 Python tests successfully. The OpenShift Job
`semantic-phase7-managed-credentials-test` completed successfully with this
image and the mounted Secret. The transition fixture exercised the new
acknowledged cancellation-proxy client. The fixture completed 21 atomic
applies, 21 native stationary proofs, restart recovery, and 20 alternating
mTLS transitions through generation 22 with no motion resume. It uses local
fixture service endpoints rather than production ROS nodes. The rerun log is
clean after executor shutdown was tightened in the verifier. The temporary
random fixture Secret was deleted after the Job completed; its credential
values are not part of this evidence.

Production operator certificates, signing key provisioning and rotation,
identity administration, production network policy, and a complete separate
Phase 7 runtime topology remain required before production sign-off.
