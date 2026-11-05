"""Physical endpoint acceptance for the simulation presentation."""
import math


def endpoint_result(summary, records):
    goal=summary.get('phase6_goal_xy')
    mat=summary.get('phase6_mat_ground_truth')
    if not records or not goal or not mat:
        return {'passed':False,'reason':'missing_endpoint_evidence'}
    last=records[-1]
    pose=last.get('physical') or {}
    if not all(type(pose.get(k)) in (int,float) and math.isfinite(pose[k])
               for k in ('x','y','speed','angular_speed')):
        return {'passed':False,'reason':'invalid_physical_pose'}
    distance=math.hypot(pose['x']-goal[0],pose['y']-goal[1])
    stopped=(last.get('armed') is False and last.get('applied_vx')==0
             and last.get('applied_wz')==0 and pose['speed']<0.005
             and pose['angular_speed']<0.02)
    far_side=pose['x']-0.246>mat['xmax']
    return {'passed':bool(summary.get('passed') and stopped and far_side and distance<=0.2),
            'goal_xy':goal,'physical_xy':[pose['x'],pose['y']],
            'distance_m':distance,'tolerance_m':0.2,'stationary':stopped,
            'clear_of_far_edge':far_side}
