import subprocess,sys,json
from pathlib import Path
n=sys.argv[1];oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031');name=f'parity-{n}.json'
result=subprocess.run([oc,'-n','semantic-navigation','exec','sam3-g1-client','--','/opt/sam3-venv/bin/python','/tmp/g1/scripts/semantic-navigation/replay_serving_parity.py','--manifest','/tmp/frozen/manifest.json','--identity','/tmp/expected-identity.json','--ca','/cert/ca.crt','--cert','/cert/tls.crt','--key','/cert/tls.key','--endpoint','https://sam3-mat-v1-tls.semantic-model-serving.svc:8443','--output','/tmp/'+name],capture_output=True,text=True)
(e/f'parity-{n}.log').write_text(result.stdout+result.stderr);subprocess.run([oc,'-n','semantic-navigation','cp','sam3-g1-client:/tmp/'+name,str(e/name)],check=True);print(json.dumps({'attempt':n,'status':json.loads((e/name).read_text())['status']}));sys.exit(result.returncode)
