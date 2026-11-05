# Verification after COO 1.5.3 installation

The user installed COO 1.5.3. Its CSV is `Succeeded`, and all four operator
deployments are available. Perses dashboard conversion is now `Webhook`, with
a populated CA bundle and a working service.

Both the cluster dashboard and MaaS usage dashboard produce equivalent content
through v1alpha1 and v1alpha2. A v1alpha1 server-side apply dry-run for the MaaS
dashboard succeeds. The original missing-conversion failure is no longer
reproduced by these API checks.

OpenShift AI's dashboard completed its rollout: two updated, ready replicas and
`DashboardReady=True`.

The newly created Perses server initially crashed because its old image rejected
`--web.tls-min-version`. This matches the public symptoms in
[Red Hat solution 7146251](https://access.redhat.com/solutions/7146251); its
subscriber-only resolution was not available in the public page.

The OpenShift AI monitoring controller had already changed the Perses CR and
StatefulSet to image
`sha256:27553fd6d4b4983475a0d9a4ccc7d7fa63b1bd4b48f0e5cb2d18963fe232cfd5`.
The failed pod still used the old image, and the ordered StatefulSet rollout was
stalled. After saving its state and verifying the replacement template, the
assistant gracefully deleted only `data-science-perses-0`. Its PVC and custom
resources were preserved. The replacement is ready with zero restarts. This is
the recovery mechanism described in the
[Kubernetes StatefulSet documentation](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/#forced-rollback).

Overall `default-dsc` readiness is still false because `ModelsAsServiceReady`
is false. The MaaS controller has a separately confirmed failure: `OOMKilled`
at a 512 MiB memory limit, with 51 restarts in the captured snapshot. Its
component status still contains the old schema error even though the direct
server-side apply dry-run now passes. Memory sizing and subsequent successful
MaaS reconciliation remain to be addressed; no memory or operator configuration
was changed in this verification.

G0 remains HOLD for that platform issue and the other baseline/provisioning
prerequisites. This check does not claim the entire observability stack is
healthy or that serving qualification has passed.

See [verification.json](verification.json) for measured state, actions and
timestamps. The saved pod, StatefulSet, dashboard deployment, DSC, CRD and OOM
snapshots provide the supporting evidence.

Follow-up: at the user’s request, the MaaS controller memory limit was raised
from 512 MiB to 1024 MiB (`1Gi`). Its rollout completed and the replacement was
ready with zero restarts after the startup check. CPU and memory requests were
unchanged. Overall AI readiness still needs separate confirmation; see
[the memory-change record](maas-memory-increase.json).
