#!/usr/bin/env python3
"""Repeat original Phase 5 gates with real served perception in the fixture."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from g4_topology import ROOT, OC, POD, call
from phase6_trial import IMAGE, NODE
from run_g4_faults import configure
from g4_prearm import POLICY, retryable, retain_attempt, sam3_readiness_death, settle_before_retry
from run_phase5_baseline import trial_passed as recovery_passed
from run_phase5_sam3_series import trial_passed as observation_passed
from run_phase5_fault_matrix import trial_passed as fault_passed, FAULT_STOP_MODES


def collect_adapter_evidence(directory):
    """The G4 adapter pod's own logs and final status: without them a
    zenoh route-binding failure on the adapter side leaves no evidence
    (qualification-8 observation trial-03)."""
    for container in ('sam3-inference','sam3-zenoh-bridge'):
        (directory/('adapter-'+container+'.log')).write_text(
            call('logs',POD,'-c',container,check=False).stdout)
    snapshot=call('exec',POD,'-c','sam3-inference','--','cat','/tmp/semantic-status.json',check=False)
    (directory/'adapter-status-final.json').write_text(snapshot.stdout)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--gate',choices=('observation','recovery','stop'),required=True);p.add_argument('--repetitions',type=int)
    a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=False)
    n=a.repetitions or (2 if a.gate=='stop' else 10)
    modes=FAULT_STOP_MODES if a.gate=='stop' else (a.gate,)
    files=list((ROOT/'apps/semantic-safety').glob('*.py'))+list((ROOT/'scripts/semantic-navigation').glob('*g4*.py'))+[ROOT/'scripts/semantic-navigation/run_phase5_native.py',ROOT/'helm/semantic-navigation/phase5-nav2-candidate.yaml']
    hashes=lambda:{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files};frozen=hashes()
    plan={'gate':a.gate,'repetitions':n,'modes':modes,'planned':n*len(modes),'source_hashes':frozen,'retry_policy':POLICY,'image':IMAGE,'serving_backend':'http'}
    (a.output_dir/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');results=[]
    for repeat in range(1,n+1):
        for mode in modes:
            if hashes()!=frozen:raise RuntimeError('source changed during frozen series')
            configure(False)
            directory=a.output_dir/f'trial-{len(results)+1:02d}-{mode}-r{repeat}'
            command=[sys.executable,str(ROOT/'scripts/semantic-navigation/run_phase5_native.py'),'--oc',OC,'--suite','hotel-guarded',
                     '--contact-audit','--sam3-observation','--served-topology','--console-only-server','--rear-casters',
                     '--physics-step','0.002','--lidar-range','12','--odom-frequency','200','--gpu-rendering','--node-name',NODE,
                     '--image',IMAGE,'--output-dir',str(directory)]
            if a.gate=='recovery':command+=['--recovery-probe']
            elif a.gate=='stop':command+=['--fault-stop-probe','--fault-stop-mode',mode]
            with (a.output_dir/(directory.name+'.log')).open('w') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
            collect_adapter_evidence(directory)
            retries=0
            while r.returncode!=0 and retryable(directory) and retries<3:
                retries+=1
                retained=retain_attempt(directory,retries)
                if sam3_readiness_death(retained):
                    # Order the replacement's announcements behind the dead
                    # fixture's zenoh retirement (liveliness lease 10 s).
                    settle_before_retry()
                if retries==3:configure(False)
                with (a.output_dir/(directory.name+'.log')).open('w') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
                collect_adapter_evidence(directory)
            path=directory/'runtime/summary.json';ev=json.loads(path.read_text()) if path.exists() else {}
            if a.gate=='recovery':ok=recovery_passed(ev,r.returncode,recovery_probe=True,console_only_server=True)
            elif a.gate=='stop':ok=fault_passed(ev,r.returncode,mode)
            else:ok=observation_passed(ev,r.returncode)
            result={'repeat':repeat,'mode':mode,'passed':ok,'returncode':r.returncode,'evidence':str(path),'prearm_liveness_retries':retries,'prearm_topology_recycles':int(retries==3)};results.append(result)
            summary={'passed':len(results)==plan['planned'] and all(x['passed'] for x in results),'planned':plan['planned'],'attempted':len(results),'results':results}
            (a.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(result),flush=True)
            if not ok:raise SystemExit(1)

if __name__=='__main__':main()
