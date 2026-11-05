import subprocess,json,time
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S0/g0-completion-20261030');start=time.time()
expected='9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e'
read=[oc,'-n','semantic-navigation','exec','semantic-phase5-sam3','-c','sam3-inference','--','cat','/models/sam3.pt']
write=[oc,'-n','semantic-model-serving','exec','-i','sam3-g0-reservation','--','/opt/sam3-venv/bin/python','-c','import sys,hashlib,os; p="/models/sam3.pt.partial"; h=hashlib.sha256(); n=0\nwith open(p,"wb") as f:\n while True:\n  b=sys.stdin.buffer.read(1024*1024)\n  if not b:break\n  f.write(b);h.update(b);n+=len(b)\nassert h.hexdigest()=="'+expected+'",h.hexdigest()\nos.chmod(p,0o444);os.replace(p,"/models/sam3.pt");print(h.hexdigest(),n)']
with open(e/'checkpoint-copy-source.log','w') as log:
 source=subprocess.Popen(read,stdout=subprocess.PIPE,stderr=log);target=subprocess.run(write,stdin=source.stdout,capture_output=True,text=True);source.stdout.close();rc=source.wait()
result={'source_returncode':rc,'destination_returncode':target.returncode,'destination_checksum_and_bytes':target.stdout.strip(),'stderr':target.stderr,'seconds':round(time.time()-start,2),'source':'semantic-navigation/sam3-checkpoint','destination':'semantic-model-serving/sam3-checkpoint'}
(e/'checkpoint-copy.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));assert rc==0 and target.returncode==0
