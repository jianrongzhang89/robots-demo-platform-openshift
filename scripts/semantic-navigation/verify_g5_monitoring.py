#!/usr/bin/env python3
"""Verify G5 scrape data through authenticated Thanos queries; never log tokens."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    def oc(*args):return subprocess.check_output(['oc','--request-timeout=20s',*args],text=True,timeout=30)
    report={'recorded_at':datetime.now(timezone.utc).isoformat(),'status':'FAIL','samples':[],'browser_visual_check':'NOT_RUN'}
    with a.output.open('x') as handle:
        try:
            host=oc('get','route','thanos-querier','-n','openshift-monitoring','-o','jsonpath={.spec.host}').strip()
            token=oc('whoami','-t').strip()
            queries={
                'scrape':'up{namespace="semantic-model-serving",service="sam3-mat-v1-tls"}',
                'worker':'semantic_worker_ready{namespace="semantic-model-serving",service="sam3-mat-v1-tls"}',
                'requests':'semantic_requests_total{namespace="semantic-model-serving",service="sam3-mat-v1-tls"}',
                'gpu':'accelerator_gpu_utilization{exported_namespace="semantic-model-serving"}',
                'gpu_memory':'accelerator_memory_used_bytes{exported_namespace="semantic-model-serving"}',
                'image':'kube_pod_container_info{namespace="semantic-model-serving",container="kserve-container"}'}
            end=time.monotonic()+180
            while time.monotonic()<end:
                sample={'recorded_at':datetime.now(timezone.utc).isoformat(),'results':{}}
                for key,query in queries.items():
                    request=urllib.request.Request('https://'+host+'/api/v1/query?'+urllib.parse.urlencode({'query':query}),headers={'Authorization':'Bearer '+token})
                    with urllib.request.urlopen(request,timeout=10) as response:result=json.load(response)
                    if result['status']!='success':raise ValueError('query failed: '+key)
                    sample['results'][key]=result['data']['result']
                report['samples'].append(sample)
                if all(sample['results'].values()) and all(float(row['value'][1])==1 for key in ['scrape','worker'] for row in sample['results'][key]):
                    report['status']='PASS';break
                time.sleep(10)
            dashboard=json.loads(oc('get','persesdashboard','semantic-g5-serving','-n','redhat-ods-monitoring','-o','json'))
            report['dashboard']={'name':dashboard['metadata']['name'],'namespace':dashboard['metadata']['namespace'],'uid':dashboard['metadata']['uid'],'panels':list(dashboard['spec']['config']['panels'])}
        except Exception as error:
            report['error']=str(error);raise
        finally:handle.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'panels':len(report['dashboard']['panels'])}))
    if report['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
