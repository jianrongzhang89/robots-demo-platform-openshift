#!/usr/bin/env python3
"""Audit saved full-run evidence independently of RMF's reported success."""
import argparse
import json
import math
from pathlib import Path


def audit(result):
    errors = []
    physical = result.get('physics_history', [])
    def require(condition, message):
        if not condition:
            errors.append(message)
    require(result.get('status') == 'PASS', 'live trial did not pass')
    require(result.get('fleet_idle_at_l1'), 'fleet did not finish idle on L1')
    require(result.get('floor_transitions') == [['L1', 'L3'], ['L3', 'L1']],
            'expected RMF floor round trip was not recorded')
    statuses = result.get('nav2_action_statuses', {})
    require(statuses and all(v == 4 for v in statuses.values()), 'Nav2 goals did not all succeed')
    require(result.get('moving_semantic_plans', 0) > 0 and
            result.get('minimum_moving_plan_hull_clearance_m', -1) >= .2,
            'moving semantic paths did not prove mat clearance')
    require((result.get('adapter_status') or {}).get('backend') == 'http' and
            (result.get('adapter_status') or {}).get('emitted_results', 0) > 0,
            'served model evidence is missing')
    payload_states = [r.get('state') for r in result.get('payload_history', [])]
    require(payload_states.count('attached') >= 2 and payload_states[-1:] == ['detached'],
            'both lift payload attachments and final release were not recorded')
    metrics = {}
    floors = result.get('floor_history', [])
    returned = floors[-1]['wall_time'] if len(floors) >= 3 else float('inf')
    return_plans = [p for p in result.get('plans', [])
                    if p['wall_time'] > returned and p['level'] == 'L1'
                    and p['moving_speed_mps'] > .02
                    and p['semantic_mat_cells'] >= 4]
    metrics['semantic_plans_after_return_to_l1'] = len(return_plans)
    require(return_plans and all(p['mat_minimum_hull_clearance_m'] >= .2
                                for p in return_plans),
            'served mat costs and safe moving plans were not restored after the floor reset')
    if not physical:
        require(False, 'physical pose evidence is missing')
    else:
        end = physical[-1]
        metrics['final_height_m'] = end['z']
        metrics['final_spawn_distance_m'] = math.hypot(end['x']-15.402254826884418,
                                                      end['y']+31.593720701112698)
        require(abs(end['z']) < .15 and metrics['final_spawn_distance_m'] < .4,
                'physical robot did not return to the L1 spawn endpoint')
        l1 = [r for r in physical if -.1 < r['z'] < .5]
        metrics['minimum_physical_mat_clearance_m'] = min((r['hull_clearance_m'] for r in l1), default=-1)
        require(metrics['minimum_physical_mat_clearance_m'] >= .2, 'physical robot violated mat clearance')
        require(any(r.get('nav_active') and 15.8 < r['z'] < 16.2 and
                    math.hypot(r['x']-16.984098, r['y']+24.221069) > 2
                    for r in physical), 'physical Nav2 travel outside the L3 cabin was not recorded')
        cabin = [r for r in physical if 'lift2_z' in r and
                 math.hypot(r['x']-16.984098, r['y']+24.221069) < .8]
        metrics['maximum_cabin_support_gap_m'] = max((abs(r['z']-r['lift2_z']) for r in cabin), default=100)
        require(metrics['maximum_cabin_support_gap_m'] < .2, 'robot lost lift platform support')
        metrics['maximum_fleet_position_error_m'] = max((r.get('fleet_position_error_m', 0) for r in physical))
        require(metrics['maximum_fleet_position_error_m'] <= .75, 'fleet position diverged from physical pose')
        require(all(r['z'] > -.2 and abs(r['roll']) < .6 and abs(r['pitch']) < .6 for r in physical),
                'robot fell or lost upright support')
    return {'status': 'FAIL' if errors else 'PASS', 'task_id': result.get('task_id'),
            'metrics': metrics, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path)
    args = parser.parse_args()
    summary = audit(json.loads(args.result.read_text()))
    print(json.dumps(summary, indent=2))
    return int(summary['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
