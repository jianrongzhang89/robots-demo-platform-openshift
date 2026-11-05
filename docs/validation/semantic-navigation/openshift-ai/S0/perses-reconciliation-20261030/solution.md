# Perses reconciliation diagnosis and recovery

Investigated October 30, 2026 (America/New_York). Status: **repair prepared and
Subscription manifest server-dry-run passed; no cluster changes applied**.

Follow-up: the user subsequently installed COO 1.5.3. Conversion and the
OpenShift AI dashboard recovered; see the
[post-install verification](after-coo153/report.md) for the Perses pod recovery
and remaining MaaS memory failure. The diagnosis and procedure below preserve
the original pre-repair findings.

## Finding

The OpenShift AI 3.4.2 reconciliation is encountering a broken Cluster
Observability Operator (COO) installation. This is more specific than an
unsupported dashboard field or a need to upgrade OpenShift AI again.

Observed directly:

- COO Subscription `cluster-observability-operator` in
  `openshift-cluster-observability-operator` claims installed CSV
  `cluster-observability-operator.v1.5.1` and reports `UpgradePending`.
- That CSV is absent. There are no operator Deployments, Pods or Services in its
  namespace, including no Perses controller or conversion webhook service.
- Its existing OperatorGroup is present and there is exactly one. Preserve it.
- The four Perses CRDs remain. `PersesDashboard` serves v1alpha1 and v1alpha2,
  stores v1alpha2, and currently has `spec.conversion.strategy: None`.
- v1alpha1 has `spec.layouts`, `spec.panels` and `spec.duration`. v1alpha2 puts
  those fields under `spec.config`. Three existing dashboards contain the new
  `spec.config` structure.
- The running OpenShift AI image ships v1alpha1 dashboard and MaaS manifests;
  their headers are archived in `ai-dashboard-manifest-header.txt` and
  `ai-maas-manifest-header.txt`.
- OpenShift AI logs report conversion of merged objects to v1alpha2 failing on
  those old top-level fields. With conversion disabled, changing API versions
  does not translate the field structure.

The original, already-approved `install-5m892` bundle is still cached in
`openshift-marketplace`. Its decoded **1.5.1** CSV explicitly declares a
`ConversionWebhook` at `/convert`, served by deployment `perses-operator` on
port 9443, covering `persesdashboards.perses.dev`. The original CRD manifest also
specifies a webhook. This proves the missing conversion is part of the original
operator installation, not a newly invented workaround. See
[original-bundle-proof.json](original-bundle-proof.json).

The evidence does not establish who removed the operator resources or when.
It does not establish that the OpenShift AI upgrade itself deleted them.

Red Hat documents that COO installs and manages the Perses operator and CRDs.
OpenShift AI's enabled observability stack requires COO.
[COO Perses architecture](https://docs.redhat.com/en/documentation/red_hat_openshift_cluster_observability_operator/1-latest/html/ui_plugins_for_red_hat_openshift_cluster_observability_operator/perses-dashboard),
[OpenShift AI 3.4 observability prerequisites](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html-single/managing_openshift_ai/index).

## Recommended repair

Refresh the stale COO subscription and reinstall COO through OLM, preserving
the CRDs, custom resources, namespace and existing OperatorGroup. The cluster's
`redhat-operators` catalog currently offers **1.5.3** on `stable`. Use manual
InstallPlan approval during recovery to inspect the resolved changes. This is
an in-family COO patch update from the claimed 1.5.1 installation.

The prepared [recovery subscription](recovery-subscription.yaml) passed
[server-side dry-run](recovery-subscription-dry-run.txt). That checks API
admission, not actual bundle resolution, image pulls or restored webhook health.
The final plan must be checked before installation. The exact 1.5.3 resolved
bundle has not yet been installed or tested on this cluster.

OLM subscription refresh/reinstallation is a documented recovery pattern. The
linked Red Hat procedure discusses inaccessible bundles, whereas this cluster
has a stale installation record with missing operands; applying the same
refresh pattern here is a recommendation based on the observed state, not a
vendor-confirmed advisory for this exact incident.
[OpenShift 4.21 operator recovery guidance](https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/pdf/operators/OpenShift_Container_Platform-4.21-Operators-en-US.pdf).

Before executing, refresh the backups and confirm the missing-CSV state still
holds. Backups of the Subscription, OperatorGroup, InstallPlan, Perses CRDs and
existing Perses custom resources are stored beside this report. They contain no
Secret objects. Re-read the catalog candidate if executing at a later date.

From the repository root, the proposed mutation is:

```sh
oc delete subscriptions.operators.coreos.com cluster-observability-operator \
  -n openshift-cluster-observability-operator --cascade=orphan
oc apply -f docs/validation/semantic-navigation/openshift-ai/S0/perses-reconciliation-20261030/recovery-subscription.yaml
oc get subscriptions.operators.coreos.com cluster-observability-operator \
  -n openshift-cluster-observability-operator -o yaml
```

Only the stale subscription is deleted. There is no CSV to delete in the
observed state. Preserve the old completed InstallPlan for evidence. Inspect the
**new** plan referenced by the recreated subscription: it should install COO
1.5.3 and its expected resources. Do not approve unrelated upgrades or substitute
the old `install-5m892` name. After reviewing that plan:

```sh
oc patch installplans.operators.coreos.com NEW_COO_INSTALLPLAN \
  -n openshift-cluster-observability-operator --type=merge \
  -p '{"spec":{"approved":true}}'
```

Allow OLM to recreate the controllers, RBAC, certificates and conversion webhook
configuration. Do not manually point a CRD at a webhook before its service,
certificates and endpoints are healthy. Do not delete the Perses CRDs or existing
dashboards: that would remove stored resources rather than restore conversion.
Do not add old fields to the new schema or disable schema validation.

There is a separate pending OpenShift AI **3.5.2** InstallPlan. Leave it pending
during this repair. Restoring the dependency can be evaluated while retaining
the installed OpenShift AI 3.4.2 version.

## Verification after repair

1. COO's CSV reaches `Succeeded`; `observability-operator`, `perses-operator`,
   Prometheus operator and admission webhook deployments become available.
2. Perses dashboard CRD uses `Webhook` conversion with a populated CA bundle,
   reachable service and ready endpoints. OLM can choose generated service names;
   inspect the CRD's actual service reference.
3. Read the same dashboard through both API versions. The old API must expose
   top-level panels/layouts, the new API `spec.config`, with equivalent content:

```sh
oc get --raw /apis/perses.dev/v1alpha1/namespaces/redhat-ods-monitoring/persesdashboards/dashboard-0-cluster-admin
oc get --raw /apis/perses.dev/v1alpha2/namespaces/redhat-ods-monitoring/persesdashboards/dashboard-0-cluster-admin
```

4. OpenShift AI reconciliation no longer emits the Perses schema errors. Check
   `DashboardReady`, `ModelsAsServiceReady` and overall `Ready` on `default-dsc`.
   Inspect subsequent errors independently if another missing dependency surfaces.
5. Confirm the managed dashboard rollout finishes, existing dashboards remain,
   and the Perses/monitoring operands reconcile. Then capture fresh G0 evidence.

A subscription dry-run cannot establish these outcomes. Until they are observed,
the reconciliation blocker remains open. Other G0 prerequisites remain separate.
