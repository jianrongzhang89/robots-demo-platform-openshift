#!/usr/bin/env python3
"""Issue a read-only metrics principal and configure its narrowly scoped scrape.

Run after G5 rotation, with the isolated replay client present. Restarts the
baseline serving pod to load the added principal. No inference permission added.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
NS = 'semantic-model-serving'
PRINCIPAL = 'spiffe://semantic-model-serving/sa/g5-monitor'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {'recorded_at':datetime.now(timezone.utc).isoformat(),'status':'FAIL','principal':PRINCIPAL}
    def run(*cmd, data=None):
        r = subprocess.run(cmd,input=data,capture_output=True,timeout=60)
        if r.returncode:
            raise RuntimeError(f'{cmd[0]} failed (exit {r.returncode})')
        return r.stdout
    def oc(*cmd, data=None):
        return run('oc','--request-timeout=30s',*cmd,data=data)
    def client(code,data=None):
        return oc('exec','-i','-n','semantic-navigation','sam3-g5-client','--','/opt/sam3-venv/bin/python','-c',code,data=data)
    def pod():
        rows=json.loads(oc('get','pods','-n',NS,'-l','serving.kserve.io/inferenceservice=sam3-mat-v1','-o','json'))['items']
        return rows[0] if len(rows)==1 else None
    try:
        clients=json.loads(oc('get','pods','-n','semantic-navigation','-l','semantic-serving-client=sam3-mat-v1','-o','json'))['items']
        if [r['metadata']['name'] for r in clients] != ['sam3-g5-client']:
            raise ValueError('only stopped G5 replay client may be present')
        issuer=json.loads(oc('get','secret','sam3-g0-issuer','-n',NS,'-o','json'))['data']
        policy=json.loads(oc('get','configmap','sam3-client-policy','-n',NS,'-o','json'))
        bindings=json.loads(policy['data']['clients.json']); bindings[PRINCIPAL]=[]
        with tempfile.TemporaryDirectory(prefix='g5-monitor-') as directory:
            root=Path(directory); os.chmod(root,0o700)
            for key in ['ca.crt','ca.key']:
                (root/key).write_bytes(base64.b64decode(issuer[key])); os.chmod(root/key,0o600)
            run('openssl','req','-new','-newkey','rsa:2048','-nodes','-keyout',str(root/'tls.key'),'-out',str(root/'csr'),'-subj','/CN=sam3-g5-monitor')
            (root/'ext').write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth\nsubjectAltName=URI:'+PRINCIPAL+'\n')
            run('openssl','x509','-req','-in',str(root/'csr'),'-CA',str(root/'ca.crt'),'-CAkey',str(root/'ca.key'),'-CAcreateserial','-out',str(root/'tls.crt'),'-days','7','-extfile',str(root/'ext'))
            report['certificate']=run('openssl','x509','-in',str(root/'tls.crt'),'-noout','-dates','-fingerprint','-sha256').decode()
            material={key:base64.b64encode((root/key).read_bytes()).decode() for key in ['ca.crt','tls.crt','tls.key']}
            secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'sam3-g5-monitor-tls','namespace':NS},'type':'Opaque','data':material}
            oc('apply','-f','-',data=json.dumps(secret).encode())
            oc('patch','configmap','sam3-client-policy','-n',NS,'--type=merge','-p',json.dumps({'data':{'clients.json':json.dumps(bindings)}}))
            old=pod()
            if old is None: raise ValueError('exactly one baseline pod required')
            report['previous_pod_uid']=old['metadata']['uid']
            oc('delete','pod',old['metadata']['name'],'-n',NS,'--wait=true','--timeout=45s')
            end=time.monotonic()+600
            while time.monotonic()<end:
                current=pod()
                if current and current['metadata']['uid']!=old['metadata']['uid'] and any(c['type']=='Ready' and c['status']=='True' for c in current.get('status',{}).get('conditions',[])):break
                time.sleep(3)
            else:raise TimeoutError('monitor policy reload did not become Ready')
            report['replacement_pod_uid']=current['metadata']['uid']
            client('import sys,json,base64,pathlib,os; d=json.load(sys.stdin); p=pathlib.Path("/tmp/g5-monitor"); p.mkdir(mode=0o700); [((p/k).write_bytes(base64.b64decode(v)),os.chmod(p/k,0o600)) for k,v in d.items()]',data=json.dumps(material).encode())
            code='''import ssl,json,urllib.request,urllib.error
c=ssl.create_default_context(cafile="/tmp/g5-monitor/ca.crt");c.load_cert_chain("/tmp/g5-monitor/tls.crt","/tmp/g5-monitor/tls.key")
u="https://sam3-mat-v1-tls.semantic-model-serving.svc:8443"
metadata=json.load(urllib.request.urlopen(u+"/v1/models/sam3-mat-v1",context=c,timeout=5))
metrics=urllib.request.urlopen(u+"/metrics",context=c,timeout=5).read().decode()
try:
 r=urllib.request.urlopen(urllib.request.Request(u+"/v1/models/sam3-mat-v1:predict",data=open("/tmp/frozen/000-request.json","rb").read(),headers={"Content-Type":"application/json"}),context=c,timeout=5); code=r.status
except urllib.error.HTTPError as e: code=e.code
print(json.dumps({"metadata":metadata,"metrics":metrics,"inference_http_status":code}))
'''
            report['authorization']=json.loads(client(code))
            expected=json.loads((ROOT/'docs/validation/semantic-navigation/openshift-ai/S2/gate-result.json').read_text())['deployment_identity']
            if report['authorization']['inference_http_status']!=403 or report['authorization']['metadata']['deployment']!=expected:
                raise ValueError('monitor permissions or baseline identity failed')
        oc('label','service','sam3-mat-v1-tls','-n',NS,'semantic-g5-monitor=sam3','--overwrite')
        rendered=run('python3',str(ROOT/'helm/semantic-navigation/openshift-ai/render_g5_monitoring.py'))
        (args.output_dir/'manifests.json').write_bytes(rendered)
        oc('apply','--dry-run=server','-f','-',data=rendered)
        report['apply']=oc('apply','-f','-',data=rendered).decode()
        report['status']='PASS'
    except Exception as error:
        report['error']=str(error);raise
    finally:
        try: client('import shutil;shutil.rmtree("/tmp/g5-monitor",ignore_errors=True)')
        finally:(args.output_dir/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'inference_http_status':report['authorization']['inference_http_status']}))


if __name__=='__main__':main()
