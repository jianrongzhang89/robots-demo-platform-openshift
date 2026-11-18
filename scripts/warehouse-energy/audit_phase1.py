#!/usr/bin/env python3
"""Independently reconcile Phase 1 modeled electrical energy and sensing evidence."""
import argparse
import csv
import json
import math
from pathlib import Path


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def audit(directory):
    design=json.loads((directory/'design.json').read_text())
    result=json.loads((directory/'result.json').read_text())
    assumptions=json.loads((Path(__file__).resolve().parents[2]/'config/warehouse-energy/phase1-telemetry-v1.json').read_text())
    torque=rows(directory/'torque.csv');energy=rows(directory/'energy.csv')
    errors=[]
    def require(condition,message):
        if not condition:errors.append(message)
    require(bool(torque) and bool(energy),'missing actuator or battery trace')
    require(len(torque)==len(energy),'actuator and energy sample counts differ')
    expected={}
    for row in torque:
        t=float(row['sim_s'])
        require(math.isfinite(t),'non-finite actuator timestamp')
        expected[t]=row
    cumulative=0.0;previous=None
    for index,row in enumerate(energy):
        t=float(row['sim_s']);dt=float(row['dt_s'])
        require(math.isfinite(t) and (previous is None or t>previous),'energy simulation clock did not increase')
        require(t in expected,'energy sample has no matching actuator sample')
        source=expected.get(t,{})
        left=float(row['left_rad_s']);right=float(row['right_rad_s'])
        lt=float(row['left_nm']);rt=float(row['right_nm'])
        lm=max(0.0,lt*left);rm=max(0.0,rt*right)
        drive=(lm+rm)/float(assumptions['electrical_model']['drive_efficiency'])
        aux=float(assumptions['electrical_model']['auxiliary_power_w'])
        battery=drive+aux
        increment=battery*dt/3600.0
        require(abs(left-float(source.get('left_rad_s',left)))<1e-8 and abs(right-float(source.get('right_rad_s',right)))<1e-8,
                'energy trace wheel speed differs from independent actuator trace')
        require(abs(lt-float(source.get('left_nm',lt)))<1e-8 and abs(rt-float(source.get('right_nm',rt)))<1e-8,
                'energy trace torque differs from independent actuator trace')
        require(abs(float(row['left_mech_w'])-lm)<1e-8 and abs(float(row['right_mech_w'])-rm)<1e-8,
                'wheel mechanical power does not reconcile')
        require(abs(float(row['drive_electrical_w'])-drive)<1e-7 and abs(float(row['auxiliary_w'])-aux)<1e-8,
                'electrical component power does not reconcile')
        require(abs(float(row['battery_w'])-battery)<1e-7,'battery power does not reconcile')
        require(abs(float(row['incremental_wh'])-increment)<1e-10,'incremental Wh does not reconcile')
        cumulative+=increment
        require(abs(float(row['cumulative_wh'])-cumulative)<1e-9,'cumulative Wh does not reconcile')
        expected_soc=max(0.0,float(assumptions['electrical_model']['initial_soc_fraction'])-
                         cumulative/float(assumptions['electrical_model']['battery_capacity_wh']))
        require(abs(float(row['soc_fraction'])-expected_soc)<1e-9,'SOC does not reconcile to modeled Wh')
        require(dt==0 if index==0 else 0<dt<=0.2,'energy sample interval outside supported window')
        previous=t
    sensing=result.get('rgbd',{})
    camera=design.get('camera',{'width':640,'height':480,'configured_rate_hz':10})
    require(result.get('status')=='PASS','navigation / sensing trial did not pass')
    require(sensing.get('rgb_samples',0)>=3 and sensing.get('depth_samples',0)>=3 and sensing.get('camera_info_samples',0)>0,
            'RGB-D or camera calibration stream is missing')
    for name in ['rgb_latest','depth_latest']:
        sample=sensing.get(name) or {}
        require(sample.get('width')==camera['width'] and sample.get('height')==camera['height'] and sample.get('data_bytes',0)>0,
                f'{name} is empty or has unexpected dimensions')
        require(sample.get('frame_id')=='camera_color_optical_frame',f'{name} camera optical frame is missing')
    tf_checked='camera_tf_samples' in sensing
    if tf_checked:
        require(sensing.get('camera_tf_samples',0)>0,'full-pose camera TF was not published')
        require(sensing.get('camera_tf_latest',{}).get('parent')=='odom','camera TF parent is not odom')
        require(bool(sensing.get('capture_tf_nearest_delta_s')) and
                max(sensing.get('capture_tf_nearest_delta_s',[]))<=.06,
                'capture-time RGB-D transform is missing or stale')
    require(bool(result.get('battery_state_samples')),'adapter did not report battery state')
    report={'status':'FAIL' if errors else 'PASS','errors':errors,
        'scope':'independent arithmetic reconciliation of modeled simulated electrical telemetry and RGB-D transport; no physical calibration or SAM3 semantic-label claim',
        'task_id':result.get('task_id'),
        'route':design.get('route'),'direction':design.get('direction'),'payload_kg':design.get('payload_kg'),
        'actuator_samples':len(torque),'energy_samples':len(energy),
        'capture_time_camera_tf_checked':tf_checked,
        'modeled_battery_wh':cumulative,'modeled_final_soc':float(energy[-1]['soc_fraction']) if energy else None,
        'camera_configured_rate_hz':camera.get('configured_rate_hz'),
        'rgb_observed_rate_hz':sensing.get('rgb_rate',{}).get('average_hz'),
        'depth_observed_rate_hz':sensing.get('depth_rate',{}).get('average_hz'),
        'rgb_samples':sensing.get('rgb_samples',0),'depth_samples':sensing.get('depth_samples',0)}
    (directory/'phase1-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('trial',type=Path)
    args=parser.parse_args();report=audit(args.trial);print(json.dumps(report))
    raise SystemExit(report['status']!='PASS')
