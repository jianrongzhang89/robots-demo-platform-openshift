#!/usr/bin/env python3
"""Render the Stage 3C energy-predictor serving candidate (CPU, mTLS).

Follows the accepted SAM3 custom-serving pattern: a KServe ServingRuntime
with a digest-pinned container, a RawDeployment InferenceService with one
warm CPU replica, a cluster-local TLS Service, a client-policy ConfigMap,
and an ingress-isolating NetworkPolicy. No oc invocation or cluster writes.
"""
import argparse
import json
import re

MODEL = "energy-predictor-v1"
NAMESPACE = "semantic-model-serving"


def render(image, namespace=NAMESPACE):
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("runtime image must be pinned by digest")
    selector = {"serving.kserve.io/inferenceservice": MODEL, "component": "predictor"}

    def resource(api, kind, name, **fields):
        return {"apiVersion": api, "kind": kind,
                "metadata": {"name": name, "namespace": namespace}, **fields}

    container = {
        "name": "kserve-container", "image": image,
        "ports": [{"name": "data", "containerPort": 8090},
                  {"name": "health", "containerPort": 8080}],
        "env": [{"name": key, "value": value} for key, value in {
            "RUNTIME_IMAGE_DIGEST": image.split("@", 1)[1],
            "MODEL_MANIFEST": "/app/model-manifest.json",
            "RELEASE_DIR": "/app/release",
            "PHYSICS_MODEL": "/app/physics-model-v1.json",
            "TLS_CERT": "/tls/tls.crt", "TLS_KEY": "/tls/tls.key",
            "CLIENT_CA": "/tls/client-ca.crt", "CLIENT_POLICY": "/policy/clients.json",
            # The platform's KServe controller injects a kube-rbac-proxy on
            # pod port 8443 for new InferenceServices; the mutually
            # authenticated data port therefore listens on 8090 and the TLS
            # Service targets it directly.
            "DATA_PORT": "8090",
            "HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1",
        }.items()],
        "resources": {"requests": {"cpu": "500m", "memory": "1Gi"},
                      "limits": {"cpu": "2", "memory": "4Gi"}},
        "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                            "seccompProfile": {"type": "RuntimeDefault"}},
        "volumeMounts": [
            {"name": "tls", "mountPath": "/tls", "readOnly": True},
            {"name": "policy", "mountPath": "/policy", "readOnly": True},
            {"name": "tmp", "mountPath": "/tmp"},
        ],
        "startupProbe": {"httpGet": {"path": "/ready", "port": 8080},
                         "periodSeconds": 5, "failureThreshold": 60},
        "readinessProbe": {"httpGet": {"path": "/ready", "port": 8080},
                           "periodSeconds": 2, "failureThreshold": 1},
        "livenessProbe": {"httpGet": {"path": "/live", "port": 8080},
                          "periodSeconds": 2, "failureThreshold": 3},
    }
    runtime = resource("serving.kserve.io/v1alpha1", "ServingRuntime",
                       "energy-predictor-runtime-v1", spec={
                           "supportedModelFormats": [{"name": "energy-predictor",
                                                      "version": "1", "autoSelect": False}],
                           "protocolVersions": ["v1"], "multiModel": False,
                           "storageHelper": {"disabled": True},
                           "containers": [container],
                           "volumes": [
                               {"name": "tls", "secret": {"secretName": "energy-serving-tls"}},
                               {"name": "policy", "configMap": {"name": "energy-client-policy"}},
                               {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}}],
                       })
    runtime["metadata"]["annotations"] = {
        "openshift.io/display-name": "Warehouse energy predictor (custom JSON, mTLS, CPU)"}
    runtime["metadata"]["labels"] = {"opendatahub.io/dashboard": "true"}
    inference = resource("serving.kserve.io/v1beta1", "InferenceService", MODEL, spec={
        "predictor": {"serviceAccountName": "energy-serving",
                      "automountServiceAccountToken": False,
                      "minReplicas": 1, "maxReplicas": 1,
                      "model": {"modelFormat": {"name": "energy-predictor", "version": "1"},
                                "runtime": "energy-predictor-runtime-v1",
                                "protocolVersion": "v1",
                                "resources": container["resources"]}}})
    inference["metadata"]["annotations"] = {
        "serving.kserve.io/deploymentMode": "RawDeployment",
        "serving.kserve.io/visibility": "cluster-local",
        "security.opendatahub.io/enable-auth": "false",  # the data port enforces mTLS itself
    }
    inference["metadata"]["labels"] = {"opendatahub.io/dashboard": "true"}
    return {"apiVersion": "v1", "kind": "List", "items": [
        resource("v1", "ServiceAccount", "energy-serving", automountServiceAccountToken=False),
        resource("v1", "ConfigMap", "energy-client-policy", data={"clients.json": json.dumps({
            "spiffe://warehouse-energy/client/energy-qualifier-v1":
                ["warehouse-bounded-differential-drive-v1"]})}),
        runtime, inference,
        resource("v1", "Service", MODEL + "-tls", spec={
            "type": "ClusterIP", "selector": selector,
            "ports": [{"name": "https", "port": 8443, "targetPort": 8090}]}),
        resource("networking.k8s.io/v1", "NetworkPolicy", "energy-predictor-isolation", spec={
            "podSelector": {"matchLabels": selector},
            "policyTypes": ["Ingress", "Egress"], "egress": [],
            "ingress": [{"from": [
                {"namespaceSelector": {"matchLabels": {
                    "kubernetes.io/metadata.name": "semantic-navigation"}},
                 "podSelector": {"matchLabels": {"energy-serving-client": MODEL}}},
                {"namespaceSelector": {"matchLabels": {
                    "kubernetes.io/metadata.name": "warehouse-energy"}},
                 "podSelector": {"matchLabels": {"energy-serving-client": MODEL}}}],
                "ports": [{"protocol": "TCP", "port": 8090},
                          {"protocol": "TCP", "port": 8080}]}]}),
    ]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--namespace", default=NAMESPACE)
    args = parser.parse_args()
    print(json.dumps(render(args.image, args.namespace), indent=2))
