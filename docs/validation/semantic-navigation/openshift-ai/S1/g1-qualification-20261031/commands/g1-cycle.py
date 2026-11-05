import json,subprocess,time,sys
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031');n=sys.argv[1];out=e/f'cold-start-{n}';out.mkdir()
def run(ns,*args,check=True,**kw):return subprocess.run([oc,'-n',ns,*args],check=check,capture_output=True,**kw)
def pod():
 ps=json.loads(run('semantic-model-serving','get','pods','-l','serving.kserve.io/inferenceservice=sam3-mat-v1','-o','json').stdout)['items'];ps=[p for p in ps if not p['metadata'].get('deletionTimestamp')];return ps[0] if ps else None
start=time.time()
if n=='1':
 run('semantic-model-serving','delete','pod','sam3-g0-reservation','--wait=true','--timeout=60s')
 result=run('semantic-model-serving','apply','-f','docs/validation/semantic-navigation/openshift-ai/S0/g0-completion-20261030/rendered-candidate.json');(out/'apply.txt').write_bytes(result.stdout+result.stderr)
else:
 old=pod();(out/'previous-pod.json').write_text(json.dumps(old,indent=2));run('semantic-model-serving','delete','pod',old['metadata']['name'],'--wait=true','--timeout=90s')
while time.time()-start<180:
 p=pod()
 if p and p.get('status',{}).get('podIP'):break
 time.sleep(.5)
else:raise RuntimeError('no scheduled Pod IP')
(out/'initial-pod.json').write_text(json.dumps(p,indent=2));(out/'start.json').write_text(json.dumps({'wall_seconds':start,'uid':p['metadata']['uid'],'pod':p['metadata']['name'],'pod_ip':p['status']['podIP']},indent=2))
result=run('semantic-navigation','exec','-i','sam3-g1-client','--','/opt/sam3-venv/bin/python','-',p['status']['podIP'],input=Path('/private/tmp/g1-cold-client.py').read_bytes(),check=False)
(out/'readiness.json').write_bytes(result.stdout);(out/'readiness-stderr.txt').write_bytes(result.stderr)
run('semantic-model-serving','wait','pod/'+p['metadata']['name'],'--for=condition=Ready','--timeout=180s')
final=json.loads(run('semantic-model-serving','get','pod',p['metadata']['name'],'-o','json').stdout);(out/'final-pod.json').write_text(json.dumps(final,indent=2));(out/'server.log').write_bytes(run('semantic-model-serving','logs',p['metadata']['name'],'-c','kserve-container').stdout)
(out/'isvc.json').write_bytes(run('semantic-model-serving','get','isvc','sam3-mat-v1','-o','json').stdout)
r=json.loads(result.stdout);assert result.returncode==0 and r['passed'],r
print(json.dumps({'cycle':n,'passed':r['passed'],'first_ready_seconds':r['first_ready_seconds'],'pod':p['metadata']['name']}))
