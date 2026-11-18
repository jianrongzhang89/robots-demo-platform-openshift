#!/usr/bin/env python3
"""Render an isolated two-container Phase 1 warehouse/SAM3 qualification pod."""
import argparse
import json
from pathlib import Path

RUNTIME_IMAGE = ('image-registry.openshift-image-registry.svc:5000/semantic-navigation/'
                 'phase8-multilevel-fix@sha256:46042806035753067de14010aff4eb5d2c63e929f7c5a93e1c139311ee06c99e')
ADAPTER_IMAGE = ('image-registry.openshift-image-registry.svc:5000/semantic-navigation/'
                 'semantic-cpu-adapter@sha256:20ea4f5e6bc30646f48b29895eb071d40403f8c20b0c1526aeacf06dce716d4b')
DDS = ('<?xml version="1.0" encoding="UTF-8" ?>\n'
       '<CycloneDDS xmlns="https://cdds.io/config"><Domain id="any">'
       '<General><Interfaces><NetworkInterface name="lo" /></Interfaces>'
       '<AllowMulticast>false</AllowMulticast></General>'
       '<Discovery><Peers><Peer Address="127.0.0.1"/></Peers>'
       '<ParticipantIndex>auto</ParticipantIndex>'
       '<MaxAutoParticipantIndex>200</MaxAutoParticipantIndex></Discovery>'
       '<Internal><SocketReceiveBufferSize min="128 KiB" max="4 MiB"/>'
       '<NackDelay>1ms</NackDelay></Internal></Domain></CycloneDDS>')


def render(identity):
    name = 'warehouse-phase1-sam3'
    config = {'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': name, 'namespace': 'semantic-navigation'},
        'data': {'identity.json': json.dumps(identity, sort_keys=True),
                 'cyclonedds.xml': DDS}}
    common_mount = {'name': 'config', 'mountPath': '/config', 'readOnly': True}
    pod = {'apiVersion': 'v1', 'kind': 'Pod',
        'metadata': {'name': name, 'namespace': 'semantic-navigation',
            'labels': {'app': name, 'semantic-serving-client': 'sam3-mat-v1',
                       'phase': 'warehouse-phase1'}},
        'spec': {'serviceAccountName': 'sam3-replay', 'automountServiceAccountToken': False,
            'terminationGracePeriodSeconds': 10,
            'containers': [
                {'name': 'runtime', 'image': RUNTIME_IMAGE,
                 'command': ['/bin/bash', '-lc', 'sleep infinity'],
                 'env': [{'name': 'ROS_DOMAIN_ID', 'value': '188'},
                         {'name': 'RMW_IMPLEMENTATION', 'value': 'rmw_cyclonedds_cpp'},
                         {'name': 'GZ_PARTITION', 'value': 'warehouse_semantic_phase1'},
                         {'name': 'CYCLONEDDS_URI', 'value': 'file:///config/cyclonedds.xml'}],
                 'resources': {'requests': {'cpu': '1', 'memory': '3Gi'},
                               'limits': {'cpu': '4', 'memory': '8Gi'}},
                 'volumeMounts': [common_mount, {'name': 'work', 'mountPath': '/work'}]},
                {'name': 'adapter',
                 'image': f'image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-cpu-adapter@{ADAPTER_IMAGE.split("@",1)[1]}',
                 'command': ['/bin/bash', '-ec'],
                 'args': ['while [ ! -f /work/apps/semantic-perception/sam3_ros_node.py ]; do sleep 1; done; source /opt/ros/jazzy/setup.bash; export PYTHONPATH=/work/apps/semantic-perception:$PYTHONPATH; exec python3 /work/apps/semantic-perception/sam3_ros_node.py --ros-args -p backend:=http -p robot_id:=robot_1 -p stream_id:=camera/color -p input_prefix:=/robot_1/camera -p output_prefix:=/robot_1/semantic'],
                 'env': [{'name': 'SEMANTIC_BACKEND', 'value': 'http'},
                    {'name': 'SEMANTIC_ENDPOINT', 'value': 'https://sam3-mat-v1-tls.semantic-model-serving.svc:8443'},
                    {'name': 'SEMANTIC_TLS_CA', 'value': '/cert/ca.crt'},
                    {'name': 'SEMANTIC_TLS_CERT', 'value': '/cert/tls.crt'},
                    {'name': 'SEMANTIC_TLS_KEY', 'value': '/cert/tls.key'},
                    {'name': 'SEMANTIC_DEPLOYMENT_IDENTITY', 'value': '/config/identity.json'},
                    {'name': 'SEMANTIC_REQUIRE_CAPTURE_TRACE', 'value': '1'},
                    {'name': 'SEMANTIC_CLOCK_UNCERTAINTY_MS', 'value': '2'},
                    {'name': 'SEMANTIC_MAX_WORK_WAIT_MS', 'value': '40'},
                    {'name': 'SEMANTIC_STATUS_FILE', 'value': '/tmp/semantic-status.json'},
                    {'name': 'ROS_DOMAIN_ID', 'value': '188'},
                    {'name': 'RMW_IMPLEMENTATION', 'value': 'rmw_cyclonedds_cpp'},
                    {'name': 'CYCLONEDDS_URI', 'value': 'file:///config/cyclonedds.xml'}],
                 'resources': {'requests': {'cpu': '500m', 'memory': '768Mi'},
                               'limits': {'cpu': '2', 'memory': '2Gi'}},
                 'securityContext': {'allowPrivilegeEscalation': False,
                    'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']},
                    'seccompProfile': {'type': 'RuntimeDefault'}},
                 'readinessProbe': {'exec': {'command': ['python3', '-c',
                    'import json,time; s=json.load(open("/tmp/semantic-status.json")); assert s["ready"] and 0 <= time.time_ns()-s["status_wall_ns"] < 500000000']},
                    'periodSeconds': 1, 'timeoutSeconds': 1, 'failureThreshold': 1},
                 'volumeMounts': [common_mount,
                    {'name': 'tls', 'mountPath': '/cert', 'readOnly': True},
                    {'name': 'tmp', 'mountPath': '/tmp'},
                    {'name': 'work', 'mountPath': '/work'}]}],
            'volumes': [{'name': 'config', 'configMap': {'name': name}},
                {'name': 'tls', 'secret': {'secretName': 'sam3-replay-tls', 'defaultMode': 288}},
                {'name': 'tmp', 'emptyDir': {'sizeLimit': '256Mi'}},
                {'name': 'work', 'emptyDir': {'sizeLimit': '4Gi'}}]}}
    return {'apiVersion': 'v1', 'kind': 'List', 'items': [config, pod]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(render(json.loads(args.identity.read_text())), indent=2) + '\n')
