#!/usr/bin/env python3
"""G4 motion fault qualification. Each independent trial uses a fresh topology.

No armed or injected-fault failure is retried. The accepted pre-arm liveness
ladder requires an empty arming history and retains every setup attempt. HTTP response faults use the explicitly declared
loopback mTLS injector and real upstream model during healthy/recovery phases.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from g4_topology import ROOT, OC, POD, ROUTER, resources, call, wait_initialized, recycle
from phase6_trial import IMAGE, NODE
from g4_prearm import POLICY, retryable, retain_attempt, sam3_readiness_death, settle_before_retry
from run_phase5_semantic_fault_matrix import trial_passed, STATUS_PATH
sys.path.insert(0,str(ROOT/'apps/semantic-safety'))
from semantic_fault_probe import MODES, SERVED_MODES


def fixture_status():
    p=call('exec','semantic-phase5-native','-c','fixture','--','cat',STATUS_PATH,check=False)
    try:return json.loads(p.stdout)
    except ValueError:return {}


def wait_semantic_flow(baseline, timeout=45):
    """A completed restore must have restored end-to-end inference, not only
    adapter identity: zenoh-bridge 1.5.0 route re-binding on participant
    churn is intermittent (qualification-5 trial-02 retained a restore whose
    semantic topics never re-crossed the fixture bridge while the camera path
    and adapter results were healthy). True once the fixture supervisor has
    observed a new semantic lease sequence beyond the pre-restore baseline."""
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        seq=(fixture_status().get('leases') or {}).get('semantic')
        if isinstance(seq,int) and seq>baseline: return True
        time.sleep(2)
    return False

def configure(proxy):
    objs=resources(proxy)
    for kind,name in [('pod',POD),('deployment',ROUTER)]:
        call('delete',kind,name,'--ignore-not-found','--wait=true','--timeout=60s')
    for obj in objs[:2]:call('apply','-f','-',obj=obj)
    call('create','-f','-',obj=objs[2]);call('rollout','status','deployment/'+ROUTER,'--timeout=180s')
    call('create','-f','-',obj=objs[3]);wait_initialized()
    return objs


def set_mode(mode):
    return call('exec',POD,'-c','sam3-inference','--','python3','-c',
                'from pathlib import Path; import sys; p=Path("/tmp/g4-fault-mode.tmp"); p.write_text(sys.argv[1]); p.replace("/tmp/g4-fault-mode")',mode)


def signal_adapter(signal):
    return call('exec',POD,'-c','sam3-inference','--','bash','-c',f'kill -{signal} "$(cat /tmp/sam3-python.pid)"')


def internal_fault_proof(mode, events):
    injected=next((e for e in events if e.get('event')=='semantic_fault_injected' and e.get('mode')==mode and e.get('injected_by')=='fixture'),None)
    restored=next((e for e in events if e.get('event')=='semantic_fault_restored' and e.get('mode')==mode),None)
    native=(injected or {}).get('native_status') or {}
    physical=native.get('physical') or {}
    return bool(injected and restored and restored.get('steady_ns',0)>injected.get('steady_ns',0)
                and native.get('armed') is True and native.get('applied_vx',0)>.02
                and physical.get('velocity_valid') is True and physical.get('speed',0)>.02)


def run_trial(mode, directory, objects=None):
    proxy=mode in SERVED_MODES
    objs=configure(proxy) if objects is None else objects
    command=[sys.executable,str(ROOT/'scripts/semantic-navigation/run_phase5_native.py'),
             '--oc',OC,'--suite','hotel-guarded','--contact-audit','--sam3-observation','--served-topology',
             '--semantic-fault-probe','--semantic-fault-mode',mode,'--console-only-server','--rear-casters',
             '--physics-step','0.002','--lidar-range','12','--odom-frequency','200','--gpu-rendering',
             '--node-name',NODE,'--image',IMAGE,'--output-dir',str(directory)]
    log=directory.parent/(directory.name+'.log')
    events=[];injected=False;restored=False
    with log.open('w') as output:
        run=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT)
        try:
            while run.poll() is None:
                state=fixture_status()
                if state.get('phase')=='motion_verified' and not injected:
                    event={'event':'inject','mode':mode,'fixture_state':state,'controller_wall_ns':time.time_ns()}
                    if proxy:r=set_mode(mode)
                    elif mode=='hung_inference':r=signal_adapter('STOP')
                    elif mode=='process_loss':r=signal_adapter('KILL')
                    elif mode=='transport_loss':r=call('delete','pod',POD,'--grace-period=0','--force','--wait=true','--timeout=30s')
                    else:r=None
                    event['returncode']=r.returncode if r else 0;events.append(event);injected=True
                if injected and not restored and state.get('phase')=='stopped':
                    if proxy:
                        capture=call('exec',POD,'-c','sam3-inference','--','cat','/tmp/g4-proxy-events.jsonl',check=False)
                        (directory/'proxy-events-at-stop.jsonl').write_text(capture.stdout)
                        set_mode('healthy')
                    if mode=='hung_inference':signal_adapter('CONT')
                    elif mode in ('wrong_version','process_loss','transport_loss'):
                        # Wrong identity deliberately stays latched until process
                        # restart; motion must stay stopped after this repair.
                        # Each replacement is ordered: the fixture bridge has
                        # to process the old participant's retirement before
                        # the new bridge announces, or the semantic routes
                        # stay unbound (zenoh-bridge 1.5.0 ordering race).
                        # Even ordered, the zenoh router's data-plane matching
                        # between a new client's publishers and the fixture
                        # bridge's existing subscribers is a coin flip
                        # (qualification-10 trial-08: liveliness crossed, zero
                        # data, zero errors on any side), and a router restart
                        # is fatal to the fixture bridge (pilot-4) — so the
                        # adapter client is replaced up to three times, each
                        # verified end-to-end and recorded. This completes the
                        # harness's restore step only; the trial's verdict is
                        # still decided by the unchanged late-success check.
                        baseline=(state.get('leases') or {}).get('semantic') or 0
                        for attempt in (1,2,3):
                            call('delete','pod',POD,'--ignore-not-found','--force',
                                 '--grace-period=0','--wait=true','--timeout=50s')
                            time.sleep(20)
                            call('create','-f','-',obj=objs[3]);wait_initialized()
                            verified=wait_semantic_flow(baseline,
                                timeout=45 if attempt==1 else 15)
                            events.append({'event':'restore_flow_verified' if verified
                                else 'restore_semantic_flow_missing','attempt':attempt,
                                'baseline_semantic_sequence':baseline})
                            if verified: break
                    events.append({'event':'restore','mode':mode,'fixture_state':state,'controller_wall_ns':time.time_ns()});restored=True
                time.sleep(.5)
        finally:
            if injected and not restored:
                if proxy:set_mode('healthy')
                elif mode=='hung_inference':signal_adapter('CONT')
            run.wait()
    if proxy:
        snapshot=call('exec',POD,'-c','sam3-inference','--','cat','/tmp/g4-proxy-events.jsonl',check=False)
        (directory/'proxy-events-final.jsonl').write_text(snapshot.stdout)
    snapshot=call('exec',POD,'-c','sam3-inference','--','cat','/tmp/semantic-status.json',check=False)
    (directory/'adapter-status-final.json').write_text(snapshot.stdout)
    (directory/'injection-log.json').write_text(json.dumps(events,indent=2)+'\n')
    (directory/'topology.json').write_text(json.dumps(objs,indent=2)+'\n')
    for container in ('sam3-inference','sam3-zenoh-bridge'):
        # Prefixed names: run_phase5_native collects the FIXTURE pod's
        # sidecars into the same directory, and a bare
        # sam3-zenoh-bridge.log would overwrite the fixture bridge's log
        # (the adapter pod's bridge log is a different container).
        (directory/('adapter-'+container+'.log')).write_text(call('logs',POD,'-c',container,check=False).stdout)
    # The router is recreated per trial, so its log covers exactly this
    # trial's client churn — the only window where the data-plane matching
    # between replaced clients and existing subscribers is visible.
    (directory/'router.log').write_text(call('logs','deployment/'+ROUTER,'--tail=10000',check=False).stdout)
    path=directory/'runtime/summary.json'
    evidence=json.loads(path.read_text()) if path.exists() else {}
    if mode in ('camera_path_loss','tf_loss'):
        native_path=directory/'runtime/fault-injection-events.json'
        native_events=json.loads(native_path.read_text()) if native_path.exists() else []
        # These faults are injected/restored inside the fixture. Their whole
        # phase can be shorter than a CLI poll; use the native event proof.
        injected=restored=internal_fault_proof(mode,native_events)
        events.append({'event':'internal_fault_proof','passed':injected,'source':str(native_path)})
        (directory/'injection-log.json').write_text(json.dumps(events,indent=2)+'\n')
    passed=trial_passed(evidence,run.returncode,mode) and injected and restored
    if proxy:
        events_path=directory/'proxy-events-at-stop.jsonl'
        wire=[json.loads(x) for x in events_path.read_text().splitlines()] if events_path.exists() else []
        active=[e for e in wire if e['mode']==mode]
        passed=passed and bool(active)
        if mode=='auth': passed=passed and any(e.get('upstream_status')==403 for e in active)
        if mode=='overload': passed=passed and any(429 in e.get('upstream_statuses',[]) for e in active)
        if mode=='serving': passed=passed and any(e.get('status')==503 for e in active)
        if mode=='wrong_version': passed=passed and any(e.get('status')==200 for e in active)
    return {'mode':mode,'passed':passed,'returncode':run.returncode,'evidence':str(path),'injected':injected,'restored':restored}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--modes',nargs='+',choices=MODES+SERVED_MODES,default=list(MODES+SERVED_MODES))
    p.add_argument('--repetitions',type=int,default=2);a=p.parse_args()
    if a.repetitions<1:p.error('positive repetitions required')
    a.output_dir.mkdir(parents=True,exist_ok=False)
    files=list((ROOT/'apps/semantic-safety').glob('*.py'))+[Path(__file__),ROOT/'scripts/semantic-navigation/run_phase5_native.py',ROOT/'scripts/semantic-navigation/g4_topology.py',ROOT/'scripts/semantic-navigation/g4_fault_proxy.py',ROOT/'scripts/semantic-navigation/g4_prearm.py']
    hashes=lambda:{str(f.relative_to(ROOT)) if f.is_absolute() else str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    frozen=hashes();plan={'modes':a.modes,'repetitions':a.repetitions,'source_hashes':frozen,'image':IMAGE,'retry_policy':POLICY,'freshness_ms':500,'zero_command_ms':100,'injection':'loopback mTLS response faults; real model healthy and recovery; legacy faults direct'}
    (a.output_dir/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    results=[]
    for repeat in range(1,a.repetitions+1):
        for mode in a.modes:
            if hashes()!=frozen:raise RuntimeError('source changed during frozen series')
            directory=a.output_dir/f'trial-{len(results)+1:02d}-{mode}-r{repeat}'
            result=run_trial(mode,directory)
            retries=0
            while not result['passed'] and retryable(directory) and retries<3:
                retries+=1
                retained=retain_attempt(directory,retries)
                if sam3_readiness_death(retained):
                    # Order the replacement's announcements behind the dead
                    # fixture's zenoh retirement (liveliness lease 10 s).
                    settle_before_retry()
                objects=json.loads((retained/'topology.json').read_text()) if retries<3 else None
                result=run_trial(mode,directory,objects)
            result['prearm_liveness_retries']=retries
            result['prearm_topology_recycles']=int(retries==3)
            result['repeat']=repeat;results.append(result)
            summary={'passed':len(results)==len(a.modes)*a.repetitions and all(r['passed'] for r in results),'planned':len(a.modes)*a.repetitions,'attempted':len(results),'results':results}
            (a.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(result),flush=True)
            if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
