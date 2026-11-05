#!/usr/bin/env python3
"""Actual serving-pod loss during qualified semantic-armed motion.

Uses the original serving-fault evaluator, pinned runtime and direct HTTP adapter.
No proxy response injection, changed thresholds, or armed retries.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from g4_topology import ROOT, OC, POD, call
from run_g4_faults import configure, fixture_status
from run_g4_serving_pilot import pod_ready, RESERVATION_POD
from phase6_trial import IMAGE, NODE
from run_phase5_semantic_fault_matrix import trial_passed


def serving_pods():
    return json.loads(call('get','pods','-n','semantic-model-serving','-l',
        'serving.kserve.io/inferenceservice=sam3-mat-v1','-o','json').stdout)['items']


def ready(pod):
    return not pod['metadata'].get('deletionTimestamp') and any(
        c.get('type')=='Ready' and c.get('status')=='True' for c in pod.get('status',{}).get('conditions',[]))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--reservation',type=Path,required=True);a=p.parse_args()
    a.output_dir.mkdir(parents=True,exist_ok=False)
    result={'started_at':datetime.now(timezone.utc).isoformat(),'passed':False,'injected':False,'replacement_ready':False,'events':[]}
    owned=False;run=None
    def save(name,value):(a.output_dir/name).write_text(json.dumps(value,indent=2)+'\n')
    try:
        for kind,name in [('configmap','semantic-phase5-native'),('pod','semantic-phase5-native'),('pod',POD),('deployment','semantic-g4-sam3-router')]:
            if call('get',kind,name,'--ignore-not-found','-o','name').stdout.strip():raise RuntimeError('existing fixture: '+name)
        if not a.reservation.is_file() or not pod_ready(RESERVATION_POD):raise RuntimeError('reservation prerequisite failed')
        pods=serving_pods()
        expected=json.loads((ROOT/'docs/validation/semantic-navigation/openshift-ai/S2/gate-result.json').read_text())['deployment_identity']
        if len(pods)!=1 or not ready(pods[0]):raise RuntimeError('one Ready server required')
        if not any(c['name']=='kserve-container' and c.get('imageID','').endswith('@'+expected['container_digest']) for c in pods[0]['status']['containerStatuses']):raise RuntimeError('baseline image differs')
        original=pods[0];save('serving-before.json',original)
        files=[Path(__file__),ROOT/'scripts/semantic-navigation/run_phase5_native.py',ROOT/'scripts/semantic-navigation/run_g4_faults.py',ROOT/'apps/semantic-safety/semantic_fault_probe.py']
        save('protocol.json',{'freshness_ms':500,'zero_command_ms':100,'attempts':1,'mode':'serving','injection':'delete actual model-serving pod with one-second grace after fresh verified motion; fixture-clock attribution interval; no response proxy','image':IMAGE,'model_identity':expected,'source_hashes':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}})
        call('delete','pod',RESERVATION_POD,'--wait=true','--timeout=120s');owned=True
        objects=configure(False);save('topology.json',objects)
        trial=a.output_dir/'trial'
        command=[sys.executable,str(ROOT/'scripts/semantic-navigation/run_phase5_native.py'),'--oc',OC,'--suite','hotel-guarded','--contact-audit','--sam3-observation','--served-topology','--semantic-fault-probe','--semantic-fault-mode','serving','--console-only-server','--rear-casters','--physics-step','0.002','--lidar-range','12','--odom-frequency','200','--gpu-rendering','--node-name',NODE,'--image',IMAGE,'--output-dir',str(trial)]
        save('command.json',command)
        with (a.output_dir/'runner.log').open('w') as log, (a.output_dir/'navigation-samples.jsonl').open('x') as samples:
            run=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+1200
            while run.poll() is None:
                if time.monotonic()>deadline:raise TimeoutError('bounded 1200 second trial window exceeded')
                state=fixture_status()
                row={'observed_wall_ns':time.time_ns(),'fixture':state}
                # Read-only operator telemetry; never feeds a lease or command.
                status=call('exec',POD,'-c','sam3-inference','--','cat','/tmp/semantic-status.json',check=False)
                try:row['adapter']=json.loads(status.stdout)
                except ValueError:row['adapter_error']='status unavailable'
                samples.write(json.dumps(row)+'\n');samples.flush()
                if state.get('phase')=='motion_verified' and not result['injected']:
                    current=serving_pods()
                    if len(current)!=1 or current[0]['metadata']['uid']!=original['metadata']['uid']:raise RuntimeError('server changed before injection')
                    before=time.monotonic_ns()
                    anchor=json.loads(call('exec','semantic-phase5-native','-c','fixture','--','python3','-c',
                        'import time,json; print(json.dumps({"wall_ns":time.time_ns(),"fixture":json.load(open("/tmp/phase5-native-results/semantic-armed-status.json"))}))').stdout)
                    if anchor['fixture'].get('phase')!='motion_verified' or anchor['fixture'].get('armed') is not True:
                        raise RuntimeError('motion ended before injection; no fault injected')
                    event={'event':'delete_serving_pod','at_wall_ns':time.time_ns(),'uid':original['metadata']['uid'],'fixture':anchor['fixture'],
                           'fixture_delete_lower_ns':anchor['wall_ns'],'grace_period_seconds':1}
                    call('delete','pod',original['metadata']['name'],'-n','semantic-model-serving','--grace-period=1','--wait=false')
                    event['fixture_delete_upper_ns']=anchor['wall_ns']+time.monotonic_ns()-before
                    result['events'].append(event);result['injected']=True;save('progress.json',result)
                if result['injected'] and not result['replacement_ready']:
                    replacement=[pod for pod in serving_pods() if ready(pod) and pod['metadata']['uid']!=original['metadata']['uid']]
                    if len(replacement)==1:
                        result['replacement_ready']=True;save('serving-replacement.json',replacement[0])
                        result['events'].append({'event':'replacement_ready','at_wall_ns':time.time_ns(),'uid':replacement[0]['metadata']['uid'],'fixture':state})
                time.sleep(.5)
        evidence_path=trial/'runtime/summary.json'
        evidence=json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
        result['returncode']=run.returncode
        result['fixture_passed']=trial_passed(evidence,run.returncode,'serving')
        result['passed']=result['fixture_passed'] and result['injected'] and result['replacement_ready']
        for container in ['sam3-inference','sam3-zenoh-bridge']:
            (a.output_dir/(container+'.log')).write_text(call('logs',POD,'-c',container,check=False).stdout)
    except Exception as error:
        result['error']=str(error)
    finally:
        if run is not None and run.poll() is None:
            run.terminate()
            try:run.wait(timeout=15)
            except subprocess.TimeoutExpired:run.kill();run.wait()
        cleanup=[]
        if owned:
            for command in [[OC,'-n','semantic-navigation','delete','pod','semantic-phase5-native','--ignore-not-found','--wait=true','--timeout=90s'],[sys.executable,str(ROOT/'scripts/semantic-navigation/g4_topology.py'),'down'],[OC,'-n','semantic-navigation','create','-f',str(a.reservation)],[OC,'-n','semantic-navigation','wait','pod/'+RESERVATION_POD,'--for=condition=Ready','--timeout=120s']]:
                try:
                    r=subprocess.run(command,capture_output=True,text=True,timeout=180);cleanup.append({'command':command,'returncode':r.returncode,'stderr':r.stderr})
                except Exception as error:cleanup.append({'command':command,'returncode':-1,'error':str(error)})
        result['cleanup']=cleanup;result['cleanup_ok']=all(r['returncode']==0 for r in cleanup)
        result['passed']=result['passed'] and result['cleanup_ok'];save('result.json',result)
    print(json.dumps({'passed':result['passed'],'injected':result['injected'],'replacement_ready':result['replacement_ready'],'cleanup_ok':result['cleanup_ok']}))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
