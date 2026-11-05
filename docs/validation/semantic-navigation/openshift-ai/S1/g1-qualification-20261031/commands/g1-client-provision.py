import json,subprocess,tempfile,base64,os
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031');image=json.loads((e.parent/'gate-result.json').read_text())['runtime_image']
def run(*args,**kw):return subprocess.run(args,check=True,capture_output=True,**kw)
def apply(r):return run(oc,'apply','-f','-',input=json.dumps(r).encode())
# Issue a negative-test leaf under the existing issuer; never print key material.
issuer=json.loads(run(oc,'get','secret','sam3-g0-issuer','-n','semantic-model-serving','-o','json').stdout)['data']
with tempfile.TemporaryDirectory(prefix='g1-negative-cert-') as tmp:
 p=Path(tmp)
 for name in ('ca.crt','ca.key'):(p/name).write_bytes(base64.b64decode(issuer[name]));os.chmod(p/name,0o600)
 run('openssl','req','-new','-newkey','rsa:2048','-nodes','-keyout',str(p/'key'),'-out',str(p/'csr'),'-subj','/CN=g1-unbound')
 (p/'ext').write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth\nsubjectAltName=URI:spiffe://semantic-navigation/sa/g1-unbound\n')
 run('openssl','x509','-req','-in',str(p/'csr'),'-CA',str(p/'ca.crt'),'-CAkey',str(p/'ca.key'),'-CAcreateserial','-out',str(p/'cert'),'-days','1','-extfile',str(p/'ext'))
 secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'sam3-g1-unbound-tls','namespace':'semantic-navigation'},'type':'Opaque','data':{k:base64.b64encode((p/v).read_bytes()).decode() for k,v in {'tls.crt':'cert','tls.key':'key'}.items()}};apply(secret)
for name,allowed in [('sam3-g1-client',True),('sam3-g1-denied',False)]:
 r={'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':'semantic-navigation','labels':{'semantic-serving-client':'sam3-mat-v1'} if allowed else {}},'spec':{'serviceAccountName':'sam3-replay','automountServiceAccountToken':False,'restartPolicy':'Never','terminationGracePeriodSeconds':5,'containers':[{'name':'client','image':image,'command':['/opt/sam3-venv/bin/python','-c','import time;time.sleep(21600)'],'resources':{'requests':{'cpu':'100m','memory':'512Mi'},'limits':{'cpu':'2','memory':'2Gi'}},'securityContext':{'allowPrivilegeEscalation':False,'runAsNonRoot':True,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']},'seccompProfile':{'type':'RuntimeDefault'}},'volumeMounts':[{'name':'cert','mountPath':'/cert','readOnly':True},{'name':'unbound','mountPath':'/unbound','readOnly':True},{'name':'tmp','mountPath':'/tmp'}]}],'volumes':[{'name':'cert','secret':{'secretName':'sam3-replay-tls'}},{'name':'unbound','secret':{'secretName':'sam3-g1-unbound-tls'}},{'name':'tmp','emptyDir':{'sizeLimit':'512Mi'}}]}}
 (e/(name+'.json')).write_text(json.dumps(r,indent=2)+'\n');apply(r)
print('Replay client and negative-test client created.')
