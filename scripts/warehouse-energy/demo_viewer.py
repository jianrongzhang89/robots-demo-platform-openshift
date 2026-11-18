#!/usr/bin/env python3
"""Render the visual energy-demo pod: simulation + view-only noVNC viewer.

Extends the Stage 4 demo pod with a viewer sidecar following the accepted
G5 presentation pattern: a dummy X server, a view-only x11vnc, and
websockify/noVNC on port 6080, plus a Gazebo GUI-only client that joins
the trial partition on pod-local loopback and follows robot_1. The GUI
client restarts whenever the simulation server changes between trial
legs. The main container runs the audited demo machinery unchanged; the
viewer is presentation-only and never issues commands.

The rendered Service and Route expose the noVNC page in a browser
(https://<route>/vnc.html?autoconnect=1). For a private session, skip the
Route and use `oc port-forward` instead.
"""
import argparse
import json

IMAGE = ("image-registry.openshift-image-registry.svc:5000/semantic-navigation/"
         "phase8-multilevel-fix@sha256:46042806035753067de14010aff4eb5d2c63e929f7c5a"
         "93e1c139311ee06c99e")

GUI_CONFIG = '''<?xml version="1.0"?>
<window><width>1280</width><height>800</height><menus><drawer default="false"/></menus></window>
<plugin filename="MinimalScene" name="Warehouse energy demo">
 <gz-gui><title>Energy-aware warehouse delivery</title><property type="bool" key="showTitleBar">false</property></gz-gui>
 <!-- CPU raster pipeline; the server's rendering and physics are unchanged. -->
 <engine>ogre</engine><anti_aliasing>0</anti_aliasing>
 <camera_clip><near>0.1</near><far>60</far></camera_clip>
 <scene>scene</scene><ambient_light>0.7 0.7 0.7</ambient_light>
 <background_color>0.85 0.85 0.85</background_color>
 <camera_pose>10 -14 10 0 0.53 1.5708</camera_pose>
</plugin>
<plugin filename="GzSceneManager" name="GzSceneManager"><gz-gui>
<property key="state" type="string">floating</property><property key="width" type="double">5</property><property key="height" type="double">5</property><property key="showTitleBar" type="bool">false</property>
</gz-gui></plugin>
<plugin filename="CameraTracking" name="CameraTracking"><gz-gui>
<property key="state" type="string">floating</property><property key="width" type="double">5</property><property key="height" type="double">5</property><property key="showTitleBar" type="bool">false</property>
</gz-gui></plugin>
'''

VIEWER_SCRIPT = r'''#!/bin/bash
set -uo pipefail
export HOME=/tmp/viewer-home DISPLAY=:99 QT_QPA_PLATFORM=xcb QT_X11_NO_MITSHM=1
export LIBGL_ALWAYS_SOFTWARE=1 LP_NUM_THREADS=4 NVIDIA_VISIBLE_DEVICES=void
# Same pod as the simulation: Gazebo transport on loopback, trial partition.
export GZ_IP=127.0.0.1 GZ_PARTITION=warehouse_navigation_trial
mkdir -p "$HOME" /tmp/viewer-runtime
chmod 700 /tmp/viewer-runtime
export XDG_RUNTIME_DIR=/tmp/viewer-runtime
cat > /tmp/viewer-gui.config <<'EOG'
''' + GUI_CONFIG + r'''EOG
trap 'kill $(jobs -pr) 2>/dev/null || true' EXIT
Xorg :99 -config /etc/X11/xorg-dummy.conf -nolisten tcp -logfile /tmp/viewer-xorg.log &
sleep 2
openbox >/tmp/viewer-openbox.log 2>&1 &
x11vnc -display :99 -rfbport 5900 -viewonly -shared -forever -nopw -noxdamage -noscr \
  -clip 1284x828+0+0 -wait 20 -defer 10 >/tmp/viewer-vnc.log 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/viewer-web.log 2>&1 &
# Each demo leg starts a fresh simulation server on the partition; restart
# the GUI client whenever the current server is gone so the browser view
# follows every delivery instead of freezing on the previous world.
gui_pid=""
start_gui() {
  gz sim --force-version 8 -g -v 1 --gui-config /tmp/viewer-gui.config >>/tmp/viewer-gui.log 2>&1 &
  gui_pid=$!
}
start_gui
while true; do
  sleep 4
  if ! timeout 3 gz topic -l 2>/dev/null | grep -q "^/world/"; then
    if [ -n "$gui_pid" ] && kill -0 "$gui_pid" 2>/dev/null; then
      kill "$gui_pid" 2>/dev/null || true
      sleep 1
    fi
    start_gui
  elif [ -n "$gui_pid" ] && ! kill -0 "$gui_pid" 2>/dev/null; then
    start_gui
  fi
  # Re-assert camera follow after every GUI restart.
  gz service -s /gui/follow --reqtype gz.msgs.StringMsg --reptype gz.msgs.Boolean \
    --timeout 2000 --req 'data: "robot_1"' >/dev/null 2>&1 || true
done
'''


def render(name="warehouse-energy-demo"):
    labels = {"app": "warehouse-energy-demo-run",
              "energy-serving-client": "energy-predictor-v1"}
    main = {
        "name": "runtime", "image": IMAGE,
        "command": ["sleep", "infinity"],
        "env": [{"name": k, "value": v} for k, v in {
            "ROS_DOMAIN_ID": "85", "GZ_PARTITION": "warehouse_navigation_trial",
            "GZ_IP": "127.0.0.1", "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
            "HOME": "/tmp"}.items()],
        "resources": {"requests": {"cpu": "2", "memory": "4Gi"},
                      "limits": {"cpu": "4", "memory": "8Gi"}},
        "volumeMounts": [{"name": "work", "mountPath": "/work"},
                         {"name": "tls", "mountPath": "/tls", "readOnly": True}],
    }
    viewer = {
        "name": "viewer", "image": IMAGE,
        "command": ["bash", "-c", VIEWER_SCRIPT],
        "ports": [{"name": "novnc", "containerPort": 6080}],
        "resources": {"requests": {"cpu": "1", "memory": "1Gi"},
                      "limits": {"cpu": "3", "memory": "3Gi"}},
        "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": False,
                            "capabilities": {"drop": ["ALL"]},
                            "seccompProfile": {"type": "RuntimeDefault"}},
        "volumeMounts": [{"name": "work", "mountPath": "/work", "readOnly": True}],
    }
    pod = {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": name, "namespace": "warehouse-energy", "labels": labels},
        "spec": {
            "restartPolicy": "Never", "terminationGracePeriodSeconds": 15,
            "containers": [main, viewer],
            "volumes": [
                {"name": "work", "emptyDir": {"sizeLimit": "8Gi"}},
                {"name": "tls", "secret": {"secretName": "energy-serving-client-tls"}},
            ]}}
    service = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": f"{name}-novnc", "namespace": "warehouse-energy"},
        "spec": {"type": "ClusterIP", "selector": {"app": "warehouse-energy-demo-run"},
                 "ports": [{"name": "novnc", "port": 6080, "targetPort": 6080}]}}
    route = {
        "apiVersion": "route.openshift.io/v1", "kind": "Route",
        "metadata": {"name": f"{name}-novnc", "namespace": "warehouse-energy"},
        "spec": {"to": {"kind": "Service", "name": f"{name}-novnc"},
                 "port": {"targetPort": "novnc"},
                 "tls": {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"}}}
    return {"apiVersion": "v1", "kind": "List",
            "items": [pod, service, route]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=argparse.FileType("w"), default="-")
    args = parser.parse_args()
    args.output.write(json.dumps(render(), indent=2) + "\n")
