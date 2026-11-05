#!/usr/bin/env python3
"""Render an isolated S1 candidate. No kubectl/oc invocation or cluster writes."""
import argparse
import json
import re


def render(image, namespace="semantic-model-serving", node_name=None):
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("runtime image must be pinned by digest")
    name = "sam3-mat-v1"
    selector = {"serving.kserve.io/inferenceservice": name, "component": "predictor"}
    def resource(api, kind, name, **fields):
        return {"apiVersion": api, "kind": kind,
                "metadata": {"name": name, "namespace": namespace}, **fields}
    volume_mounts = [
        {"name": "model", "mountPath": "/models", "readOnly": True},
        {"name": "tls", "mountPath": "/tls", "readOnly": True},
        {"name": "policy", "mountPath": "/policy", "readOnly": True},
        {"name": "tmp", "mountPath": "/tmp"},
    ]
    container = {
        "name": "kserve-container", "image": image,
        "ports": [{"name": "https", "containerPort": 8443},
                  {"name": "health", "containerPort": 8080}],
        "env": [{"name": key, "value": value} for key, value in {
            "RUNTIME_IMAGE_DIGEST": image.split("@", 1)[1],
            "MODEL_DIR": "/models", "TLS_CERT": "/tls/tls.crt", "TLS_KEY": "/tls/tls.key",
            "CLIENT_CA": "/tls/client-ca.crt", "CLIENT_POLICY": "/policy/clients.json",
            "HOME": "/tmp", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        }.items()],
        "resources": {"requests": {"cpu": "3", "memory": "12Gi", "nvidia.com/gpu": "1"},
                      "limits": {"cpu": "6", "memory": "24Gi", "nvidia.com/gpu": "1"}},
        "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True,
            "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"}},
        "volumeMounts": volume_mounts,
        "startupProbe": {"httpGet": {"path": "/ready", "port": 8080},
                         "periodSeconds": 5, "failureThreshold": 120},
        "readinessProbe": {"httpGet": {"path": "/ready", "port": 8080},
                           "periodSeconds": 2, "failureThreshold": 1},
        "livenessProbe": {"httpGet": {"path": "/live", "port": 8080},
                          "periodSeconds": 2, "failureThreshold": 3},
    }
    runtime = resource("serving.kserve.io/v1alpha1", "ServingRuntime", "sam3-runtime-v1", spec={
        "supportedModelFormats": [{"name": "sam3", "version": "1", "autoSelect": False}],
        "protocolVersions": ["v1"], "multiModel": False,
        "storageHelper": {"disabled": True}, "containers": [container],
        "volumes": [{"name": "model", "persistentVolumeClaim": {"claimName": "sam3-checkpoint"}},
                    {"name": "tls", "secret": {"secretName": "sam3-serving-tls"}},
                    {"name": "policy", "configMap": {"name": "sam3-client-policy"}},
                    {"name": "tmp", "emptyDir": {"sizeLimit": "2Gi"}}],
    })
    runtime["metadata"]["annotations"] = {"openshift.io/display-name": "SAM3 semantic inference (custom JSON, mTLS)"}
    runtime["metadata"]["labels"] = {"opendatahub.io/dashboard": "true"}
    inference = resource("serving.kserve.io/v1beta1", "InferenceService", name, spec={
        "predictor": {"serviceAccountName": "sam3-serving", "automountServiceAccountToken": False,
            "minReplicas": 1, "maxReplicas": 1,
            "nodeSelector": {"nvidia.com/gpu.product": "NVIDIA-L40S"},
            "tolerations": [{"key": "g6e-gpu", "operator": "Equal",
                             "value": "true", "effect": "NoSchedule"}],
            "model": {"modelFormat": {"name": "sam3", "version": "1"},
                      "runtime": "sam3-runtime-v1", "protocolVersion": "v1",
                      "resources": container["resources"]}}})
    inference["metadata"]["annotations"] = {
        "serving.kserve.io/deploymentMode": "RawDeployment",
        "serving.kserve.io/visibility": "cluster-local",
        "security.opendatahub.io/enable-auth": "false",  # Data port enforces mTLS itself.
    }
    inference["metadata"]["labels"] = {"opendatahub.io/dashboard": "true"}
    if node_name:
        inference["spec"]["predictor"]["nodeSelector"]["kubernetes.io/hostname"] = node_name
    project = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace,
        "labels": {"opendatahub.io/dashboard": "true", "modelmesh-enabled": "false"},
        "annotations": {"openshift.io/display-name": "Semantic model serving"}}}
    return {"apiVersion": "v1", "kind": "List", "items": [project,
        resource("v1", "ServiceAccount", "sam3-serving", automountServiceAccountToken=False),
        resource("v1", "ConfigMap", "sam3-client-policy", data={"clients.json": json.dumps({
            "spiffe://semantic-navigation/sa/sam3-replay": [["robot_1", "camera/color"]]})}),
        runtime, inference,
        resource("v1", "Service", name + "-tls", spec={"type": "ClusterIP", "selector": selector,
            "ports": [{"name": "https", "port": 8443, "targetPort": 8443}]}),
        resource("networking.k8s.io/v1", "NetworkPolicy", "sam3-isolation", spec={
            "podSelector": {"matchLabels": selector}, "policyTypes": ["Ingress", "Egress"],
            "egress": [], "ingress": [{"from": [{
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "semantic-navigation"}},
                "podSelector": {"matchLabels": {"semantic-serving-client": name}}}],
                "ports": [{"protocol": "TCP", "port": 8443}]}]}),
    ]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--namespace", default="semantic-model-serving")
    parser.add_argument("--node-name", help="pin to the separately reserved serving GPU node")
    args = parser.parse_args()
    print(json.dumps(render(args.image, args.namespace, args.node_name), indent=2))
