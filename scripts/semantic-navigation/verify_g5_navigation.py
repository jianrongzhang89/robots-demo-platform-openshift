#!/usr/bin/env python3
"""Verify passive navigation series through the authenticated monitoring API."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.parse


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--unavailable',action='store_true');p.add_argument('--costmap',action='store_true');a=p.parse_args()
    host=subprocess.check_output(['oc','--request-timeout=20s','get','route','thanos-querier','-n','openshift-monitoring','-o','jsonpath={.spec.host}'],text=True).strip()
    token=subprocess.check_output(['oc','whoami','-t'],text=True).strip()
    scope='{namespace="semantic-navigation",service="semantic-g5-navigation-metrics"}'
    names=['snapshot_available','adapter_available','safety_available','capture_to_result_seconds','last_capture_timestamp_seconds','capture_stream_rtf','armed','stop_reason','work_queue_drops','costmap_available']
    if a.costmap or a.unavailable:names.append('capture_to_costmap_seconds')
    report={'recorded_at':datetime.now(timezone.utc).isoformat(),'status':'FAIL','expect_unavailable':a.unavailable,'samples':[]}
    with a.output.open('x') as output:
        try:
            end=time.monotonic()+180
            while time.monotonic()<end:
                sample={}
                for name in names:
                    query='g5_navigation_'+name+scope
                    req=urllib.request.Request('https://'+host+'/api/v1/query?'+urllib.parse.urlencode({'query':query}),headers={'Authorization':'Bearer '+token})
                    with urllib.request.urlopen(req,timeout=10) as r:data=json.load(r)
                    sample[name]=data['data']['result']
                report['samples'].append(sample)
                if a.unavailable:
                    availability=['snapshot_available','adapter_available','safety_available','costmap_available']
                    passed=all(sample[name] and all(float(x['value'][1])==0 for x in sample[name]) for name in availability) and all(not sample[name] for name in names if name not in availability)
                elif a.costmap:
                    required=[name for name in names if name not in ['safety_available','armed','stop_reason']]
                    passed=all(sample[name] for name in required) and all(float(x['value'][1])==1 for name in ['snapshot_available','adapter_available','costmap_available'] for x in sample[name])
                else:
                    passed=all(sample[name] for name in names) and all(float(x['value'][1])==1 for name in ['snapshot_available','adapter_available','safety_available'] for x in sample[name])
                if passed:report['status']='PASS';break
                time.sleep(5)
        finally:output.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'samples':len(report['samples'])}))
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
