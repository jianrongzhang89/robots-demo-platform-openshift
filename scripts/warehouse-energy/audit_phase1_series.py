#!/usr/bin/env python3
"""Audit all route cases in a Phase 1 telemetry series."""
import argparse
import json
from pathlib import Path
from audit_phase1 import audit


def run(directory):
    cases=json.loads((directory/'series-result.json').read_text())
    reports=[]
    for case in cases:
        trial=directory/case['case'].replace(':','-')
        report=audit(trial)
        reports.append({'case':case['case'],'status':report['status'],'task_id':report.get('task_id'),
            'modeled_battery_wh':report.get('modeled_battery_wh'),
            'modeled_final_soc':report.get('modeled_final_soc'),
            'rgb_samples':report.get('rgb_samples'),'depth_samples':report.get('depth_samples'),
            'capture_time_camera_tf_checked':report.get('capture_time_camera_tf_checked'),
            'errors':report['errors']})
    result={'status':'PASS' if len(reports)==len(cases) and all(r['status']=='PASS' for r in reports) else 'FAIL',
        'scope':'four route/direction integrated simulation telemetry checks; modeled energy assumptions only, no SAM3 semantic label or physical electrical calibration claim',
        'case_count':len(reports),'cases':reports}
    (directory/'phase1-series-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('series',type=Path)
    args=parser.parse_args();result=run(args.series);print(json.dumps(result))
    raise SystemExit(result['status']!='PASS')
