#!/usr/bin/env python3
"""Frozen observation-only SAM3 series on the private guarded moving fixture.

Manages the private SAM3 topology for the whole series: the parked demo
SAM3 pod is saved and deleted (its L40S node and the node-locked
ReadWriteOnce checkpoint PVC are the only qualified placement), a private
Zenoh router and a private SAM3 pod are created, and every trial runs the
identical frozen guarded GPU profile with observation-only SAM3. Semantic
costs are excluded from navigation. The demo pod is restored in a finally
block with retained evidence. No retries; the series stops on the first
failure.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

SAM3_POD = "semantic-phase5-sam3"
ROUTER = "semantic-phase5-sam3-router"
ROUTER_CONFIG = "semantic-phase5-sam3-config"
DEMO_SAM3_POD = "semantic-phase6-sam3"
GPU_NODE = "ip-10-0-18-251.ec2.internal"
NAMESPACE = "semantic-navigation"

BRIDGE_CONFIG = """{
  "plugins": { "ros2dds": { "allow": {
      "publishers": [
        "^/robot_1/semantic/mask$",
        "^/robot_1/semantic/points$",
        "^/robot_1/semantic/timing$",
        "^/robot_1/semantic/label_info$",
        "^/robot_1/semantic/status$",
        "^/robot_1/semantic/ready$"
      ],
      "subscribers": [
        "^/clock$",
        "^/robot_1/camera/color/image_compressed$",
        "^/robot_1/camera/depth/image_compressed$",
        "^/robot_1/camera/color/camera_info$",
        "^/robot_1/camera/capture_trace$",
        "^/robot_1/camera/compression_trace$"
      ]
    } } },
  "mode": "client",
  "connect": { "endpoints": ["tcp/semantic-phase5-sam3-router:17448"], "exit_on_failure": false, "timeout_ms": -1 },
  "scouting": { "multicast": { "enabled": false } }
}
"""


def trial_passed(evidence, returncode):
    required = {"sam3_observation_ready", "sam3_registration_under_motion",
                "sam3_observation_timing", "sam3_semantic_isolation",
                "guarded_real_hotel_one_meter_goal",
                "cancellation_terminal_and_acknowledged",
                "closed_graph_and_descendants_terminal",
                "baseline_native_stop_metrics", "baseline_contact_window",
                "independent_native_motion_observed", "settled_support_geometry"}
    if evidence.get("sam3_observation") is not True:
        return False
    if evidence.get("console_only_server") is not True or evidence.get("world_recording") is not False:
        return False
    if evidence.get("diagnostic_only", False):
        return False
    checks = {c["case"]: c for c in evidence.get("checks", [])}
    return (returncode == 0 and evidence.get("passed") is True
            and all(checks.get(name, {}).get("passed") is True for name in required)
            and all(c.get("passed") is True for c in evidence.get("checks", [])))


def restore_spec(live):
    """Strip API-managed fields so the saved demo pod can be recreated."""
    spec = copy.deepcopy(live)
    spec.pop("status", None)
    metadata = spec["metadata"]
    for field in ("uid", "resourceVersion", "creationTimestamp", "managedFields"):
        metadata.pop(field, None)
    spec["spec"].pop("nodeName", None)
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oc", default="oc")
    parser.add_argument("--image", required=True,
                        help="digest-pinned semantic-safety console image WITH the capture-trace override")
    parser.add_argument("--sam3-image", required=True,
                        help="digest-pinned payload-bound sam3-runtime image")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--node-name", default="ip-10-0-44-146.ec2.internal",
                        help="pinned guarded-fixture GPU worker")
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("at least one trial is required")
    root = Path(__file__).resolve().parents[2]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    files = sorted((root / "apps/semantic-safety").glob("*.py")) + [
        root / "apps/semantic-safety/phase5-baseline.xml",
        root / "helm/semantic-navigation/phase5-nav2-candidate.yaml",
        root / "scripts/semantic-navigation/run_phase5_native.py",
        root / "scripts/semantic-navigation/run_phase5_sam3_series.py"]
    hashes = lambda: {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    frozen = hashes()
    plan = {"image": args.image, "sam3_image": args.sam3_image,
            "planned_trials": args.trials, "node_name": args.node_name,
            "sam3_node": GPU_NODE, "router": ROUTER,
            "scenario": "guarded baseline 1 m goal with observation-only SAM3; semantic costs excluded",
            "retry_policy": "none; stop series on first failure",
            "qualified_profile": {"console_only_server": True, "contact_audit": True,
                                  "rear_casters": True, "physics_step": 0.002,
                                  "lidar_range": 12.0, "odom_frequency": 200.0,
                                  "gpu_rendering": True},
            "source_hashes": frozen}
    (args.output_dir / "plan.json").write_text(json.dumps(plan, indent=2))

    def oc(*argv, check=True, input=None):
        return subprocess.run([args.oc, "-n", NAMESPACE, *argv], text=True,
                              capture_output=True, check=check, timeout=120, input=input)

    results = []
    demo_live = json.loads(oc("get", "pod", DEMO_SAM3_POD, "-o", "json").stdout)
    (args.output_dir / "demo-sam3-saved-pod.json").write_text(json.dumps(demo_live, indent=2))
    restore = restore_spec(demo_live)
    (args.output_dir / "demo-sam3-restore-pod.json").write_text(json.dumps(restore, indent=2))
    created = []
    try:
        oc("delete", "pod", DEMO_SAM3_POD, "--wait=true", "--timeout=120s")
        config_map = {"apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": ROUTER_CONFIG, "namespace": NAMESPACE,
                         "labels": {"app": ROUTER}},
            "data": {
                "cyclonedds.xml": '<CycloneDDS><Domain id="any"><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex></Discovery></Domain></CycloneDDS>',
                "router.json5": '{\n  "mode": "router",\n  "listen": { "endpoints": ["tcp/0.0.0.0:17448"] },\n  "scouting": { "multicast": { "enabled": false } }\n}\n',
                "sam3-bridge.json5": BRIDGE_CONFIG}}
        service = {"apiVersion": "v1", "kind": "Service",
            "metadata": {"name": ROUTER, "namespace": NAMESPACE,
                         "labels": {"app": ROUTER}},
            "spec": {"selector": {"app": ROUTER},
                     "ports": [{"name": "zenoh", "port": 17448, "targetPort": 17448}]}}
        deployment = {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": ROUTER, "namespace": NAMESPACE,
                         "labels": {"app": ROUTER}},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": ROUTER}},
                "template": {"metadata": {"labels": {"app": ROUTER}},
                    "spec": {"containers": [{"name": "router",
                        "image": "docker.io/eclipse/zenoh@sha256:137310456cc7a75d955063513207c737f25071fbb74fd7641835c50ab8e3369f",
                        "imagePullPolicy": "IfNotPresent",
                        "args": ["-c", "/phase5-config/router.json5"],
                        "ports": [{"name": "zenoh", "containerPort": 17448}],
                        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                                      "limits": {"cpu": "500m", "memory": "512Mi"}},
                        "volumeMounts": [{"name": "config", "mountPath": "/phase5-config", "readOnly": True}]}],
                        "volumes": [{"name": "config", "configMap": {"name": ROUTER_CONFIG}}]}}}}
        sam3_pod = {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": SAM3_POD, "namespace": NAMESPACE,
                         "labels": {"app": SAM3_POD}},
            "spec": {"restartPolicy": "Always",
                "securityContext": {"fsGroup": 1001340000, "fsGroupChangePolicy": "OnRootMismatch"},
                "nodeSelector": {"kubernetes.io/hostname": GPU_NODE},
                "tolerations": [{"key": "g6e-gpu", "operator": "Equal", "value": "true", "effect": "NoSchedule"}],
                "containers": [
                    {"name": "sam3-zenoh-bridge",
                     "image": "eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18",
                     "args": ["-c", "/phase5-bridges/sam3-bridge.json5"],
                     "env": [{"name": k, "value": v} for k, v in {
                         "ROS_DOMAIN_ID": "86", "ROS_DISTRO": "jazzy",
                         "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                         "CYCLONEDDS_URI": "file:///phase5-bridges/cyclonedds.xml"}.items()],
                     "volumeMounts": [{"name": "bridge-config", "mountPath": "/phase5-bridges", "readOnly": True}],
                     "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                                   "limits": {"cpu": "500m", "memory": "512Mi"}}},
                    {"name": "sam3-inference", "image": args.sam3_image,
                     "imagePullPolicy": "IfNotPresent",
                     "env": [{"name": k, "value": v} for k, v in {
                         "ROS_DOMAIN_ID": "86", "ROS_DISTRO": "jazzy",
                         "HOME": "/tmp/phase5-sam3-home", "ROS_LOG_DIR": "/tmp/phase5-sam3-logs",
                         "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                         "CYCLONEDDS_URI": "file:///phase5-bridges/cyclonedds.xml",
                         "SAM3_PROMPT": "red mat",
                         "SEMANTIC_REQUIRE_CAPTURE_TRACE": "1",
                         "SEMANTIC_MAX_WORK_WAIT_MS": "40",
                         "SEMANTIC_CLOCK_UNCERTAINTY_MS": "2"}.items()],
                     "volumeMounts": [
                         {"name": "bridge-config", "mountPath": "/phase5-bridges", "readOnly": True},
                         {"name": "model", "mountPath": "/models", "readOnly": True}],
                     "resources": {"requests": {"cpu": "3", "memory": "12Gi", "nvidia.com/gpu": 1},
                                   "limits": {"cpu": "6", "memory": "24Gi", "nvidia.com/gpu": 1}}}],
                "volumes": [
                    {"name": "bridge-config", "configMap": {"name": ROUTER_CONFIG}},
                    {"name": "model", "persistentVolumeClaim": {"claimName": "sam3-checkpoint"}}]}}
        for obj in (config_map, service, deployment, sam3_pod):
            oc("create", "-f", "-", input=json.dumps(obj))
            created.append((obj["kind"], obj["metadata"]["name"]))
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            status = json.loads(oc("get", "pod", SAM3_POD, "-o", "json").stdout).get("status", {})
            if status.get("phase") == "Running" and all(
                    c.get("ready") for c in status.get("containerStatuses", [])):
                break
            time.sleep(5)
        else:
            raise RuntimeError("private SAM3 pod did not become ready")
        (args.output_dir / "sam3-topology.json").write_text(json.dumps(
            {"created": created, "ready_wall_ns": time.time_ns(),
             "sam3_pod": json.loads(oc("get", "pod", SAM3_POD, "-o", "json").stdout)}, indent=2))
        for trial in range(1, args.trials + 1):
            if hashes() != frozen:
                raise RuntimeError("runtime inputs changed during fixed series")
            directory = args.output_dir / f"trial-{trial:02d}"
            print(json.dumps({"event": "trial_started", "trial": trial}), flush=True)
            run = subprocess.run([sys.executable,
                str(root / "scripts/semantic-navigation/run_phase5_native.py"),
                "--oc", args.oc, "--suite", "hotel-guarded", "--contact-audit",
                "--sam3-observation", "--console-only-server", "--rear-casters",
                "--physics-step", "0.002", "--lidar-range", "12", "--odom-frequency", "200",
                "--gpu-rendering", "--node-name", args.node_name,
                "--image", args.image, "--output-dir", str(directory)])
            path = directory / "runtime/summary.json"
            evidence = json.loads(path.read_text()) if path.is_file() else {}
            passed = trial_passed(evidence, run.returncode)
            if hashes() != frozen:
                passed = False
            results.append({"trial": trial, "passed": passed,
                            "returncode": run.returncode, "evidence": str(path)})
            summary = {"passed": len(results) == args.trials and all(r["passed"] for r in results),
                       "planned": args.trials, "attempted": len(results),
                       "succeeded": sum(r["passed"] for r in results),
                       "results": results,
                       "scope": "observation-only SAM3 registration/load on the private guarded "
                                "fixture; semantic costs excluded; not the armed semantic fault matrix"}
            (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps({"event": "trial_finished", **results[-1]}), flush=True)
            if not passed:
                raise RuntimeError("SAM3 observation series failed; no automatic retry")
    finally:
        # Always retain the private SAM3 pod state and container logs before
        # any teardown: a crash-looping sidecar otherwise leaves no evidence.
        pod_json = oc("get", "pod", SAM3_POD, "-o", "json", check=False)
        if pod_json.returncode == 0 and pod_json.stdout.strip():
            diagnostics = {
                "pod": json.loads(pod_json.stdout),
                "bridge_log": oc("logs", SAM3_POD, "-c", "sam3-zenoh-bridge", check=False).stdout,
                "inference_log_tail": oc("logs", SAM3_POD, "-c", "sam3-inference", check=False).stdout[-4000:],
                "router_pods": json.loads(oc("get", "pods", "-l", f"app={ROUTER}", "-o", "json", check=False).stdout or "{}")}
            (args.output_dir / "sam3-topology-diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
        cleanup = []
        for kind, name in reversed(created):
            result = oc("delete", kind, name, "--wait=true", "--timeout=120s", check=False)
            cleanup.append({"kind": kind, "name": name,
                            "returncode": result.returncode, "stderr": result.stderr})
        # Restore the parked demo SAM3 pod on the freed L40S placement.
        restore_result = oc("create", "-f", "-", input=json.dumps(restore), check=False)
        cleanup.append({"kind": "Pod", "name": DEMO_SAM3_POD,
                        "returncode": restore_result.returncode,
                        "stderr": restore_result.stderr})
        if restore_result.returncode == 0:
            deadline = time.monotonic() + 600
            restored = False
            while time.monotonic() < deadline:
                status = json.loads(oc("get", "pod", DEMO_SAM3_POD, "-o", "json",
                                       check=False).stdout).get("status", {})
                if status.get("phase") == "Running" and all(
                        c.get("ready") for c in status.get("containerStatuses", [])):
                    restored = True
                    break
                time.sleep(5)
            cleanup.append({"kind": "Pod", "name": DEMO_SAM3_POD, "restored": restored})
        (args.output_dir / "cleanup.json").write_text(json.dumps(cleanup, indent=2))


if __name__ == "__main__":
    main()
