# S1 model-server packaging and live qualification

Date: October 31, 2026 (America/New_York). **G1 technical PASS.** G0 is user-approved; G1 was signed off by the user on October 31, 2026. The pinned SAM3 InferenceService is deployed and Ready in `semantic-model-serving`.

The [full G1 report](g1-qualification-20261031/report.md) and [gate result](gate-result.json) contain the deployed configuration, frozen evaluation set, retained attempts and handoff.

| Check | Result |
| --- | --- |
| Three frozen cases, three replay batches | Nine exact comparisons: IoU 1.0, 100% empty agreement, zero occupied-fraction difference |
| Three independent process/model cold starts | All observed not-ready before verified warm readiness; 30.942 / 10.425 / 10.779 s from probe-loop start |
| Live contract/security checks | 22 PASS, including request limits, authorization and bounded overload |
| Whole-process hang and restart | Automatic liveness recovery; post-recovery parity exact |
| Network isolation | Authorized data access only; client health/agent access and inference egress denied |
| OpenShift AI registration | Dashboard API and installed frontend selection rules verified; missing runtime label corrected |
| Local regression tests | 19 server/qualification + 27 shared perception/contract tests PASS |

The supported internal origin is `https://sam3-mat-v1-tls.semantic-model-serving.svc:8443`, using the custom JSON contract and client certificates. The generated KServe HTTP status URL is not the application endpoint. Model-container requests/limits remain 3/6 CPU, 12/24 GiB and one L40S; the injected KServe agent adds 100m CPU/100 MiB requests and 1 CPU/1 GiB limits within quota.

The serving reservation was handed to the model deployment. The accepted local SAM3 path and separate rendering GPU reservation remain available. No ROS adapter or robot motion was switched to remote inference. G2–G4 remain separate work, and the standing recognition waiver remains in force.

Certificates expire November 7, 2026 at 02:58:59 UTC. Visual browser inspection was unavailable; dashboard verification used its authenticated API and the actual installed frontend selection code. Worker-only hang timeout coverage is local; the live fault stopped the entire model-server process.

The runtime package remains [apps/semantic-model-server](../../../../../apps/semantic-model-server/README.md). The final image is recorded in [build-results.json](build-results.json); neither its bytes nor the shared SAM3 inference code changed during G1. Initial packaging history is preserved in [the earlier report](g1-qualification-20261031/packaging-report-before-qualification.md).
