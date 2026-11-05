# S1 model-server packaging and qualification

Date: October 30, 2026 (America/New_York). **G1: HOLD.** Server implementation,
local conformance tests and resource validation are available. No isolated
InferenceService or serving endpoint has been deployed. No served GPU parity,
three-cycle cold-start, dashboard visibility or live no-egress result is claimed.

The [serving proposal](../../../../semantic-navigation-openshift-ai-serving-proposal.md)
defines S1 as packaging the model server, separate from the accepted navigation
Phases 0–6. Its upstream **G0 technical verification now passes**. OpenShift AI
3.4.2, COO 1.5.3, Perses/dashboard and MaaS reconciliation are healthy. The
baseline pair, destination storage/credentials, GPU reservations, isolation
and final admission checks are recorded in the
[G0 completion report](../S0/g0-completion-20261030/report.md). The user approved G0 on October 31, 2026. The temporary G0 transport probe loaded no model;
it does not replace G1 endpoint qualification.

## Delivered

- [Runtime package](../../../../../apps/semantic-model-server/README.md): shared
  SAM3 runner/contract, checksum verification, build provenance, additive loaded
  identity, full-size warm-up, fixed policy and single-worker admission.
- Mutually authenticated HTTPS, client-to-robot/stream authorization, bounded
  request sizes/uploads/connections, explicit overload/errors, separate health
  probes and hung-worker restart signals. Plain health endpoints do not serve
  inference. No ROS or motion credentials are used by this process.
- [Resource renderer](../../../../../helm/semantic-navigation/openshift-ai/render.py):
  RawDeployment candidate, fixed L40S replica, dedicated service identity, TLS
  ClusterIP endpoint and ingress/egress policies. Image references require digests.
- Read-only prerequisite inventory, hashed replay source selection, local GPU
  baseline freezing, and served parity scoring. The replay checker retains each
  frame's success/failure, verifies complete deployment identity and rejects
  modified input files. It does not close the standing recognition waiver.

## Verification

| Check | Result | Evidence |
| --- | --- | --- |
| Server and qualification tests | 19 PASS | `../S0/g0-completion-20261030/server-tests.txt` |
| Existing perception/contract regression tests | 27 PASS | `shared-regression-tests.txt` |
| Serving-resource API server dry-run | PASS in actual serving project, final image and reserved node | `../S0/g0-completion-20261030/destination-admission.txt` |
| Build-resource API server dry-run | PASS | `build-dry-run-2.txt` |
| GPU/precision profile readback | L40S, BF16 supported, Torch 2.10.0+cu128, CUDA 12.8 | `../S0/runtime-hardware.json` |
| Runtime image build | Two builds PASS; final includes import smoke check | `build-results.json` |
| Actual GPU parity / cold starts / endpoint security and no-egress | NOT RUN | G1 remains HOLD |

The tests include actual TLS handshakes and connection reuse, no certificate,
trusted-but-unbound certificate, robot spoofing, prompt/version/identity errors,
malformed/oversized bodies, empty output, overload, expired/late work, hung worker,
readiness/precision/checksum failure, union-mask parity and a replay with a
tampered file. The runner in these tests is deterministic, not SAM3 on a GPU.

Commands (repository root):

```sh
PYTHONPATH=apps/semantic-model-server:apps/semantic-perception python3 -m unittest discover -s apps/semantic-model-server/tests -v
PYTHONPATH=apps/semantic-perception python3 -m unittest discover -s apps/semantic-perception/tests -v
python3 scripts/semantic-navigation/check_serving_prerequisites.py --output /tmp/serving-inventory.json
oc apply --dry-run=server -f docs/validation/semantic-navigation/openshift-ai/S0/g0-completion-20261030/rendered-candidate.json
oc apply --dry-run=server --validate=true -f helm/semantic-navigation/openshift-ai/build.yaml
```

The initial serving schema dry-run used `semantic-navigation` before the
destination project was provisioned. Its image was explicitly non-runnable
`registry.invalid/semantic-model-server@sha256:` followed by 64 zeroes. This
validates API compatibility only. `rendered-candidate.json` preserves that initial
candidate; `rendered-built-image.json` records the final built image for the
intended project. The subsequent G0 record contains the final reserved-node
manifest and successful destination admission, image pulls, checkpoint copy,
transport credentials/routing and GPU scheduling verification.

Two earlier validation issues were retained: the local `oc` version rejects
`--validate=strict` (see the first dry-run logs); rerunning with its supported
`--validate=true` succeeds. The first TLS test run had three failures because the
test CA omitted the key-usage extension required by Python 3.14's certificate
validation. Explicit CA/leaf extensions fixed the fixture; certificate
verification was not disabled. `initial-test-attempt.json` records the failure
summary. Earlier successful test logs remain beside the final 18-test run.

## Cluster effects and remaining work

The initial S1 packaging step created the `semantic-model-server` ImageStream,
`semantic-model-server-s1` BuildConfig and image builds in `semantic-navigation`.
Subsequent G0 work provisioned the serving project, temporarily switched the
local SAM3 pod into the accepted private baseline topology, restored it, and
reserved separate serving/rendering GPUs. The ROS adapter and safety controls
remain unchanged. Build 2 includes an import smoke check inside the inherited
runtime environment; neither build loads a checkpoint or uses a GPU.

The current SAM3 dependency image is pinned to
`sha256:478ec01a7a47fbb0c862fbbef495c71b4a512ff59ed8d6ed5b7234422cc35686`,
also required by the existing Phase 6 trial preflight. The checkpoint hash is
checked independently in `../S0/checkpoint-sha256.txt`. Shared Python sources
are copied from one repository location into the server, not forked. The final
gate JSON includes their hashes and the working-tree state; no new commit was
created.

G0 technical checks passed: baseline hull exposure was 1.409 m off and 0.000 m
on, both trials were collision-free, the copied checkpoint matched its hash,
and separate L40S serving/A10G rendering reservation pods are Running. The
restored local SAM3 pod emitted valid results. Leaf credentials expire November
7, 2026 at 02:58:59 UTC. Recheck credentials and release each reservation only
when its pinned replacement is ready to schedule.

After G0, build the frozen local response set on isolated GPU capacity, provision
the pinned endpoint, verify Pod image IDs against expected identity, and run all
live G1 checks. Three cold starts must reach readiness only after verified weights
and warm-up. Test malformed and maximum-size traffic through the actual endpoint,
authentication and robot authorization, restart recovery, dashboard registration
and egress denial. Compare every frozen frame on the same hardware/precision at
IoU ≥0.99, 100% empty/nonempty agreement and occupied-fraction difference ≤0.005.
Keep failed attempts and investigate mismatches. Neither code tests nor a built
image constitutes G1 acceptance.
