"""Presentation-only, view-only Gazebo sidecar for the private served fixture."""
import json
from pathlib import Path
import uuid

VIEWER_IMAGE = ('image-registry.openshift-image-registry.svc:5000/semantic-navigation/'
                'semantic-hotel-sim@sha256:d417c9f252d1f89dd859290a4bca1f634bcfd7d3cde6d1702c409d432bd48894')
GUI = '''<?xml version="1.0"?>
<window><width>960</width><height>600</height><menus><drawer default="false"/></menus></window>
<plugin filename="MinimalScene" name="OpenShift AI served navigation">
 <gz-gui><title>OpenShift AI served navigation — operator start required</title><property type="bool" key="showTitleBar">false</property><property type="string" key="state">docked</property></gz-gui>
 <!-- OGRE's simpler raster pipeline is substantially faster on this CPU-only
      viewer. The server's GPU RGB-D rendering and inference are unchanged. -->
 <engine>ogre</engine><anti_aliasing>0</anti_aliasing>
 <camera_clip><near>0.1</near><far>20</far></camera_clip>
 <scene>scene</scene><ambient_light>0.6 0.6 0.6</ambient_light>
 <background_color>0.8 0.8 0.8</background_color><camera_pose>17.4 -31.6 8 0 1.5707 0</camera_pose>
</plugin>
'''
for plugin in ['GzSceneManager', 'CameraTracking']:
    GUI += f'''<plugin filename="{plugin}" name="{plugin}"><gz-gui>
<property key="state" type="string">floating</property><property key="width" type="double">5</property><property key="height" type="double">5</property><property key="showTitleBar" type="bool">false</property>
</gz-gui></plugin>\n'''
SCRIPT = r'''#!/bin/bash
set -eo pipefail
export HOME=/tmp/viewer-home DISPLAY=:99 QT_QPA_PLATFORM=xcb QT_X11_NO_MITSHM=1
export LIBGL_ALWAYS_SOFTWARE=1 LP_NUM_THREADS=2 NVIDIA_VISIBLE_DEVICES=void
export GZ_IP=127.0.0.1 GZ_PARTITION=phase5-watchdog-native-qualification
export GZ_SIM_RESOURCE_PATH=/opt/ros2-demo/hotel-assets/models:/opt/ros2-demo/hotel-assets:/opt/rmf_demos_ws/install/share/rmf_demos_assets/models
mkdir -p "$HOME" /tmp/viewer-runtime
mkdir -p /tmp/viewer-fps
export GALLIUM_HUD=fps GALLIUM_HUD_VISIBLE=false GALLIUM_HUD_PERIOD=1
export GALLIUM_HUD_DUMP_DIR=/tmp/viewer-fps
chmod 700 /tmp/viewer-runtime
export XDG_RUNTIME_DIR=/tmp/viewer-runtime
source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash
trap 'kill $(jobs -pr) 2>/dev/null || true' EXIT
Xorg :99 -config /etc/X11/xorg-dummy.conf -nolisten tcp -logfile /tmp/viewer-xorg.log &
sleep 2
openbox >/tmp/viewer-openbox.log 2>&1 &
x11vnc -display :99 -rfbport 5900 -viewonly -shared -forever -nopw -noxdamage -noscr -clip 964x628+0+0 -wait 20 -defer 10 >/tmp/viewer-vnc.log 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/viewer-web.log 2>&1 &
gz sim --force-version 8 -g -v 3 --gui-config /phase5-native/g5-demo-gui.config >/tmp/viewer-gui.log 2>&1 &
# Attach only after the GUI's own services are ready. These services affect
# the camera, never the robot or world state.
initialize_camera_follow() {
  for _attempt in $(seq 1 90); do
    if gz service -s /gui/follow --reqtype gz.msgs.StringMsg --reptype gz.msgs.Boolean \
        --timeout 2000 --req 'data: "robot_1"' 2>/dev/null | grep -q 'data: true' &&
       gz service -s /gui/follow/offset --reqtype gz.msgs.Vector3d --reptype gz.msgs.Boolean \
        --timeout 2000 --req 'x: 0 y: 0 z: 5' 2>/dev/null | grep -q 'data: true'; then
      echo 'Camera following robot_1 overhead'
      return 0
    fi
    sleep 1
  done
  echo 'Camera follow initialization timed out' >&2
  return 1
}
initialize_camera_follow >/tmp/viewer-camera.log 2>&1 &
wait
'''


def attach_viewer(config, pod, output_dir):
    token = str(uuid.uuid4())
    config['data']['g5-demo-viewer.sh'] = SCRIPT
    config['data']['g5-demo-gui.config'] = GUI
    fixture = next(c for c in pod['spec']['containers'] if c['name'] == 'fixture')
    fixture['env'].append({'name': 'PHASE5_OPERATOR_DEMO_TOKEN', 'value': token})
    for env in fixture['env']:
        if env['name'] == 'PHASE5_FIXTURE_TIMEOUT_S':
            env['value'] = str(int(env['value']) + 600)
    # Keep the view-only recording window alive long enough for the presenter
    # to recover a browser session. The gate remains disarmed during this
    # entire hold; this extends no motion or command lease.
    pod['spec']['activeDeadlineSeconds'] += 1800
    pod['metadata'].setdefault('labels', {})['semantic-g5-demo'] = 'viewer'
    pod['spec']['containers'].append({
        'name': 'viewer', 'image': VIEWER_IMAGE,
        'command': ['bash', '/phase5-native/g5-demo-viewer.sh'],
        'ports': [{'name': 'novnc', 'containerPort': 6080}],
        'volumeMounts': [{'name': 'source', 'mountPath': '/phase5-native', 'readOnly': True}],
        'resources': {'requests': {'cpu': '1', 'memory': '512Mi'},
                      'limits': {'cpu': '3', 'memory': '3Gi'}},
        'securityContext': {'runAsNonRoot': True, 'allowPrivilegeEscalation': False,
                            'capabilities': {'drop': ['ALL']},
                            'seccompProfile': {'type': 'RuntimeDefault'}}})
    (Path(output_dir)/'operator-demo.json').write_text(json.dumps({
        'token': token, 'operator_wait_seconds': 1800, 'viewer_image': VIEWER_IMAGE,
        'mat_size_m': [1.2, 1.95], 'viewer_engine': 'ogre',
        'scope': 'Presentation extension of accepted G4 profile; view-only GUI, explicit pre-arm hold; no qualification claim',
        'release_path': '/tmp/phase5-native-results/operator-start.json'}, indent=2)+'\n')
