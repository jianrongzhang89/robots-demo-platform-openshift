import json,subprocess,time,re
from pathlib import Path
oc='/Users/zhangj/bin/oc';e=Path('docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031');out=e/'process-hang-2';out.mkdir()
def run(ns,*args,check=True,**kw):return subprocess.run([oc,'-n',ns,*args],capture_output=True,check=check,**kw)
r=json.loads(run('semantic-model-serving','get','pods','-l','serving.kserve.io/inferenceservice=sam3-mat-v1','-o','json').stdout)['items'][0];name=r['metadata']['name'];before=next(c for c in r['status']['containerStatuses'] if c['name']=='kserve-container');cid=before['containerID'].removeprefix('cri-o://');assert re.fullmatch('[a-f0-9]{64}',cid);(out/'before-pod.json').write_text(json.dumps(r,indent=2))
# Namespace init ignores local SIGSTOP. Target only this exact container from
# the parent PID namespace; validate process identity and cgroup before stopping.
command='''set -euo pipefail
record=$(crictl inspect "$1")
test "$(printf '%s' "$record" | jq -r '.status.metadata.name')" = kserve-container
test "$(printf '%s' "$record" | jq -r '.status.state')" = CONTAINER_RUNNING
pid=$(printf '%s' "$record" | jq -r '.info.pid')
test "$pid" -gt 1
grep -qF "$1" /proc/"$pid"/cgroup
tr '\\0' ' ' < /proc/"$pid"/cmdline | grep -qF /app/server.py
kill -STOP "$pid"
printf 'target_pid=%s\\n' "$pid"
grep '^State:' /proc/"$pid"/status
'''
(out/'injection-command.sh').write_text(command)
start=time.monotonic();result=subprocess.run([oc,'debug','node/'+r['spec']['nodeName'],'--','chroot','/host','/bin/bash','-c',command,'g1-hang',cid],capture_output=True,timeout=120)
(out/'injection.stdout').write_bytes(result.stdout);(out/'injection.stderr').write_bytes(result.stderr);print(result.stdout.decode(),flush=True);print('debug command exit',result.returncode,flush=True)
assert result.returncode==0 and b'T (stopped)' in result.stdout,'host injection did not confirm stopped state'
samples=[];passed=False
try:
 while time.monotonic()-start<180:
  r=json.loads(run('semantic-model-serving','get','pod',name,'-o','json').stdout);c=next(c for c in r['status']['containerStatuses'] if c['name']=='kserve-container');samples.append({'seconds':round(time.monotonic()-start,2),'ready':c['ready'],'restart_count':c['restartCount'],'state':c['state']})
  if c['restartCount']>before['restartCount'] and c['ready']:
   passed=any(not s['ready'] for s in samples) and c['restartCount']==before['restartCount']+1;break
  time.sleep(1)
finally:
 (out/'after-pod.json').write_text(json.dumps(r,indent=2));(out/'events.json').write_bytes(run('semantic-model-serving','get','events','--field-selector','involvedObject.name='+name,'-o','json').stdout)
 report={'passed':passed,'recovery_seconds':samples[-1]['seconds'] if samples else None,'samples':samples,'scope':'Whole model-server process stopped by exact CRI container ID from parent PID namespace; kubelet liveness recovery. Worker-only stall threshold separately unit-tested.'};(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
 if not passed:run('semantic-model-serving','delete','pod',name,'--wait=true','--timeout=90s',check=False)
print(json.dumps({'passed':passed,'recovery_seconds':report['recovery_seconds']}));assert passed
