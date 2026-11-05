import json,subprocess,time
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031')
def run(ns,*args):return subprocess.run([oc,'-n',ns,*args],capture_output=True,text=True)
r=json.loads(run('semantic-model-serving','get','pods','-l','serving.kserve.io/inferenceservice=sam3-mat-v1','-o','json').stdout)['items'][0];server=r['status']['podIP'];name=r['metadata']['name'];api=run('default','get','service','kubernetes','-o','jsonpath={.spec.clusterIP}').stdout
results={}
for case,ns,pod,host,port,expected in [('allowed_data_ingress','semantic-navigation','sam3-g1-client',server,8443,True),('unlabeled_ingress_denied','semantic-navigation','sam3-g1-denied',server,8443,False),('health_port_denied','semantic-navigation','sam3-g1-client',server,8080,False),('agent_port_denied','semantic-navigation','sam3-g1-client',server,9081,False),('egress_control','semantic-navigation','sam3-g1-client',api,443,True),('inference_egress_denied','semantic-model-serving',name,api,443,False)]:
 code=f'import socket,json,time;t=time.monotonic()\ntry:\n s=socket.create_connection(({host!r},{port}),timeout=4);s.close();r={{"connected":True}}\nexcept OSError as ex:r={{"connected":False,"error":str(ex)}}\nr["seconds"]=round(time.monotonic()-t,2);print(json.dumps(r))'
 cmd=['exec',pod]+(['-c','kserve-container'] if ns=='semantic-model-serving' else [])+['--','/opt/sam3-venv/bin/python','-c',code];result=run(ns,*cmd);assert result.returncode==0,result.stderr;results[case]=json.loads(result.stdout);results[case]['passed']=results[case]['connected']==expected
results['no_api_token_mount']={'passed':r['spec'].get('automountServiceAccountToken') is False and all(not v.get('projected') for v in r['spec'].get('volumes',[]))}
public=json.loads(run('semantic-model-serving','get','routes,ingresses','-o','json').stdout);results['no_public_endpoint']={'passed':not public['items']}
results['passed']=all(v['passed'] for v in results.values());(e/'network-results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2));assert results['passed']
