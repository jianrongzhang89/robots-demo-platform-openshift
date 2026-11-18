#!/usr/bin/env python3
"""Scope the existing adapter to this fixture and record RMF/Nav2 correlation."""
import json
import csv
import os
from pathlib import Path
import sys
import time
import math
from std_msgs.msg import String

sys.path.insert(0,'/work/scripts')
import local_nav2_fleet_adapter as baseline


class WarehouseBackend(baseline.LocalRobotBackend):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.events=self.create_publisher(String,'/warehouse/adapter_events',20)
        self.event_file=open(Path(os.environ['WAREHOUSE_RUN_DIR'],'adapter-events.jsonl'),'a',buffering=1)
        self.energy_cache=(.8,0.0);self.energy_mtime_ns=0

    def record(self,event,**data):
        row={'wall_time':time.time(),'event':event,**data};payload=json.dumps(row)
        self.events.publish(String(data=payload));self.event_file.write(payload+'\n')

    def navigate(self,destination,execution):
        self.record('rmf_navigation',target=list(destination.position),map=destination.map,
                    activity=str(execution.identifier))
        super().navigate(destination,execution)

    def _goal_result(self,future,generation,destination,execution):
        with self._lock:
            goal=self._active_goal
            goal_id=bytes(goal.goal_id.uuid).hex() if goal is not None else None
        self.record('nav2_terminal',generation=generation,target=list(destination.position),
                    goal_id=goal_id,status=int(future.result().status),activity=str(execution.identifier))
        super()._goal_result(future,generation,destination,execution)
        self.record('activity_state',generation=generation,finished=self._active_execution is None)

    def _at_destination(self,destination):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with self._lock:
                fresh=time.monotonic()-self.last_pose_time<.5
                error=math.dist(self.pose[:2],list(destination.position)[:2])
                stopped=abs(self.velocity[0])<.02 and abs(self.velocity[1])<.05
            if fresh and error<.10 and stopped:return True
            time.sleep(.05)
        return False

    def update_state(self):
        # SOC is derived from the instrumented simulation battery trace.  Keep
        # the design assumption visible if the first trace sample has not arrived.
        if self.update_handle is None:return
        soc,cumulative_wh=self.energy_cache
        energy_path=Path(os.environ['WAREHOUSE_RUN_DIR'],'energy.csv')
        try:
            stat=energy_path.stat()
            if stat.st_mtime_ns!=self.energy_mtime_ns:
                with energy_path.open('rb') as stream:
                    stream.seek(max(0,stat.st_size-512))
                    lines=stream.read().decode('ascii').splitlines()
                complete=next((line for line in reversed(lines) if line.count(',')==13),None)
                if complete:
                    last=next(csv.DictReader(['sim_s,dt_s,left_rad_s,right_rad_s,left_nm,right_nm,left_mech_w,right_mech_w,drive_electrical_w,auxiliary_w,battery_w,incremental_wh,cumulative_wh,soc_fraction',complete]))
                    soc=float(last['soc_fraction'])
                    cumulative_wh=float(last['cumulative_wh'])
                    self.energy_mtime_ns=stat.st_mtime_ns
                    self.energy_cache=(soc,cumulative_wh)
                if not math.isfinite(soc) or not 0.0<=soc<=1.0:raise ValueError('invalid SOC')
                if not math.isfinite(cumulative_wh) or cumulative_wh<0:raise ValueError('invalid energy')
        except FileNotFoundError:
            pass
        self.record('battery_state',soc=soc,cumulative_wh=cumulative_wh)
        with self._lock:
            state=baseline.rmf_easy.RobotState(self.current_map,list(self.pose),soc)
            activity=self._activity
        self.update_handle.update(state,activity)


if __name__=='__main__':
    baseline.LocalRobotBackend=WarehouseBackend
    baseline.main()
