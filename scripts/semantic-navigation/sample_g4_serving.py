#!/usr/bin/env python3
"""Read-only G4 serving/GPU resource samples, bounded to eight hours."""
import argparse
import json
from pathlib import Path
import subprocess
import time
p=argparse.ArgumentParser();p.add_argument('--oc',default='oc');p.add_argument('--output',type=Path,required=True);p.add_argument('--stop-file',type=Path,required=True);a=p.parse_args()
def call(*args):
    r=subprocess.run([a.oc,*args],text=True,capture_output=True,timeout=15)
    return {'stdout':r.stdout,'stderr':r.stderr,'returncode':r.returncode}
start=time.monotonic()
with a.output.open('x') as handle:
    while time.monotonic()-start<28800 and not a.stop_file.exists():
        row={'wall_ns':time.time_ns(),'elapsed_s':time.monotonic()-start}
        try:
            pods=json.loads(call('get','pods','-n','semantic-model-serving','-l','serving.kserve.io/inferenceservice=sam3-mat-v1','-o','json')['stdout'])['items']
            pod=next(p['metadata']['name'] for p in pods if p['status']['phase']=='Running')
            row['pod']=pod
            live=next(p for p in pods if p['metadata']['name']==pod)
            row['pod_uid']=live['metadata']['uid']
            row['restarts']={c['name']:c['restartCount'] for c in live['status'].get('containerStatuses',[])}
            row['gpu']=call('exec','-n','semantic-model-serving',pod,'-c','kserve-container','--','nvidia-smi','--query-gpu=name,utilization.gpu,memory.used,memory.total','--format=csv,noheader,nounits')
            row['metrics']=call('exec','-n','semantic-navigation','semantic-g4-sam3','-c','sam3-inference','--','python3','-c','import urllib.request,ssl; c=ssl.create_default_context(cafile="/cert/ca.crt"); c.load_cert_chain("/cert/tls.crt","/cert/tls.key"); print(urllib.request.urlopen("https://sam3-mat-v1-tls.semantic-model-serving.svc:8443/metrics",context=c,timeout=2).read().decode())')
            row['cpu_memory']=call('adm','top','pods','-n','semantic-model-serving','--containers')
        except Exception as e:row['error']=repr(e)
        handle.write(json.dumps(row)+'\n');handle.flush()
        for _ in range(60):
            if a.stop_file.exists():break
            time.sleep(1)
