#!/usr/bin/env python3
"""Short stationary G3-fixture telemetry demonstration, not a new G3 gate."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from g4_topology import ROOT,OC
from run_g4_serving_pilot import RESERVATION_POD,pod_ready


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--inference-node',help='Explicit worker for CPU-only telemetry consumers; not G3 requalification');a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).read_bytes();(a.output_dir/'runner-source.py').write_bytes(source)
    resources=json.loads((ROOT/'docs/validation/semantic-navigation/openshift-ai/S3/g3-qualification-20261031/resources-final.json').read_text())['items']
    if a.inference_node:
        for resource in resources:
            if resource['metadata']['name']=='semantic-s3-inference':
                resource['spec']['nodeSelector']['kubernetes.io/hostname']=a.inference_node
                simulator=next(x for x in resources if x['metadata']['name']=='semantic-s3-simulator')
                if a.inference_node==simulator['spec']['nodeSelector']['kubernetes.io/hostname']:
                    resource['spec']['tolerations']=simulator['spec'].get('tolerations',[])
                    # Consumers use CPU only; the simulator retains the only GPU claim.
    reservation=ROOT/'docs/validation/semantic-navigation/openshift-ai/S4/g4-qualification-20261031/rendering-reservation-saved.json'
    created=[];owned=False;children=[];handles=[];report={'passed':False,'scope':'stationary 40-second capture / 60-second costmap telemetry demonstration; no navigation or G3 requalification claim','inference_node_override':a.inference_node}
    report.update(started_at=datetime.now(timezone.utc).isoformat(),command=sys.argv,source_sha256=hashlib.sha256(source).hexdigest())
    def oc(*argv,obj=None):
        r=subprocess.run([OC,'--request-timeout=30s','-n','semantic-navigation',*argv],input=json.dumps(obj) if obj else None,text=True,capture_output=True,timeout=200)
        if r.returncode:raise RuntimeError(r.stderr)
        return r.stdout
    def launch(name,cmd):
        h=(a.output_dir/(name+'.log')).open('w');handles.append(h);r=subprocess.Popen(cmd,stdout=h,stderr=subprocess.STDOUT);children.append(r);return r
    try:
        for kind,name in [('pod','semantic-phase5-native'),('pod','semantic-g4-sam3')]+[(x['kind'],x['metadata']['name']) for x in resources]:
            if oc('get',kind,name,'--ignore-not-found','-o','name').strip():raise RuntimeError('existing fixture '+name)
        if not pod_ready(RESERVATION_POD):raise RuntimeError('reservation not Ready')
        oc('delete','pod',RESERVATION_POD,'--wait=true','--timeout=120s');owned=True
        (a.output_dir/'resources.json').write_text(json.dumps(resources,indent=2)+'\n')
        for obj in resources:
            oc('create','-f','-',obj=obj);created.append(obj)
            if obj['kind']=='Pod':oc('wait','pod/'+obj['metadata']['name'],'--for=condition=Ready','--timeout=180s')
        (a.output_dir/'resources.json').write_text(json.dumps(resources,indent=2)+'\n')
        sampler=launch('navigation',[sys.executable,str(ROOT/'scripts/semantic-navigation/collect_g5_navigation.py'),'--adapter-pod','semantic-s3-inference','--adapter-container','adapter','--costmap-pod','semantic-s3-inference','--output',str(a.output_dir/'navigation.jsonl'),'--seconds','120'])
        costmap=launch('costmap',[sys.executable,str(ROOT/'scripts/semantic-navigation/collect_phase4_evidence.py'),'--pod','semantic-s3-inference','--duration','60','--output-dir',str(a.output_dir/'costmap')])
        capture=launch('capture',[OC,'-n','semantic-navigation','exec','semantic-s3-inference','-c','adapter','--','bash','-ec','source /opt/ros/jazzy/setup.bash; python3 /g3-config/audit_g3_capture_timing.py --duration 40 --output /tmp/g5-capture.json'])
        verify=launch('monitoring',[sys.executable,str(ROOT/'scripts/semantic-navigation/verify_g5_navigation.py'),'--costmap','--output',str(a.output_dir/'monitoring.json')])
        for child in [capture,costmap,verify]:
            if child.wait(timeout=240):raise RuntimeError('telemetry collector or monitoring verification failed')
        oc('cp','-c','adapter','semantic-s3-inference:/tmp/g5-capture.json',str(a.output_dir/'capture.json'))
        correlation=subprocess.run([sys.executable,str(ROOT/'scripts/semantic-navigation/correlate_g3_costmaps.py'),'--run-dir',str(a.output_dir)],text=True,capture_output=True,timeout=30)
        (a.output_dir/'correlation.log').write_text(correlation.stdout+correlation.stderr)
        report['passed']=correlation.returncode==0
    except Exception as error:report['error']=str(error)
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        for h in handles:h.close()
        cleanup=[]
        for obj in created:
            if obj['kind']=='Pod':
                name=obj['metadata']['name']
                try:(a.output_dir/(name+'.json')).write_text(oc('get','pod',name,'-o','json'))
                except Exception as error:report.setdefault('evidence_errors',[]).append(str(error))
                for container in obj['spec']['containers']:
                    try:(a.output_dir/(name+'-'+container['name']+'.log')).write_text(oc('logs',name,'-c',container['name'],'--tail=3000'))
                    except Exception as error:report.setdefault('evidence_errors',[]).append(str(error))
        for obj in reversed(created):
            try:oc('delete',obj['kind'],obj['metadata']['name'],'--wait=true','--timeout=120s');cleanup.append(True)
            except Exception as error:cleanup.append(False);report.setdefault('cleanup_errors',[]).append(str(error))
        if owned:
            try:oc('create','-f',str(reservation));oc('wait','pod/'+RESERVATION_POD,'--for=condition=Ready','--timeout=120s');cleanup.append(True)
            except Exception as error:cleanup.append(False);report.setdefault('cleanup_errors',[]).append(str(error))
        report['cleanup_ok']=all(cleanup);report['passed']=report['passed'] and report['cleanup_ok']
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        (a.output_dir/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
