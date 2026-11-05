import json,subprocess,tempfile,os
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S0/g0-completion-20261030')
def run(args,**kw):return subprocess.run(args,check=True,capture_output=True,**kw)
def apply(obj):return run([oc,'apply','-f','-'],input=json.dumps(obj).encode())
with tempfile.TemporaryDirectory(prefix='sam3-g0-credentials-') as tmp:
 p=Path(tmp);os.chmod(p,0o700)
 run(['openssl','req','-x509','-newkey','rsa:3072','-nodes','-keyout',str(p/'ca.key'),'-out',str(p/'ca.crt'),'-days','90','-subj','/CN=semantic-serving-G0-issuer','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign'])
 details={}
 for name,san,usage in [('server','DNS:sam3-mat-v1-tls.semantic-model-serving.svc,DNS:sam3-mat-v1-tls.semantic-model-serving.svc.cluster.local','serverAuth'),('client','URI:spiffe://semantic-navigation/sa/sam3-replay','clientAuth'),('unbound','URI:spiffe://semantic-navigation/sa/unbound','clientAuth')]:
  run(['openssl','req','-new','-newkey','rsa:2048','-nodes','-keyout',str(p/f'{name}.key'),'-out',str(p/f'{name}.csr'),'-subj',f'/CN=sam3-{name}'])
  (p/'ext').write_text(f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage={usage}\nsubjectAltName={san}\n')
  run(['openssl','x509','-req','-in',str(p/f'{name}.csr'),'-CA',str(p/'ca.crt'),'-CAkey',str(p/'ca.key'),'-CAcreateserial','-out',str(p/f'{name}.crt'),'-days','7','-extfile',str(p/'ext')])
  details[name]=run(['openssl','x509','-in',str(p/f'{name}.crt'),'-noout','-dates','-fingerprint','-sha256','-ext','subjectAltName']).stdout.decode()
 def secret(ns,name,files):
  args=[oc,'-n',ns,'create','secret','generic',name]+[f'--from-file={key}={p/value}' for key,value in files.items()]+['--dry-run=client','-o','json']
  payload=run(args).stdout;run([oc,'apply','-f','-'],input=payload)
 secret('semantic-model-serving','sam3-g0-issuer',{'ca.crt':'ca.crt','ca.key':'ca.key'})
 secret('semantic-model-serving','sam3-serving-tls',{'tls.crt':'server.crt','tls.key':'server.key','client-ca.crt':'ca.crt'})
 secret('semantic-navigation','sam3-replay-tls',{'tls.crt':'client.crt','tls.key':'client.key','ca.crt':'ca.crt'})
 secret('semantic-navigation','sam3-g0-unbound-tls',{'tls.crt':'unbound.crt','tls.key':'unbound.key','ca.crt':'ca.crt'})
 (e/'certificate-metadata.json').write_text(json.dumps(details,indent=2)+'\n')
apply({'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':'sam3-replay','namespace':'semantic-navigation'},'automountServiceAccountToken':False})
r=json.loads((e/'rendered-candidate.json').read_text());runtime=next(x for x in r['items'] if x['kind']=='ServingRuntime')['spec'];c=runtime['containers'][0];c['name']='transport';c['resources']={'requests':{'cpu':'100m','memory':'512Mi'},'limits':{'cpu':'1','memory':'2Gi'}}
for k in ['startupProbe','readinessProbe','livenessProbe']:c.pop(k)
c['command']=['/opt/sam3-venv/bin/python','-u','-c'];c['args']=['import ssl,json; from pathlib import Path; from server import ModelService,BoundedServer; s=ModelService(json.loads(Path("/policy/clients.json").read_text())); t=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); t.minimum_version=ssl.TLSVersion.TLSv1_2; t.verify_mode=ssl.CERT_REQUIRED; t.load_cert_chain("/tls/tls.crt","/tls/tls.key"); t.load_verify_locations("/tls/client-ca.crt"); print("G0 transport-only probe; no model loaded",flush=True); BoundedServer(("0.0.0.0",8443),s,tls=t).serve_forever()']
c['volumeMounts']=[x for x in c['volumeMounts'] if x['name']!='model']
server={'apiVersion':'v1','kind':'Pod','metadata':{'name':'sam3-g0-transport','namespace':'semantic-model-serving','labels':{'serving.kserve.io/inferenceservice':'sam3-mat-v1','component':'predictor'}},'spec':{'serviceAccountName':'sam3-serving','automountServiceAccountToken':False,'restartPolicy':'Never','containers':[c],'volumes':[x for x in runtime['volumes'] if x['name']!='model']}}
(e/'transport-probe-pod.json').write_text(json.dumps(server,indent=2)+'\n');apply(server)
for name,allowed in [('sam3-g0-client',True),('sam3-g0-denied',False)]:
 client={'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':'semantic-navigation','labels':{'semantic-serving-client':'sam3-mat-v1'} if allowed else {}},'spec':{'serviceAccountName':'sam3-replay','automountServiceAccountToken':False,'restartPolicy':'Never','containers':[{'name':'client','image':c['image'],'command':['/opt/sam3-venv/bin/python','-c','import time;time.sleep(3600)'],'resources':{'requests':{'cpu':'50m','memory':'256Mi'},'limits':{'cpu':'1','memory':'1Gi'}},'securityContext':c['securityContext'],'volumeMounts':[{'name':'cert','mountPath':'/cert','readOnly':True},{'name':'unbound','mountPath':'/unbound','readOnly':True}]}],'volumes':[{'name':'cert','secret':{'secretName':'sam3-replay-tls'}},{'name':'unbound','secret':{'secretName':'sam3-g0-unbound-tls'}}]}}
 apply(client)
print('Credentials and transport test pods provisioned (no private material in evidence).')
