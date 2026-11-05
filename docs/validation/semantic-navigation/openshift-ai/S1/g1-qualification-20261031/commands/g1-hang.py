import json,subprocess,time,sys
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031');out=e/'process-hang-1';out.mkdir()
def run(ns,*args,check=True,**kw):return subprocess.run([oc,'-n',ns,*args],capture_output=True,check=check,**kw)
r=json.loads(run('semantic-model-serving','get','pods','-l','serving.kserve.io/inferenceservice=sam3-mat-v1','-o','json').stdout)['items'][0];name=r['metadata']['name'];before=next(c for c in r['status']['containerStatuses'] if c['name']=='kserve-container');(out/'before-pod.json').write_text(json.dumps(r,indent=2))
cmd='import os,signal,json,time; before=open("/proc/1/status").read().splitlines()[2];os.kill(1,signal.SIGSTOP);time.sleep(.2);print(json.dumps({"before":before,"after":[s for s in open("/proc/1/status").read().splitlines() if s.startswith("State:")][0]}))'
result=run('semantic-model-serving','exec',name,'-c','kserve-container','--','/opt/sam3-venv/bin/python','-c',cmd,check=False);(out/'injection.stdout').write_bytes(result.stdout);(out/'injection.stderr').write_bytes(result.stderr)
print(result.stdout.decode(),flush=True)
if result.returncode or 'T (stopped)' not in result.stdout.decode():
 (out/'result.json').write_text(json.dumps({'status':'INJECTION_NOT_APPLIED','reason':'PID namespace init did not stop; no hang result claimed'},indent=2));sys.exit(2)
start=time.monotonic();samples=[]
while time.monotonic()-start<180:
 r=json.loads(run('semantic-model-serving','get','pod',name,'-o','json').stdout);c=next(c for c in r['status']['containerStatuses'] if c['name']=='kserve-container');samples.append({'seconds':round(time.monotonic()-start,2),'ready':c['ready'],'restart_count':c['restartCount'],'state':c['state']})
 if c['restartCount']>before['restartCount'] and c['ready']:break
 time.sleep(1)
else:raise RuntimeError('hung process did not recover within 180 seconds')
(out/'after-pod.json').write_text(json.dumps(r,indent=2));(out/'events.json').write_bytes(run('semantic-model-serving','get','events','--field-selector','involvedObject.name='+name,'-o','json').stdout)
result={'passed':any(not s['ready'] for s in samples) and c['restartCount']==before['restartCount']+1,'recovery_seconds':samples[-1]['seconds'],'samples':samples,'scope':'Whole model-server process stopped with SIGSTOP; kubelet liveness restarts it. Worker-only stall timeout is separately unit-tested.'};(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'recovery_seconds':result['recovery_seconds']}));assert result['passed']
