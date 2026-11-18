#!/usr/bin/env python3
"""Read-only capture of the hotel baseline; never exports Secrets or credentials."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(args):
    return subprocess.check_output(args, text=True, timeout=60)


def serving_inventory():
    pods = json.loads(run(["oc", "get", "pods", "-n", "semantic-model-serving", "-o", "json"]))
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "pods": [
        {"name": p["metadata"]["name"], "uid": p["metadata"]["uid"],
         "phase": p["status"]["phase"], "containers": [
             {k: c.get(k) for k in ("name", "image", "imageID", "ready", "restartCount")}
             for c in p["status"].get("containerStatuses", [])]}
        for p in pods["items"]]}


def capture(output):
    output.mkdir(parents=True, exist_ok=False)
    ns = "semantic-navigation"
    pods = json.loads(run(["oc", "get", "pods", "-n", ns, "-l",
                           "app=phase8-multilevel-hotel", "-o", "json"]))
    running = [p for p in pods["items"] if p["status"]["phase"] == "Running"
               and not p["metadata"].get("deletionTimestamp")]
    if len(running) != 1:
        raise RuntimeError("expected exactly one running hotel pod")
    pod = running[0]
    name = pod["metadata"]["name"]
    prefix = ["oc", "exec", "-n", ns, name, "-c", "hotel-nav2-rmf", "--"]
    inventory = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "git_head": run(["git", "rev-parse", "HEAD"]).strip(),
        "git_status": run(["git", "status", "--short"]),
        "cluster": run(["oc", "whoami", "--show-server"]).strip(),
        "namespace": ns, "pod": name, "pod_uid": pod["metadata"]["uid"],
        "images": [{"name": c["name"], "image": c["image"],
                    "imageID": c.get("imageID"), "ready": c.get("ready"),
                    "restartCount": c.get("restartCount")}
                   for c in pod["status"].get("containerStatuses", [])],
        "helm": json.loads(run(["helm", "list", "-n", ns, "-o", "json"])),
    }
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    (output / "serving-pods.json").write_text(json.dumps(serving_inventory(), indent=2) + "\n")
    # This chart's values contain only image/configuration references, no credentials.
    (output / "helm-values.json").write_text(run([
        "helm", "get", "values", "phase8-multilevel", "-n", ns, "-a", "-o", "json"]))
    config = json.loads(run(["oc", "get", "configmap", "phase8-multilevel-serving-config",
                             "-n", ns, "-o", "json"]))["data"]
    config_dir = output / "mounted-config"
    config_dir.mkdir()
    for key, value in config.items():
        if Path(key).name != key:
            raise ValueError("unexpected ConfigMap filename")
        (config_dir / key).write_text(value)
    assets = ["/tmp/phase8-robot.urdf", "/tmp/phase8-nav-graph.yaml",
              "/tmp/phase8-multilevel-hotel.world", "/opt/ros2-demo/rmf/fleet_config.yaml"]
    for path in assets:
        (output / Path(path).name).write_text(run(prefix + ["cat", path]))
    (output / "packages.txt").write_text(run(prefix + ["bash", "-lc",
        "dpkg-query -W 'ros-jazzy-rmf*' 'ros-jazzy-nav2*' 'gz-sim*'"]))
    # Record geometry sources and generated map hashes without copying large meshes.
    (output / "runtime-asset-sha256.txt").write_text(run(prefix + ["bash", "-lc",
        "find /opt/ros2-demo/hotel-assets /tmp/phase8-maps -type f -exec sha256sum {} +"]))
    local_paths = sorted((ROOT / "helm/phase8-multilevel-demo").rglob("*"))
    (output / "repository-sha256.json").write_text(json.dumps({
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in local_paths if p.is_file()}, indent=2) + "\n")
    hashes = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"status": "CAPTURED", "pod": name, "files": len(hashes)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    capture(parser.parse_args().output)
