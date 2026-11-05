#!/usr/bin/env python3
"""Private served-navigation topology; never displaces the accepted local SAM3 pod."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import shlex
import time
from phase6_topology import topology_objects

ROOT = Path(__file__).resolve().parents[2]
OC = '/Users/zhangj/bin/oc'
POD = 'semantic-g4-sam3'
ROUTER = POD + '-router'
CONFIG = 'semantic-g4-sam3-config'
IDENTITY = ROOT/'docs/validation/semantic-navigation/openshift-ai/S2/g2-qualification-20261031/expected-identity.json'
DDS = '<CycloneDDS><Domain id="any"><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex></Discovery><Internal><SocketReceiveBufferSize min="4 MiB" max="4 MiB"/><NackDelay>1ms</NackDelay></Internal></Domain></CycloneDDS>'


def call(*args, check=True, obj=None):
    return subprocess.run([OC, '-n', 'semantic-navigation', *args], input=json.dumps(obj) if obj else None, text=True, capture_output=True, check=check, timeout=180)


def resources(fault_proxy=False):
    spec = importlib.util.spec_from_file_location('adapter_renderer', ROOT/'helm/semantic-navigation/openshift-ai/render_adapter.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    adapter_config, pod = module.resources(json.loads(IDENTITY.read_text()), 'ip-10-0-53-174.ec2.internal')['items']
    old = topology_objects('unused')
    config, service, router = json.loads(json.dumps(old[:3]).replace('semantic-phase5-sam3', POD))
    config['metadata']['name'] = CONFIG
    for v in router['spec']['template']['spec']['volumes']: v['configMap']['name'] = CONFIG
    config['data'].update({'cyclonedds.xml': DDS, 'identity.json': IDENTITY.read_text()})
    pod['metadata']['name'] = POD; pod['metadata']['labels']['app'] = POD
    pod['metadata']['labels']['semantic-qualification'] = 'g4'
    c = pod['spec']['containers'][0]; c['name'] = 'sam3-inference'
    c['args'] = ['source /opt/ros/jazzy/setup.bash; python3 /opt/semantic-perception/sam3_ros_node.py --ros-args -p backend:=http -p robot_id:=robot_1 -p stream_id:=camera/color & echo $! > /tmp/sam3-python.pid; wait $(cat /tmp/sam3-python.pid)']
    for e in c['env']:
        if e['name']=='ROS_DOMAIN_ID': e['value']='86'
        if e['name']=='SEMANTIC_MAX_WORK_WAIT_MS': e['value']='60'
    c['env'] += [{'name':'HOME','value':'/tmp/g4-home'},{'name':'ROS_LOG_DIR','value':'/tmp/g4-logs'}]
    pod['spec']['volumes'][0]['configMap']['name'] = CONFIG
    bridge = copy.deepcopy(old[3]['spec']['containers'][0])
    bridge['volumeMounts'] = [{'name':'config','mountPath':'/phase5-bridges','readOnly':True}]
    # 1 CPU at the 30 simulation-Hz candidate: frame traffic doubles and
    # this bridge must never throttle the capture stream the armed lease
    # freshness depends on.
    bridge['resources'] = {'requests': {'cpu': '200m', 'memory': '128Mi'},
                           'limits': {'cpu': '1', 'memory': '512Mi'}}
    pod['spec']['containers'].insert(0, bridge)
    if fault_proxy:
        config['data']['g4_fault_proxy.py'] = (ROOT/'scripts/semantic-navigation/g4_fault_proxy.py').read_text()
        pod['metadata']['labels']['g4-fault-proxy'] = 'true'
        pod['spec']['volumes'].append({'name':'proxy-tls','secret':{'secretName':'semantic-g4-proxy-tls','defaultMode':288}})
        c['volumeMounts'].append({'name':'proxy-tls','mountPath':'/proxy-tls','readOnly':True})
        for e in c['env']:
            if e['name']=='SEMANTIC_ENDPOINT': e['value']='https://localhost:9443'
            if e['name']=='SEMANTIC_TLS_CA': e['value']='/proxy-tls/tls.crt'
        proxy = {'name':'fault-proxy','image':c['image'],'command':['python3','/config/g4_fault_proxy.py'],
                 'volumeMounts':copy.deepcopy(c['volumeMounts']),
                 'securityContext':copy.deepcopy(c['securityContext']),
                 'resources':{'requests':{'cpu':'100m','memory':'64Mi'},'limits':{'cpu':'1','memory':'256Mi'}}}
        # Proxy TLS listener must be up before the adapter's one-time identity load.
        listener_probe = shlex.quote('import socket; socket.create_connection(("127.0.0.1",9443),1).close()')
        c['args'][0] = f'until python3 -c {listener_probe} 2>/dev/null; do sleep 1; done; ' + c['args'][0]
        pod['spec']['containers'].append(proxy)
    return [config,service,router,pod]


STATUS_COMMAND = ['python3', '-c', 'import json,time; print(json.dumps({"observed_wall_ns":time.time_ns(), "status":json.load(open("/tmp/semantic-status.json"))}))']

def initialized(pod, envelope, expected):
    status = envelope.get('status', {})
    states = {c['name']:c for c in pod.get('status',{}).get('containerStatuses',[])}
    return (pod.get('metadata',{}).get('labels',{}).get('semantic-qualification')=='g4'
            and pod.get('status',{}).get('phase')=='Running'
            and states.get('sam3-zenoh-bridge',{}).get('ready') is True
            and 'running' in states.get('sam3-inference',{}).get('state',{})
            and status.get('backend')=='http' and status.get('deployment_identity')==expected
            and 0<=envelope.get('observed_wall_ns',0)-status.get('status_wall_ns',0)<2_000_000_000)


def wait_initialized():
    expected=json.loads(IDENTITY.read_text())
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        p=call('get','pod',POD,'-o','json',check=False)
        s=call('exec',POD,'-c','sam3-inference','--',*STATUS_COMMAND,check=False)
        try:
            if initialized(json.loads(p.stdout),json.loads(s.stdout),expected): return
        except ValueError: pass
        time.sleep(2)
    raise RuntimeError('G4 adapter did not initialize with pinned identity')


def create_with_retry(obj, attempts=3, settle=15.0):
    """The served-navigation series recycles the topology before every trial
    (~110 per series); a single transient API error, or a deletion that has
    not yet propagated, must not kill a fully passing series
    (paired-series-5: one `oc create` exited 2 during the per-trial
    recycle). Each retry re-deletes the target first so AlreadyExists
    from a partially-propagated deletion is also covered."""
    result=None
    for attempt in range(attempts):
        result=call('create','-f','-',obj=obj,check=False)
        if result.returncode==0: return result
        if attempt<attempts-1:
            time.sleep(settle)
            call('delete',obj['kind'],obj['metadata']['name'],
                 '--ignore-not-found','--wait=true','--timeout=60s',check=False)
    raise RuntimeError(f"{obj['kind']} {obj['metadata']['name']} creation failed "
                       f"after {attempts} attempts: {(result.stderr or '').strip()[-200:]}")


def recycle(fault_proxy=False):
    # The initial deletes are best-effort: a transient API failure here
    # (paired-series-19: one `oc delete` exited 1 on an otherwise healthy
    # cluster) is fully covered by create_with_retry's internal re-delete,
    # and a genuinely missing resource is already ignored.
    call('delete','pod',POD,'--ignore-not-found','--wait=true','--timeout=50s',check=False)
    call('delete','deployment',ROUTER,'--ignore-not-found','--wait=true','--timeout=60s',check=False)
    objs=resources(fault_proxy)
    create_with_retry(objs[2])
    call('rollout','status','deployment/'+ROUTER,'--timeout=180s')
    create_with_retry(objs[3]); wait_initialized()


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('action',choices=('up','down','recycle','render')); p.add_argument('--output-dir',type=Path); p.add_argument('--fault-proxy',action='store_true'); a=p.parse_args()
    objs=resources(a.fault_proxy)
    if a.action=='render': print(json.dumps({'apiVersion':'v1','kind':'List','items':objs},indent=2)); return
    if a.action=='recycle': recycle(); return
    if a.action=='down':
        for o in reversed(objs): call('delete',o['kind'],o['metadata']['name'],'--ignore-not-found','--wait=true','--timeout=60s')
        return
    if not a.output_dir: p.error('up requires --output-dir')
    a.output_dir.mkdir(parents=True,exist_ok=False)
    (a.output_dir/'resources.json').write_text(json.dumps(objs,indent=2)+'\n')
    for o in objs:
        call('create','-f','-',obj=o)
        if o['kind']=='Deployment': call('rollout','status','deployment/'+ROUTER,'--timeout=180s')
    wait_initialized()
    (a.output_dir/'initialized.json').write_text(call('exec',POD,'-c','sam3-inference','--','cat','/tmp/semantic-status.json').stdout)

if __name__=='__main__': main()
