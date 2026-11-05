#!/usr/bin/env python3
"""Isolated G3 sensor -> CPU HTTP adapter -> diagnostic costmap topology."""
import argparse
import copy
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[3]
BRIDGE='eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18'
ROUTER='docker.io/eclipse/zenoh@sha256:137310456cc7a75d955063513207c737f25071fbb74fd7641835c50ab8e3369f'

def render(costmap_image):
    text=(ROOT/'helm/semantic-navigation/phase4-isolated-costmaps.yaml').read_text().replace('semantic-phase4','semantic-s3').replace('semantic_phase4','semantic_s3').replace('/phase4-config','/g3-config')
    docs=list(yaml.safe_load_all(text));config=docs[0]
    data=config['data']
    data['cyclonedds-consumer.xml']=data['cyclonedds-consumer.xml'].replace('<Internal>', '<Internal><SocketReceiveBufferSize min="4 MiB" max="4 MiB"/>')
    data['identity.json']=(ROOT/'docs/validation/semantic-navigation/openshift-ai/S2/g2-qualification-20261031/expected-identity.json').read_text()
    for name in ('g3_simulator.sh','g3_odom_tf.py','audit_g3_capture_timing.py','g3_cloud_validation.py'):
        data[name]=(ROOT/'scripts/semantic-navigation'/name).read_text()
    for obj in docs:
        if obj['kind']!='Pod':continue
        spec=obj['spec'];spec['automountServiceAccountToken']=False
        for c in spec['containers']:
            if 'zenoh-bridge' in c['name']:c['image']=BRIDGE
            if c['name']=='router':c['image']=ROUTER
            for e in c.get('env',[]):
                if e['name']=='ROS_DOMAIN_ID':e['value']={'81':'190','82':'191'}[e['value']]
        if obj['metadata']['name']=='semantic-s3-simulator':
            spec['nodeSelector']={'kubernetes.io/hostname':'ip-10-0-44-146.ec2.internal'}
            spec['tolerations']=[{'key':'g5-gpu','operator':'Equal','value':'true','effect':'NoSchedule'}]
            sim=spec['containers'][0];sim['command']=['/bin/bash','/g3-config/g3_simulator.sh']
            sim['env'] += [{'name':'NVIDIA_DRIVER_CAPABILITIES','value':'all'}]
            sim['resources']={'requests':{'cpu':'3','memory':'3Gi','nvidia.com/gpu':1},'limits':{'cpu':'6','memory':'8Gi','nvidia.com/gpu':1}}
        if obj['metadata']['name']=='semantic-s3-inference':
            spec['nodeSelector']={'kubernetes.io/hostname':'ip-10-0-53-174.ec2.internal'};spec.pop('tolerations',None)
            spec.pop('securityContext',None);spec['serviceAccountName']='sam3-replay'
            obj['metadata']['labels']['semantic-serving-client']='sam3-mat-v1'
            adapter=json.loads((ROOT/'docs/validation/semantic-navigation/openshift-ai/S2/g2-qualification-20261031/adapter-resources.json').read_text())['items'][1]['spec']['containers'][0]
            adapter=copy.deepcopy(adapter);adapter['name']='adapter'
            adapter['args']=['source /opt/ros/jazzy/setup.bash; exec python3 /opt/semantic-perception/sam3_ros_node.py --ros-args -p backend:=http -p robot_id:=robot_1 -p stream_id:=camera/color']
            for e in adapter['env']:
                if e['name']=='ROS_DOMAIN_ID':e['value']='191'
                if e['name']=='SEMANTIC_MAX_WORK_WAIT_MS':e['value']='60'
                if e['name']=='CYCLONEDDS_URI':e['value']='file:///g3-config/cyclonedds-consumer.xml'
                if e['name']=='SEMANTIC_DEPLOYMENT_IDENTITY':e['value']='/g3-config/identity.json'
            adapter['volumeMounts'][0]['mountPath']='/g3-config'
            spec['containers'][1]=adapter
            cost=spec['containers'][2];cost['image']=costmap_image
            cost['args']=['source /opt/semantic-costmap-ws/install/setup.bash; exec /opt/g3/build/g3_observer --ros-args -p use_sim_time:=true -p global_frame:=odom -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static']
            spec['volumes']=[v for v in spec['volumes'] if v['name']!='model']
            spec['volumes'] += [{'name':'tls','secret':{'secretName':'sam3-replay-tls','defaultMode':288}}, {'name':'tmp','emptyDir':{'sizeLimit':'512Mi'}}]
            # Active throughout measurement, separately quota-bounded, no network IO.
            spec['containers'].append({'name':'background-load','image':adapter['image'],'command':['python3','-c'],
              'args':['import time\nwhile True:\n t=time.monotonic()\n while time.monotonic()-t<0.05: pass\n time.sleep(0.05)'],
              'resources':{'requests':{'cpu':'500m','memory':'32Mi'},'limits':{'cpu':'500m','memory':'64Mi'}},
              'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}})
    return {'apiVersion':'v1','kind':'List','items':docs}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--costmap-image',required=True);args=p.parse_args()
    if '@sha256:' not in args.costmap_image: p.error('digest pin required')
    print(json.dumps(render(args.costmap_image),indent=2))
