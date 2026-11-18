#!/usr/bin/env python3
"""Run fresh full-stack route trials sequentially, preserving every attempt."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--cases',nargs='+',default=['A:up','A:down','B:up','B:down']);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);results=[]
    for case in args.cases:
        route,direction=case.split(':');output=args.output/f'{route}-{direction}'
        command=[sys.executable,str(Path(__file__).with_name('run_navigation.py')),
            '--source',str(args.source),'--fixture',str(args.fixture),'--output',str(output),
            '--route',route,'--direction',direction]
        with (args.output/f'{route}-{direction}-runner.log').open('w') as log:
            child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            for line in child.stdout:
                log.write(line);log.flush();print(line,end='',flush=True)
            code=child.wait()
        result=json.loads((output/'result.json').read_text()) if (output/'result.json').exists() else {'status':'ERROR'}
        results.append({'case':case,'exit_code':code,'status':result['status'],'task_id':result.get('task_id')})
        (args.output/'series-result.json').write_text(json.dumps(results,indent=2)+'\n')
        if code:raise SystemExit(code)
