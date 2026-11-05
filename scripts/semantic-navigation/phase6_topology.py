#!/usr/bin/env python3
"""Private SAM3 topology lifecycle for Phase 6 trials.

The same management the frozen Phase 5 series runners perform, factored into
a two-command tool so pilot trials can run against the private topology
without duplicating it: `up` saves and deletes the parked demo SAM3 pod (its
L40S node and the node-locked ReadWriteOnce checkpoint PVC are the only
qualified placement), creates the private Zenoh router/ConfigMap/Service and
SAM3 pod and waits for readiness; `down` deletes the created objects and
restores the demo pod on its L40S placement. Every trial itself only checks
the topology is ready (run_phase5_native.py --sam3-observation); this tool
moves no robot and changes no canonical deployment.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

from run_phase5_sam3_series import (BRIDGE_CONFIG, DEMO_SAM3_POD, GPU_NODE,
                                    NAMESPACE, ROUTER, ROUTER_CONFIG, SAM3_POD,
                                    restore_spec)

STATE_FILE = "topology-state.json"


def oc_call(oc, *argv, check=True, input=None):
    return subprocess.run([oc, "-n", NAMESPACE, *argv], text=True,
                          capture_output=True, check=check, timeout=180, input=input)


def wait_ready(oc, name, deadline_s=600):
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        status = json.loads(oc_call(oc, "get", "pod", name, "-o", "json",
                                    check=False).stdout or "{}").get("status", {})
        if status.get("phase") == "Running" and all(
                c.get("ready") for c in status.get("containerStatuses", [])):
            return True
        time.sleep(5)
    return False


def sam3_pod_spec(sam3_image):
    return {"apiVersion": "v1", "kind": "Pod",
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
                {"name": "sam3-inference", "image": sam3_image,
                 "imagePullPolicy": "IfNotPresent",
                 "command": ["/bin/bash", "-c"],
                 "args": ["source /opt/ros/jazzy/setup.bash; "
                          "/opt/sam3-venv/bin/python /opt/semantic-perception/sam3_ros_node.py & "
                          "echo $! > /tmp/sam3-python.pid; "
                          "wait $(cat /tmp/sam3-python.pid)"],
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


def topology_objects(sam3_image):
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
    return (config_map, service, deployment, sam3_pod_spec(sam3_image))


def wait_router_available(oc, deadline_s=180):
    """Wait until the private router deployment reports available replicas.

    The SAM3 pod's zenoh bridge dials the router ONCE at startup (its config
    carries retry: None — the known 'a zenoh client session never re-dials a
    lost router' lesson). If the pod is created in the same instant as the
    router, the bridge's initial dial can precede the router's listening
    socket and the session stays dead with the control plane half-alive:
    routes still form from cached declarations, but NO data flows (the
    pair-1-on-lethal254-grace1 trial lost its whole run to this — SAM3 warm
    and 'awaiting live RGB-D frame' forever, zero observations at the
    costmaps, witness never qualifying a scan). Creating the pod only after
    the router is available closes the race.
    """
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        deployment = json.loads(oc_call(oc, "get", "deploy", ROUTER, "-o", "json",
                                        check=False).stdout or "{}")
        if deployment.get("status", {}).get("availableReplicas"):
            return True
        time.sleep(3)
    return False


def up(args):
    args.output_dir.mkdir(parents=True, exist_ok=False)
    demo_live = json.loads(oc_call(args.oc, "get", "pod", DEMO_SAM3_POD, "-o", "json").stdout)
    (args.output_dir / "demo-sam3-saved-pod.json").write_text(json.dumps(demo_live, indent=2))
    restore_pod = restore_spec(demo_live)
    (args.output_dir / "demo-sam3-restore-pod.json").write_text(json.dumps(restore_pod, indent=2))
    oc_call(args.oc, "delete", "pod", DEMO_SAM3_POD, "--wait=true", "--timeout=120s")
    created = []
    for obj in topology_objects(args.sam3_image):
        oc_call(args.oc, "create", "-f", "-", input=json.dumps(obj))
        created.append((obj["kind"], obj["metadata"]["name"]))
    if not wait_router_available(args.oc):
        raise RuntimeError("private router did not become available before the SAM3 pod")
    if not wait_ready(args.oc, SAM3_POD):
        raise RuntimeError("private SAM3 pod did not become ready")
    state = {"created": created, "restore_pod": restore_pod,
             "ready_wall_ns": time.time_ns(), "sam3_node": GPU_NODE}
    (args.output_dir / STATE_FILE).write_text(json.dumps(state, indent=2))
    print(json.dumps({"event": "topology_ready", **state}))


def down(args):
    state = json.loads((args.output_dir / STATE_FILE).read_text())
    cleanup = []
    for kind, name in reversed(state["created"]):
        result = oc_call(args.oc, "delete", kind, name, "--wait=true",
                         "--timeout=120s", check=False)
        cleanup.append({"kind": kind, "name": name,
                        "returncode": result.returncode, "stderr": result.stderr})
    restore_result = oc_call(args.oc, "create", "-f", "-",
                             input=json.dumps(state["restore_pod"]), check=False)
    cleanup.append({"kind": "Pod", "name": DEMO_SAM3_POD,
                    "returncode": restore_result.returncode,
                    "stderr": restore_result.stderr})
    if restore_result.returncode == 0:
        restored = wait_ready(args.oc, DEMO_SAM3_POD)
        cleanup.append({"kind": "Pod", "name": DEMO_SAM3_POD, "restored": restored})
    (args.output_dir / "cleanup.json").write_text(json.dumps(cleanup, indent=2))
    print(json.dumps({"event": "topology_down", "cleanup": cleanup}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "down"))
    parser.add_argument("--oc", default="oc")
    parser.add_argument("--sam3-image",
                        help="digest-pinned payload-bound sam3-runtime image (up)")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="new directory for up; the up directory for down")
    args = parser.parse_args()
    if args.command == "up":
        if not args.sam3_image:
            parser.error("up requires --sam3-image")
        up(args)
    else:
        down(args)


if __name__ == "__main__":
    main()
