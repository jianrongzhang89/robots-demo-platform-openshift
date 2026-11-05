import json,os,subprocess,time
from pathlib import Path
root=Path.cwd(); evidence=root/'docs/validation/semantic-navigation/openshift-ai/S3/g3-qualification-20261031'
deadline=time.monotonic()+900
while not (evidence/'run-1/evaluation.json').exists():
    if time.monotonic()>deadline:raise TimeoutError('run-1 result unavailable')
    time.sleep(2)
for index in (2,3):
    previous=json.loads((evidence/f'run-{index-1}/evaluation.json').read_text())
    if previous['status']!='PASS':raise RuntimeError(f'run-{index-1} did not pass; no next run started')
    command=['python3',str(root/'scripts/semantic-navigation/run_g3_timing.py'),'--oc','/Users/zhangj/bin/oc','--resources',str(evidence/'resources-final.json'),'--output-dir',str(evidence/f'run-{index}'),'--moving']
    print(json.dumps({'event':'starting_run','index':index,'command':command}),flush=True)
    env=os.environ.copy();env['PATH']='/Users/zhangj/bin:'+env['PATH']
    with (evidence/f'run-{index}.log').open('w') as output:
        result=subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,env=env)
    if result.returncode:raise RuntimeError(f'run-{index} failed; evidence retained')
print('All three independent measurements passed.',flush=True)
