#!/usr/bin/env python3
"""Collect read-only G5 prerequisites; this does not qualify the G5 gate.

No Secret reads, credential output, mutations, or inference requests. Output is
exclusive-create so a failed attempt cannot overwrite earlier evidence.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
import subprocess

ROOT = Path(__file__).resolve().parents[2]
GATES = ROOT / "docs/validation/semantic-navigation/openshift-ai"
NS = "semantic-model-serving"


def ready(resource):
    return any(c.get("type") == "Ready" and c.get("status") == "True"
               for c in resource.get("status", {}).get("conditions", []))


def pod_summary(pod):
    return {"name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"],
            "node": pod["spec"].get("nodeName"), "ready": ready(pod),
            "containers": [{"name": c["name"], "imageID": c.get("imageID"),
                            "ready": c.get("ready"), "restarts": c.get("restartCount")}
                           for c in pod.get("status", {}).get("containerStatuses", [])]}


def collect(oc="oc"):
    commands = []

    def call(*args):
        command = [oc, "--request-timeout=20s", *args]
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True, timeout=35)
        if result.returncode:
            raise RuntimeError(f"command failed ({result.returncode}): {result.stderr.strip()}")
        return json.loads(result.stdout)

    result = {"recorded_at": datetime.now(timezone.utc).isoformat(),
              "gate": "G5", "gate_status": "HOLD", "accepted": False,
              "commands": commands, "checks": {}, "errors": [],
              "scope": "read-only prerequisites; no lifecycle qualification"}
    checks = result["checks"]
    result["upstream_gates"] = {}
    for stage in range(5):
        gate = json.loads((GATES / f"S{stage}/gate-result.json").read_text())
        result["upstream_gates"][f"G{stage}"] = {
            "status": gate["status"], "accepted": gate.get("accepted", False)}
    checks["upstream_accepted"] = all(g["status"] == "PASS" and g["accepted"]
                                        for g in result["upstream_gates"].values())
    expected = json.loads((GATES / "S2/gate-result.json").read_text())["deployment_identity"]
    result["expected_identity"] = expected
    try:
        service = call("get", "inferenceservice", "sam3-mat-v1", "-n", NS, "-o", "json")
        checks["inferenceservice_ready"] = ready(service)
        pods = call("get", "pods", "-n", NS, "-l",
                    "serving.kserve.io/inferenceservice=sam3-mat-v1", "-o", "json")["items"]
        result["serving_pods"] = [pod_summary(p) for p in pods]
        checks["one_ready_serving_pod"] = len(pods) == 1 and ready(pods[0])
        checks["runtime_digest_matches"] = bool(pods) and all(
            any(c["name"] == "kserve-container" and
                c.get("imageID", "").endswith("@" + expected["container_digest"])
                for c in p.get("status", {}).get("containerStatuses", [])) for p in pods)
        if len(pods) == 1:
            # Decode only the public certificate; never read the private key.
            code = ('import ssl,json,urllib.request; print(json.dumps({'
                    '"certificate":ssl._ssl._test_decode_cert("/tls/tls.crt"),'
                    '"ready":json.load(urllib.request.urlopen("http://localhost:8080/ready",timeout=5))}))')
            result["server_probe"] = call("exec", "-n", NS, pods[0]["metadata"]["name"],
                "-c", "kserve-container", "--", "python3", "-c", code)
            expiry = ssl.cert_time_to_seconds(result["server_probe"]["certificate"]["notAfter"])
            result["certificate_seconds_remaining"] = expiry - datetime.now(timezone.utc).timestamp()
            checks["certificate_unexpired"] = result["certificate_seconds_remaining"] > 0
            checks["local_health_ready"] = result["server_probe"]["ready"].get("ok") is True
        navigation = call("get", "pods", "-n", "semantic-navigation", "-o", "json")["items"]
        result["navigation_pods"] = [pod_summary(p) for p in navigation]
        by_name = {p["metadata"]["name"]: p for p in navigation}
        checks["rendering_reservation_ready"] = ready(by_name.get("sam3-g0-rendering-reservation", {}))
        checks["local_sam3_ready"] = ready(by_name.get("semantic-phase6-sam3", {}))
        checks["no_g4_pods"] = not any(n.startswith("semantic-g4-") for n in by_name)
        hotel = call("get", "deployment", "semantic-hotel-sim", "-n", "semantic-navigation", "-o", "json")
        checks["hotel_sim_scaled_to_zero"] = hotel["spec"].get("replicas") == 0 and hotel.get("status", {}).get("replicas", 0) == 0
        registries = call("get", "modelregistries.modelregistry.opendatahub.io", "-A", "-o", "json")["items"]
        result["registries"] = [{"name": r["metadata"]["name"],
                                 "namespace": r["metadata"].get("namespace"),
                                 "ready": any(c.get("type") == "Available" and c.get("status") == "True"
                                              for c in r.get("status", {}).get("conditions", []))}
                                for r in registries]
        checks["registry_available"] = any(r["ready"] for r in result["registries"])
        version = call("get", "clusterversion", "version", "-o", "json")
        operators = call("get", "csv", "-n", "redhat-ods-operator", "-o", "json")
        result["cluster_versions"] = {"ocp": version["status"]["desired"]["version"],
            "ai": [{"name": c["metadata"]["name"], "version": c["spec"]["version"],
                    "phase": c["status"].get("phase")}
                   for c in operators["items"] if c["metadata"]["name"].startswith("rhods-operator.")]}
        checks["ai_operator_succeeded"] = bool(result["cluster_versions"]["ai"]) and all(
            c["phase"] == "Succeeded" for c in result["cluster_versions"]["ai"])

    except (subprocess.SubprocessError, RuntimeError, ValueError, KeyError, OSError) as error:
        result["errors"].append(str(error))
    result["preflight_status"] = "PASS" if checks and all(checks.values()) and not result["errors"] else "HOLD"
    result["limitations"] = ["Health and pod image do not prove authenticated loaded identity or replay parity.",
        "Certificate validity is a snapshot, not proof it covers a future maintenance window.",
        "No update, rollback, rotation, pod-loss, egress or dependency-outage test executed."]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oc", default="oc")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        result = collect(args.oc)
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"preflight_status": result["preflight_status"], "gate_status": "HOLD",
                      "output": str(args.output)}))
    return 0 if result["preflight_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
