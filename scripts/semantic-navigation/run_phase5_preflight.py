#!/usr/bin/env python3
"""Run non-actuating Phase 5 tests using the pinned Phase 4 ROS image.

Creates only its named ConfigMap/Pod; refuses to replace existing resources.
No Gazebo, GPU, Zenoh bridge, command receiver, RPP or RMF is launched. Retains
logs/manifests/hashes in a NEW output directory and cleans up created resources.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import yaml

NAME = "semantic-phase5-preflight"
NAMESPACE = "semantic-navigation"
IMAGE = "image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-costmap@sha256:447c6ee36d2eff0707a69133881c4131e0033dab5c38099750844173d416c92f"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oc", default="oc")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output_dir.mkdir(parents=True, exist_ok=False)

    def oc(*arguments, input=None, check=True):
        return subprocess.run([args.oc, "-n", NAMESPACE, *arguments], input=input,
                              text=True, capture_output=True, check=check, timeout=45)

    for kind in ("pod", "configmap"):
        if oc("get", kind, NAME, "--ignore-not-found", "-o", "name").stdout.strip():
            raise RuntimeError(f"{kind}/{NAME} already exists; refusing replacement")
    files = list((root / "apps/semantic-safety").glob("*.py")) + [root / "helm/semantic-navigation/phase5-nav2-candidate.yaml"]
    data = {f.name: f.read_text() for f in sorted(files)}
    data["cyclonedds-phase5.xml"] = ('<CycloneDDS><Domain id="any"><General><Interfaces>'
        '<NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast>'
        '</General><Discovery><ParticipantIndex>auto</ParticipantIndex></Discovery></Domain></CycloneDDS>')
    config = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": NAME, "namespace": NAMESPACE}, "data": data}
    pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": NAME, "namespace": NAMESPACE}, "spec": {
        "restartPolicy": "Never", "activeDeadlineSeconds": 300, "automountServiceAccountToken": False,
        "containers": [{"name": "preflight", "image": IMAGE, "command": ["/bin/bash", "-ec"],
            "args": ["source /opt/ros/jazzy/setup.bash; cd /phase5; "
                     "python3 -m unittest discover -s /phase5 -p 'test_*.py' -v; "
                     "python3 /phase5/audit_geometry.py; "
                     "dpkg-query -W ros-jazzy-nav2-collision-monitor ros-jazzy-nav2-controller ros-jazzy-nav2-velocity-smoother; "
                     "python3 /phase5/verify_nav_task_client.py; "
                     "python3 /phase5/verify_collision_monitor.py"],
            "env": [{"name": "ROS_DOMAIN_ID", "value": "85"}, {"name": "RMW_IMPLEMENTATION", "value": "rmw_cyclonedds_cpp"},
                    {"name": "CYCLONEDDS_URI", "value": "file:///phase5/cyclonedds-phase5.xml"},
                    {"name": "ROS_LOG_DIR", "value": "/tmp/phase5-ros-logs"},
                    {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"}],
            "volumeMounts": [{"name": "source", "mountPath": "/phase5", "readOnly": True}],
            "resources": {"requests": {"cpu": "250m", "memory": "256Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}},
            "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}}}],
        "volumes": [{"name": "source", "configMap": {"name": NAME}}]}}
    manifest = yaml.safe_dump_all([config, pod], sort_keys=False)
    (args.output_dir / "manifest.yaml").write_text(manifest)
    (args.output_dir / "source-hashes.json").write_text(json.dumps({k: hashlib.sha256(v.encode()).hexdigest() for k, v in data.items()}, indent=2))
    created = []
    try:
        for obj in (config, pod):
            oc("create", "-f", "-", input=yaml.safe_dump(obj))
            created.append(obj["kind"].lower())
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            state = json.loads(oc("get", "pod", NAME, "-o", "json").stdout)
            if state["status"]["phase"] in ("Succeeded", "Failed"):
                break
            time.sleep(2)
        else:
            raise TimeoutError("preflight pod did not finish")
        (args.output_dir / "pod.json").write_text(json.dumps(state, indent=2))
        logs = oc("logs", NAME).stdout
        (args.output_dir / "test.log").write_text(logs)
        for line in logs.splitlines():
            if line.startswith("{"):
                item = json.loads(line)
                if item.get("event") == "phase5_native_collision_fixture":
                    (args.output_dir / "collision-monitor.json").write_text(json.dumps(item, indent=2))
                elif "world_sha256" in item:
                    (args.output_dir / "geometry.json").write_text(json.dumps(item, indent=2))
                elif item.get("event") == "phase5_owned_action_fixture":
                    (args.output_dir / "owned-action.json").write_text(json.dumps(item, indent=2))
        print(json.dumps({"phase": state["status"]["phase"], "output_dir": str(args.output_dir), "image": IMAGE}))
        if state["status"]["phase"] != "Succeeded":
            raise RuntimeError("preflight failed; see retained test.log")
    finally:
        cleanup = []
        # Retrieve partial diagnostics even when scheduling or execution fails.
        if "pod" in created and not (args.output_dir / "test.log").exists():
            result = oc("logs", NAME, check=False)
            (args.output_dir / "test.log").write_text(result.stdout + result.stderr)
        for kind in reversed(created):
            result = oc("delete", kind, NAME, "--wait=false", check=False)
            cleanup.append({"kind": kind, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        (args.output_dir / "cleanup.json").write_text(json.dumps(cleanup, indent=2))


if __name__ == "__main__":
    main()
