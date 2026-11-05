import subprocess,json
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S0/g0-completion-20261030')
def run(args):return subprocess.run([oc,*args],capture_output=True,text=True)
server=json.loads(run(['-n','semantic-model-serving','get','pod','sam3-g0-transport','-o','json']).stdout)['status']['podIP']
api=run(['-n','default','get','service','kubernetes','-o','jsonpath={.spec.clusterIP}']).stdout
results={}
for name,ns,pod,host,port,expected in [('allowed_ingress','semantic-navigation','sam3-g0-client',server,8443,True),('denied_ingress','semantic-navigation','sam3-g0-denied',server,8443,False),('egress_control','semantic-navigation','sam3-g0-client',api,443,True),('denied_egress','semantic-model-serving','sam3-g0-transport',api,443,False)]:
 code=f'import socket,json,time; t=time.monotonic()\ntry:\n s=socket.create_connection(({host!r},{port}),timeout=4);s.close();r={{"connected":True}}\nexcept OSError as e:r={{"connected":False,"error":str(e)}}\nr["seconds"]=round(time.monotonic()-t,2);print(json.dumps(r))'
 result=run(['-n',ns,'exec',pod,'--','/opt/sam3-venv/bin/python','-c',code]);assert result.returncode==0,result.stderr
 results[name]=json.loads(result.stdout);results[name]['passed']=results[name]['connected']==expected
for name,sa,ns,verb,resource in [('serving_cannot_read_robotics_secrets','system:serviceaccount:semantic-model-serving:sam3-serving','semantic-navigation','get','secrets'),('replay_cannot_read_serving_secrets','system:serviceaccount:semantic-navigation:sam3-replay','semantic-model-serving','get','secrets'),('serving_can_pull_image','system:serviceaccount:semantic-model-serving:sam3-serving','semantic-navigation','get','imagestreams/layers')]:
 result=run(['auth','can-i',verb,'imagestreams.image.openshift.io' if name=='serving_can_pull_image' else resource,'--as='+sa,'-n',ns]+(['--subresource=layers'] if name=='serving_can_pull_image' else []));results[name]={'answer':result.stdout.strip(),'passed':result.stdout.strip()==('yes' if name=='serving_can_pull_image' else 'no')}
results['passed']=all(x['passed'] for x in results.values());(e/'network-rbac-results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2));assert results['passed']
