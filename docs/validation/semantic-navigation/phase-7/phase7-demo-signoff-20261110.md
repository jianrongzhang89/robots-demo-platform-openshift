# Phase 7 demo qualification and sign-off — November 10, 2026

## Decision

**DEMO PASS — reviewed and signed off by the user on November 10, 2026.** The
accepted scope demonstrates the Phase 7 prompt-control and safety use cases in
isolated simulation and fixture topologies. It does not claim production
deployment, general object recognition, or physical-robot qualification.

This demo-scoped decision supersedes the production-focused HOLD recommendation
in the [runtime protocol evidence register](runtime-prompt-protocol-20261109.md).
That register remains the detailed history and source for the raw evidence.

## Demo scope and acceptance criteria

| Demo use case | Acceptance | Evidence |
| --- | --- | --- |
| Live semantic safety workflow | Pinned SAM3 service returns fresh `red mat` results; an authenticated idempotent request preserves generation; unapproved `blue crate` is rejected without transition effects; real Nav2 goal is canceled with both service acknowledgements; watchdog remains disarmed with zero applied commands and measured speed below 0.002 m/s. | [Candidate #68 live run under the isolated NetworkPolicy](attempts/live-network-policy-candidate-68-repeat-20261110/README.md) |
| Runtime prompt-control mechanics | In the isolated credential fixture, an authenticated signed transition waits for native stationarity, both Nav2 cancel acknowledgements, an atomic generation change, and fresh matching readiness. Restart during an in-flight transition recovers without duplicate apply; 20 alternating fixture transitions complete; stale-generation results are rejected; motion is never automatically resumed. | [Managed credential and runtime fixture](../security/phase7-managed-credentials-20261110/README.md), [generation-barrier evidence](runtime-prompt-protocol-20261109.md#test-results) |
| Safety boundary and Phase 6 preservation | Demo topology is isolated; the candidate NetworkPolicy denies ingress and limits egress to DNS and the pinned predictor. Before/after Phase 6 and shared Phase 5 router snapshots are identical. | [Policy-qualified run](attempts/live-network-policy-candidate-68-repeat-20261110/README.md) |

The live inference/navigation demo and prompt-transition mechanics fixture are
separate runs with different endpoints. The fixture proves the operator and
generation protocol; it does not claim that the live red-mat model service
accepts a new prompt. Together they demonstrate the selected Phase 7 use cases
without changing the pinned serving identity.

## Explicitly outside this sign-off

- Production hosting, production operator identities, production signing-key
  lifecycle, multi-pod production NetworkPolicy, availability, and deployment
  operations.
- Recognition quality for `blue crate` or any additional object category. The
  current model identity allows only `red mat`; the live `blue crate` request
  is an authorization-rejection check, not a recognition test.
- Held-out recognition metrics, applicable Phases 2–6 qualification for new
  categories, and physical-robot use.

These items remain future work if the project later needs production operation
or additional recognized categories. They do not block the demo-scoped Phase 7
decision.

## Repeating the demonstrations

The recorded evidence is sufficient for review. To rerun the demonstrations
in the current OpenShift project:

1. Confirm the accepted Phase 6 workloads are healthy and no Phase 7 demo pod
   is running. Keep the Phase 7 isolation policy installed.
2. Run the credential fixture first, using a short-lived validation Secret:

   ```sh
   python3 scripts/semantic-navigation/provision_phase7_fixture_credentials.py
   oc delete job semantic-phase7-managed-credentials-test -n semantic-navigation --ignore-not-found
   oc apply -f helm/semantic-navigation/openshift-ai/phase7-managed-credentials-validation.yaml
   oc wait --for=condition=complete job/semantic-phase7-managed-credentials-test -n semantic-navigation --timeout=8m
   oc logs job/semantic-phase7-managed-credentials-test -n semantic-navigation
   ```

3. Run the live semantic/Nav2 demo with the same validation Secret:

   ```sh
   oc delete pod semantic-phase7-live-nav2-cancel -n semantic-navigation --ignore-not-found
   oc apply -f helm/semantic-navigation/phase7-live-nav2-cancel.yaml
   oc wait --for=jsonpath='{.status.phase}'=Succeeded pod/semantic-phase7-live-nav2-cancel -n semantic-navigation --timeout=12m
   oc logs pod/semantic-phase7-live-nav2-cancel -n semantic-navigation --all-containers=true
   ```

4. Save the Pod JSON/YAML, verifier result, logs, and before/after Phase 6
   snapshots to a new dated evidence directory. Then delete the demo Pod and
   validation Secret; do not delete or patch accepted Phase 6 resources.

The fixture Secret contains randomly generated credentials and is validation
only. The demo Pod is ephemeral and has no service or route. The NetworkPolicy
selects only the Phase 7 demo labels; no current Phase 6 Pod matches them.

## Reviewer disposition

**Reviewer disposition:** ☑ DEMO PASS  ☐ HOLD  ☐ FAIL<br>
**Reviewer:** User (explicit conversation sign-off)  **Date:** 2026-11-10<br>
**Comments / follow-up:** Approved for the demo-only scope above.

The user confirmed review and sign-off for **DEMO PASS**. A future production
or additional-category effort requires a separate acceptance scope and its own
gates.
