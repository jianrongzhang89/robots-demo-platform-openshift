#!/usr/bin/env python3
"""Run the frozen G4 suite, stop on failure, restore the rendering reservation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from g4_topology import ROOT, OC, POD, call
from run_phase6_series import PHASE5_GATES


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--reservation',type=Path,required=True);a=p.parse_args()
    for stage in ('S1','S2','S3'):
        gate=json.loads((ROOT/f'docs/validation/semantic-navigation/openshift-ai/{stage}/gate-result.json').read_text())
        if not gate.get('accepted') or gate.get('status')!='PASS':raise RuntimeError(f'{stage} must be signed off')
    a.output_dir.mkdir(parents=True,exist_ok=False)
    stages=[('serving-faults',['run_g4_faults.py','--modes','auth','wrong_version','overload','serving','network','hang']),
            ('observation',['run_g4_phase5.py','--gate','observation']),
            ('recovery',['run_g4_phase5.py','--gate','recovery']),
            ('moving-stop',['run_g4_phase5.py','--gate','stop']),
            ('semantic-faults',['run_g4_faults.py','--modes','camera_path_loss','tf_loss','hung_inference','process_loss','transport_loss'])]
    write(a.output_dir/'plan.json',{'stages':stages,'nominal_pairs':20,'negative_pairs_each':3,'stop_policy':'first armed failure, injected-fault failure, or exhausted pre-arm liveness ladder stops the suite','camera_update_hz':30,'physics_step_s':0.002,'accepted_g3':True})
    results=[];passed=False
    try:
        for name,parts in stages:
            cmd=[sys.executable,str(ROOT/'scripts/semantic-navigation'/parts[0]),*parts[1:],'--output-dir',str(a.output_dir/name)]
            with (a.output_dir/(name+'.log')).open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
            path=a.output_dir/name/'summary.json';data=json.loads(path.read_text()) if path.exists() else {}
            result={'stage':name,'passed':r.returncode==0 and data.get('passed') is True,'returncode':r.returncode,'evidence':str(path)};results.append(result)
            write(a.output_dir/'progress.json',{'stages':results});print(json.dumps(result),flush=True)
            if not result['passed']:raise RuntimeError(name+' failed; suite stopped')
        entry=a.output_dir/'served-phase5-qualification.json'
        write(entry,{'passed':True,'accepted_gates':list(PHASE5_GATES),'reviewer':'automated technical qualification; G4 user acceptance remains pending','stages':results})
        series=a.output_dir/'paired-series'
        cmd=[sys.executable,str(ROOT/'scripts/semantic-navigation/run_phase6_series.py'),
             '--output-dir',str(series),'--serving-backend','http','--pairs','20','--negative-pairs','3',
             '--hull-radius','0.246','--region-xmin','16.9514','--region-xmax','17.8514',
             '--region-ymin','-31.919','--region-ymax','-31.269','--gpu-rendering',
             '--phase5-evidence',str(entry),'--reserved-window-note','User authorized G4 after G3 sign-off; private A10G rendering reservation handed to G4 fixture.',
             '--trial-command',sys.executable,str(ROOT/'scripts/semantic-navigation/phase6_trial.py'),'{arm}','{case}','{trial}','{output}']
        with (a.output_dir/'paired-series.log').open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
        path=series/'series-result.json';data=json.loads(path.read_text()) if path.exists() else {}
        trials=data.get('trials',[])
        complete=all(sum(t.get('arm')==arm and t.get('case')==case and t.get('completed') is True and t.get('collision') is False for t in trials)>=count for arm in ('off','on') for case,count in [('nominal',20),('target_absent',3),('target_removal',3),('perception_failure',3)])
        result={'stage':'paired-series','passed':r.returncode==0 and data.get('passed') is True and complete,'evidence':str(path)};results.append(result)
        if not result['passed']:raise RuntimeError('paired series failed')
        passed=True
    finally:
        cleanup=[]
        r=subprocess.run([sys.executable,str(ROOT/'scripts/semantic-navigation/g4_topology.py'),'down'],capture_output=True,text=True)
        cleanup.append({'action':'remove G4 topology','returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
        r=call('delete','secret','semantic-g4-proxy-tls','--ignore-not-found',check=False)
        cleanup.append({'action':'remove fault injector certificate','returncode':r.returncode})
        r=call('create','-f',str(a.reservation),check=False)
        cleanup.append({'action':'restore rendering reservation','returncode':r.returncode,'stderr':r.stderr})
        r=call('wait','pod/sam3-g0-rendering-reservation','--for=condition=Ready','--timeout=120s',check=False)
        cleanup.append({'action':'reservation Ready','returncode':r.returncode})
        write(a.output_dir/'cleanup.json',cleanup)
        write(a.output_dir/'result.json',{'gate':'G4','status':'PASS' if passed and all(x['returncode']==0 for x in cleanup) else 'HOLD','accepted':False,'stages':results,'cleanup':cleanup})

if __name__=='__main__':main()
