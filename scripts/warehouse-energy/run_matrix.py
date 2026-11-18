#!/usr/bin/env python3
"""Run three isolated payload groups; each traversal starts a fresh Gazebo world."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys


def group(payload, root, source):
    results=[]
    for route,direction,repeat in itertools.product(['A','B'],['up','down'],range(1,4)):
        name=f'{route}-{direction}-p{payload:g}-r{repeat}'
        output=root/name
        env=dict(os.environ,GZ_PARTITION=f'warehouse_matrix_payload_{payload:g}')
        command=[sys.executable,str(Path(__file__).with_name('physics_trial.py')),
                 '--source',str(source),'--output',str(output),'--route',route,
                 '--direction',direction,'--payload',str(payload),'--rtf','10']
        run=subprocess.run(command,env=env,capture_output=True,text=True,timeout=240)
        result=json.loads((output/'result.json').read_text()) if (output/'result.json').exists() else {
            'status':'ERROR','errors':[run.stderr[-4000:]]}
        (output/'runner.log').write_text(run.stdout+'\n'+run.stderr)
        results.append({'trial':name,**result})
        print(json.dumps({'trial':name,'status':result['status'],'errors':result.get('errors')}),flush=True)
        if run.returncode or result['status']!='PASS':break
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    with ThreadPoolExecutor(max_workers=3) as pool:
        groups=list(pool.map(lambda payload:group(payload,args.output.resolve(),args.source.resolve()),[0.,.25,.5]))
    rows=[r for g in groups for r in g]
    result={'status':'PASS' if len(rows)==36 and all(r['status']=='PASS' for r in rows) else 'FAIL',
            'expected_trials':36,'completed_trials':len(rows),'trials':rows}
    (args.output/'matrix-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'completed_trials':len(rows)}),flush=True)
    raise SystemExit(result['status']!='PASS')
