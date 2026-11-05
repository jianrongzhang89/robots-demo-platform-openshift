#!/usr/bin/env python3
"""Render an isolated Phase 4 profile from pinned Phase 3 sources, never canonical Helm.

Usage: python3 render_phase4_profile.py --costmap-image IMAGE@sha256:... \
  --runtime-image IMAGE@sha256:... | oc apply -f -
"""
import argparse
from pathlib import Path
import re
import sys
import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--costmap-image", required=True)
    parser.add_argument("--runtime-image", required=True)
    args = parser.parse_args()
    for value in (args.costmap_image, args.runtime_image):
        if not re.fullmatch(r"image-registry\.openshift-image-registry\.svc:5000/semantic-navigation/[a-z0-9-]+@sha256:[a-f0-9]{64}", value):
            parser.error("Only digest-pinned images in semantic-navigation are allowed")
    root = Path(__file__).resolve().parents[2]
    text = (root / "helm/semantic-navigation/phase3-native-bounded-diagnostic.yaml").read_text()
    text = text.replace("semantic-phase3", "semantic-phase4").replace("semantic_phase3", "semantic_phase4").replace("/phase3-config", "/phase4-config")
    documents = list(yaml.safe_load_all(text))
    for obj in documents:
        if obj["kind"] != "Pod":
            continue
        for container in obj["spec"]["containers"]:
            for env in container.get("env", []):
                if env["name"] == "ROS_DOMAIN_ID":
                    env["value"] = {"79": "81", "80": "82"}[env["value"]]
            if container["name"] == "sam3-inference":
                container["image"] = args.runtime_image
        if obj["metadata"]["name"] == "semantic-phase4-inference":
            obj["spec"]["containers"].append({
                "name": "costmap-observer", "image": args.costmap_image,
                "command": ["/bin/bash", "-lc"],
                "args": ["source /opt/semantic-costmap-ws/install/setup.bash; exec ros2 run demo_semantic_costmap phase4_observer --ros-args -p use_sim_time:=true -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static"],
                "env": [{"name": "ROS_DOMAIN_ID", "value": "82"},
                        {"name": "ROS_LOG_DIR", "value": "/tmp/phase4-ros-logs"},
                        {"name": "RMW_IMPLEMENTATION", "value": "rmw_cyclonedds_cpp"},
                        {"name": "CYCLONEDDS_URI", "value": "file:///phase4-config/cyclonedds-consumer.xml"}],
                "volumeMounts": [{"name": "config", "mountPath": "/phase4-config", "readOnly": True}],
                "resources": {"requests": {"cpu": "1", "memory": "1Gi"}, "limits": {"cpu": "3", "memory": "3Gi"}},
                "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
                                    "runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
            })
    yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)


if __name__ == "__main__":
    main()
