#!/usr/bin/env python3
"""Read-only serving inventory. Never treats component readiness as G0 passage."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def oc(*args):
    return json.loads(subprocess.check_output(["oc", "--request-timeout=30s", *args, "-o", "json"]))


def inventory():
    dsc = oc("get", "datasciencecluster", "default-dsc")
    csvs = oc("get", "csv", "-n", "redhat-ods-operator")
    version = oc("get", "clusterversion", "version")
    controller = oc("get", "deployment", "kserve-controller-manager", "-n", "redhat-ods-applications")
    model = oc("get", "pod", "semantic-phase6-sam3", "-n", "semantic-navigation")
    renderer = oc("get", "pod", "semantic-phase6-simulator", "-n", "semantic-navigation")
    nodes = oc("get", "nodes", "-l", "nvidia.com/gpu.present=true")
    pods = oc("get", "pods", "-A")
    pvc = oc("get", "pvc", "sam3-checkpoint", "-n", "semantic-navigation")
    schemas = oc("get", "crd", "servingruntimes.serving.kserve.io", "inferenceservices.serving.kserve.io")
    allocated = {}
    for pod in pods["items"]:
        if pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
            continue
        containers = pod["spec"].get("containers", [])
        count = sum(int(c.get("resources", {}).get("requests", {}).get("nvidia.com/gpu", 0)) for c in containers)
        node = pod["spec"].get("nodeName", "unscheduled")
        allocated[node] = allocated.get(node, 0) + count
    def pod_summary(pod):
        return {"name": pod["metadata"]["name"], "node": pod["spec"].get("nodeName"),
            "images": [{"name": c["name"], "imageID": c.get("imageID"), "ready": c["ready"]}
                       for c in pod["status"].get("containerStatuses", [])],
            "resources": {c["name"]: c.get("resources", {}) for c in pod["spec"]["containers"]}}
    return {"recorded_at": datetime.now(timezone.utc).isoformat(),
        "ocp_version": version["status"]["desired"]["version"],
        "ai_operators": [{"name": c["metadata"]["name"], "version": c["spec"]["version"],
                          "phase": c["status"].get("phase")} for c in csvs["items"]
                         if c["metadata"]["name"].startswith("rhods-operator.")],
        "conditions": dsc["status"]["conditions"],
        "kserve_images": [c["image"] for c in controller["spec"]["template"]["spec"]["containers"]],
        "crds": [{"name": c["metadata"]["name"], "versions": [v["name"] for v in c["spec"]["versions"]]}
                 for c in schemas["items"]],
        "baseline_model": pod_summary(model), "baseline_renderer": pod_summary(renderer),
        "gpus": [{"node": n["metadata"]["name"],
                  "product": n["metadata"]["labels"].get("nvidia.com/gpu.product"),
                  "allocatable": n["status"]["allocatable"].get("nvidia.com/gpu", "0"),
                  "requested_by_active_regular_containers": allocated.get(n["metadata"]["name"], 0)}
                 for n in nodes["items"]],
        "storage": {"namespace": "semantic-navigation", "claim": "sam3-checkpoint",
                    "phase": pvc["status"]["phase"], "accessModes": pvc["spec"]["accessModes"],
                    "storageClass": pvc["spec"].get("storageClassName")},
        "gate": "G0", "status": "NOT_EVALUATED",
        "gate_record": "docs/validation/semantic-navigation/openshift-ai/S0/gate-result.json",
        "gate_requirements": [
            "Require relevant OpenShift AI component reconciliation to succeed.",
            "Reproduce and archive a baseline off/on pair with frozen Phase 6 configuration.",
            "Provision serving-project checkpoint PVC, verify checksum, and reserve L40S capacity separately from rendering.",
            "Issue short-lived internal TLS/client credentials and validate namespace, quotas, permissions and routing.",
            "Build a runtime digest and server-dry-run final resources in the destination project.",
        ],
        "capacity_note": "Snapshot only, not a GPU reservation; excludes init-container and scheduler constraints."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
