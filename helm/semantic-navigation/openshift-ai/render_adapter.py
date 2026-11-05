#!/usr/bin/env python3
"""Render the isolated G2 CPU diagnostic pod; never connects to navigation DDS."""
import argparse
import json
from pathlib import Path

DIGEST = 'sha256:20ea4f5e6bc30646f48b29895eb071d40403f8c20b0c1526aeacf06dce716d4b'
DDS = '<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo" multicast="true"/></Interfaces><AllowMulticast>true</AllowMulticast></General></Domain></CycloneDDS>'


def resources(identity, node):
    name = 'semantic-s2-adapter'
    meta = {'name': name, 'namespace': 'semantic-navigation'}
    config = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta,
              'data': {'identity.json': json.dumps(identity, sort_keys=True), 'cyclonedds.xml': DDS}}
    env = {'SEMANTIC_BACKEND': 'http',
           'SEMANTIC_ENDPOINT': 'https://sam3-mat-v1-tls.semantic-model-serving.svc:8443',
           'SEMANTIC_TLS_CA': '/cert/ca.crt', 'SEMANTIC_TLS_CERT': '/cert/tls.crt',
           'SEMANTIC_TLS_KEY': '/cert/tls.key', 'SEMANTIC_DEPLOYMENT_IDENTITY': '/config/identity.json',
           'SEMANTIC_REQUIRE_CAPTURE_TRACE': '1', 'SEMANTIC_CLOCK_UNCERTAINTY_MS': '2',
           'SEMANTIC_MAX_WORK_WAIT_MS': '40', 'SEMANTIC_STATUS_FILE': '/tmp/semantic-status.json',
           'ROS_DOMAIN_ID': '188', 'CYCLONEDDS_URI': 'file:///config/cyclonedds.xml'}
    probe = 'import json,time; s=json.load(open("/tmp/semantic-status.json")); assert s["ready"] and 0 <= time.time_ns()-s["status_wall_ns"] < 500000000'
    pod = {'apiVersion': 'v1', 'kind': 'Pod',
           'metadata': {**meta, 'labels': {'app': name, 'semantic-serving-client': 'sam3-mat-v1'}},
           'spec': {'nodeSelector': {'kubernetes.io/hostname': node}, 'serviceAccountName': 'sam3-replay',
                    'automountServiceAccountToken': False, 'terminationGracePeriodSeconds': 10,
                    'containers': [{'name': 'adapter', 'image': f'image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-cpu-adapter@{DIGEST}',
                        'command': ['/bin/bash', '-ec'],
                        'args': ['source /opt/ros/jazzy/setup.bash; exec python3 /opt/semantic-perception/sam3_ros_node.py --ros-args -p backend:=http -p robot_id:=robot_1 -p stream_id:=camera/color -p input_prefix:=/g2/robot_1/camera -p output_prefix:=/g2/robot_1/semantic'],
                        'env': [{'name': k, 'value': v} for k, v in env.items()],
                        'resources': {'requests': {'cpu': '1', 'memory': '1Gi'}, 'limits': {'cpu': '2', 'memory': '2Gi'}},
                        'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                            'capabilities': {'drop': ['ALL']}, 'seccompProfile': {'type': 'RuntimeDefault'}},
                        'readinessProbe': {'exec': {'command': ['python3', '-c', probe]}, 'periodSeconds': 1, 'timeoutSeconds': 1, 'failureThreshold': 1},
                        'volumeMounts': [{'name': 'config', 'mountPath': '/config', 'readOnly': True},
                                         {'name': 'tls', 'mountPath': '/cert', 'readOnly': True}, {'name': 'tmp', 'mountPath': '/tmp'}]}],
                    'volumes': [{'name': 'config', 'configMap': {'name': name}},
                                {'name': 'tls', 'secret': {'secretName': 'sam3-replay-tls', 'defaultMode': 288}},
                                {'name': 'tmp', 'emptyDir': {'sizeLimit': '256Mi'}}]}}
    return {'apiVersion': 'v1', 'kind': 'List', 'items': [config, pod]}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--node', required=True, help='Verified non-GPU worker hostname')
    args = parser.parse_args()
    print(json.dumps(resources(json.loads(args.identity.read_text()), args.node), indent=2))
