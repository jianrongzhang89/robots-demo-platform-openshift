import json,sys,subprocess,shutil,time
from pathlib import Path
sys.path.insert(0,str(Path('scripts/semantic-navigation').resolve()))
from phase6_topology import topology_objects,wait_router_available,wait_ready,restore_spec
from run_phase6_series import hull_exposure_m
oc='/Users/zhangj/bin/oc';ns='semantic-navigation'
e=Path('docs/validation/semantic-navigation/openshift-ai/S0/g0-completion-20261030/baseline');e.mkdir()
def call(*args,check=True,**kwargs):
 return subprocess.run([oc,'-n',ns,*args],capture_output=True,text=True,check=check,**kwargs)
def get(kind,name):return json.loads(call('get',kind,name,'-o','json').stdout)
image='image-registry.openshift-image-registry.svc:5000/semantic-navigation/sam3-runtime@sha256:478ec01a7a47fbb0c862fbbef495c71b4a512ff59ed8d6ed5b7234422cc35686'
plan=json.loads(Path('docs/validation/semantic-navigation/phase-6/series-23-20261029/plan.json').read_text());plan['purpose']='G0 one nominal pair reproduction; not a repeat 58-trial qualification';plan['reserved_window_note']='User authorized G0 completion; private topology temporarily borrows local SAM3 GPU; demo restored in finally';(e/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
demo=get('pod','semantic-phase6-sam3');restore=restore_spec(demo);(e/'demo-sam3-before.json').write_text(json.dumps(demo,indent=2));(e/'demo-sam3-restore.json').write_text(json.dumps(restore,indent=2))
saved=[]
objects=topology_objects(image)
for obj in objects[:-1]:
 raw=call('get',obj['kind'],obj['metadata']['name'],'--ignore-not-found','-o','json').stdout
 saved.append(json.loads(raw) if raw.strip() else None)
(e/'private-topology-before.json').write_text(json.dumps(saved,indent=2))
deleted=False
try:
 for obj in objects[:-1]:call('apply','-f','-',input=json.dumps(obj))
 call('rollout','restart','deployment/semantic-phase5-sam3-router')
 call('rollout','status','deployment/semantic-phase5-sam3-router','--timeout=180s')
 assert wait_router_available(oc)
 call('delete','pod','semantic-phase6-sam3','--wait=true','--timeout=120s');deleted=True
 call('create','-f','-',input=json.dumps(objects[-1]));assert wait_ready(oc,'semantic-phase5-sam3')
 print('Private SAM3 topology ready',flush=True)
 for i,arm in enumerate(('off','on')):
  output=e/f'trial-{i:03d}-{arm}-nominal.json'
  result=subprocess.run([sys.executable,'scripts/semantic-navigation/phase6_trial.py',arm,'nominal',str(i),str(output)])
  if result.returncode:raise RuntimeError(f'{arm} baseline trial failed; retained evidence, no check-failure retry')
 records=[json.loads((e/f'trial-{i:03d}-{a}-nominal.json').read_text()) for i,a in enumerate(('off','on'))]
 exposures=[hull_exposure_m(r['trajectory_map_xy'],plan['ground_truth_region'],plan['hull_radius_m']) for r in records]
 passed=all(r['completed'] and r['collision'] is False for r in records) and exposures[0]>0 and exposures[1]<=0.1*exposures[0]
 (e/'pair-result.json').write_text(json.dumps({'passed':passed,'off_hull_exposure_m':exposures[0],'on_hull_exposure_m':exposures[1],'reduction_fraction':1-exposures[1]/exposures[0] if exposures[0] else None,'samples':2,'profile':'accepted Phase 6 lethal-254, speed 0.15 m/s','recognition_waiver_retained':True},indent=2)+'\n')
 print('Baseline pair passed:',passed,flush=True)
finally:
 if deleted:
  call('delete','pod','semantic-phase5-sam3','--ignore-not-found','--wait=true','--timeout=120s',check=False)
  call('create','-f','-',input=json.dumps(restore));ready=wait_ready(oc,'semantic-phase6-sam3')
  (e/'demo-restoration.json').write_text(json.dumps({'ready':ready,'pod':get('pod','semantic-phase6-sam3')},indent=2));print('Demo SAM3 restored:',ready,flush=True)
 # Restore the preexisting private router objects without deleting shared resources.
 for obj,old in zip(objects[:-1],saved):
  if old:
   old.pop('status',None)
   for key in ('resourceVersion','uid','creationTimestamp','managedFields'):old['metadata'].pop(key,None)
   call('apply','-f','-',input=json.dumps(old),check=False)
  else:call('delete',obj['kind'],obj['metadata']['name'],'--ignore-not-found',check=False)
