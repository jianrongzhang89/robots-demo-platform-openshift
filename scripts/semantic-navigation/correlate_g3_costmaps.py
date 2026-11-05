#!/usr/bin/env python3
"""Cross-check applied costmap request IDs against actual capture/result records."""
import argparse
import gzip
import json
from pathlib import Path


def correlate(capture, updates):
    results={r['identity']['request_id']:r for r in capture['results']}
    lower=min(r['capture_wall_ns'] for r in results.values())
    upper=max(r['capture_wall_ns'] for r in results.values())
    maps={'global_semantic':{},'local_semantic':{}}
    for row in updates:
        for name,data in row['maps'].items():
            last=data['last']
            if last and 'costmap_wall_ns' in last:maps[name][last['request_id']]=last
    report={'status':'PASS','maps':{}}
    for name,applied in maps.items():
        matched=[];mismatches=[];boundaries=[];unexpected=[]
        for request,last in applied.items():
            if request not in results:
                (unexpected if lower<=last['capture_wall_ns']<=upper else boundaries).append(request)
                continue
            r=results[request];matched.append(request)
            if last['stamp_ns']!=r['capture']['stamp_ns'] or last['capture_wall_ns']!=r['capture_wall_ns']:
                mismatches.append(request)
            if r['identity']['robot']!='robot_1' or r['identity']['stream']!='camera/color':mismatches.append(request)
        # Independent collectors have slightly different start/end windows.
        # Retain out-of-window rows separately; never ignore an unknown ID
        # whose capture belongs to the measured result interval.
        coverage=len(matched)/len(results)
        passed=not mismatches and not unexpected and coverage>=.95
        report['maps'][name]={'pass':passed,'applied_unique':len(applied),'matched':len(matched),
            'coverage':coverage,'wrong_capture_or_stream':mismatches,'unexpected_inside_window':unexpected,
            'outside_capture_window':boundaries,'missing_result_ids':sorted(set(results)-set(matched))}
        if not passed:report['status']='FAIL'
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args()
    capture=json.loads((a.run_dir/'capture.json').read_text())
    with gzip.open(a.run_dir/'costmap/updates.jsonl.gz','rt') as h: result=correlate(capture,(json.loads(line) for line in h))
    (a.run_dir/'correlation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    if result['status']!='PASS':raise SystemExit(1)
