#!/usr/bin/env python3
"""Bounded read-only fixture sampling and dashboard publication; no ROS commands."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=int,default=900);p.add_argument('--adapter-pod',default='semantic-g4-sam3');p.add_argument('--adapter-container',default='sam3-inference');p.add_argument('--costmap-pod');a=p.parse_args()
    if not 1<=a.seconds<=3600:raise ValueError('bounded collection duration required')
    def oc(*args,data=None):
        r=subprocess.run(['oc','--request-timeout=5s','-n','semantic-navigation',*args],input=data,text=True,capture_output=True,timeout=10)
        if r.returncode:raise RuntimeError('source or exporter unavailable')
        return r.stdout
    previous=None;end=time.monotonic()+a.seconds
    with a.output.open('x') as output:
        while time.monotonic()<end:
            row={'host_observed_wall_ns':time.time_ns()}
            for key,pod,container,path in [('adapter',a.adapter_pod,a.adapter_container,'/tmp/semantic-status.json'),('fixture','semantic-phase5-native','fixture','/tmp/phase5-native-results/semantic-armed-status.json')]:
                try:row[key]=json.loads(oc('exec',pod,'-c',container,'--','cat',path))
                except (ValueError,RuntimeError,subprocess.SubprocessError):row[key]={}
            row['observed_wall_ns']=max(row['adapter'].get('status_wall_ns',0),row['fixture'].get('written_wall_ns',0))
            if a.costmap_pod:
                try:
                    raw=oc('logs',a.costmap_pod,'-c','costmap-observer','--tail=1')
                    maps=json.loads(raw)['maps'];row['costmap_maps']=maps
                    applied=[m['last'] for m in maps.values() if m.get('current') and m.get('last') and 'costmap_wall_ns' in m['last']]
                    if applied:
                        latest=max(applied,key=lambda x:x['costmap_wall_ns']-x['capture_wall_ns'])
                        row['costmap']={**latest,'observed_wall_ns':latest['costmap_wall_ns']}
                        row['observed_wall_ns']=max(row['observed_wall_ns'],latest['costmap_wall_ns'])
                except (ValueError,KeyError,RuntimeError,subprocess.SubprocessError):row['costmap']={}
            last=(row['adapter'].get('last_result') or {})
            source=(last.get('source_epoch'),(last.get('capture') or {}).get('stamp_ns'),last.get('capture_wall_ns'))
            if previous and source[0]==previous[0] and all(type(x) is int for x in (*source[1:],*previous[1:])) and source[2]>previous[2] and source[1]>previous[1]:
                row['rtf']=(source[1]-previous[1])/(source[2]-previous[2]);row['rtf_source_wall_ns']=source[2]
            if source[2]:previous=source
            try:
                oc('exec','-i','semantic-g5-navigation-metrics','--','python3','-c','import sys,pathlib; p=pathlib.Path("/tmp/navigation.tmp"); p.write_text(sys.stdin.read()); p.replace("/tmp/navigation.json")',data=json.dumps(row))
                row['published']=True
            except (RuntimeError,subprocess.SubprocessError):row['published']=False
            output.write(json.dumps(row)+'\n');output.flush();time.sleep(2)


if __name__=='__main__':main()
