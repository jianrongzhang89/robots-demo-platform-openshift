#!/usr/bin/env python3
"""Audit a Phase 1 warehouse SAM3 semantic repeatability series.

Reads every semantic-320-<route>-<direction>-r<N> trial directory in a series
and reconciles its independent phase-1 energy/sensing and semantic audits into
one cross-run repeatability result. Reports per-run outcomes and cross-run
metric ranges; it does not widen any single-run gate.
"""
import argparse
import json
import re
from pathlib import Path

TRIAL = re.compile(r'^semantic-320-(?P<route>[AB])-(?P<direction>up|down)-r(?P<repeat>[0-9]+)$')


def run(directories):
    trials = {}
    directory_names = {}
    for directory in directories:
        for trial in sorted(p for p in directory.iterdir() if p.is_dir() and TRIAL.match(p.name)):
            # Later directories override earlier ones on trial-name collision
            # (used when an amended fixture re-runs a subset of the series).
            trials[trial.name] = trial
            directory_names[trial] = directory.name
    cases = []
    for name in sorted(trials):
        trial = trials[name]
        match = TRIAL.match(name)
        result = json.loads((trial / 'result.json').read_text())
        phase1 = json.loads((trial / 'phase1-audit.json').read_text())
        semantic = json.loads((trial / 'semantic-warehouse-audit.json').read_text())
        cases.append({
            'trial': trial.name,
            'series_directory': directory_names[trial],
            'route': match['route'],
            'direction': match['direction'],
            'repeat': int(match['repeat']),
            'task_id': result.get('task_id'),
            'status': result.get('status'),
            'phase1_audit_status': phase1.get('status'),
            'semantic_audit_status': semantic.get('status'),
            'nav2_goal_statuses': result.get('nav2_goal_statuses') or semantic.get('nav2_goal_statuses'),
            'rgb_hz': phase1.get('rgb_observed_rate_hz'),
            'depth_hz': phase1.get('depth_observed_rate_hz'),
            'modeled_wh': phase1.get('modeled_battery_wh'),
            'modeled_final_soc': phase1.get('modeled_final_soc'),
            'nonempty_target_masks': semantic.get('nonempty_target_masks'),
            'mask_samples': semantic.get('mask_samples'),
            'saved_rgb_mask_pairs': semantic.get('saved_rgb_mask_pairs'),
            'mask_red_pixel_precision_min': semantic.get('mask_red_pixel_precision_min_mean', [None, None])[0],
            'mask_red_pixel_coverage_min': semantic.get('mask_red_pixel_coverage_min_mean', [None, None])[0],
            'max_plan_centerline_distance_m': semantic.get('max_plan_centerline_distance_m'),
            'max_physical_corridor_distance_m': semantic.get('max_physical_corridor_distance_m'),
        })
    groups = []
    for route in ['A', 'B']:
        for direction in ['up', 'down']:
            members = [c for c in cases if c['route'] == route and c['direction'] == direction]
            if not members:
                continue
            groups.append({
                'route': route,
                'direction': direction,
                'run_count': len(members),
                'all_pass': all(c['status'] == 'PASS' and c['phase1_audit_status'] == 'PASS'
                                and c['semantic_audit_status'] == 'PASS' for c in members),
                'all_nav2_goals_succeeded': all(all(s == 4 for s in c['nav2_goal_statuses']) for c in members),
                'modeled_wh_range': [
                    min(c['modeled_wh'] for c in members if c['modeled_wh'] is not None),
                    max(c['modeled_wh'] for c in members if c['modeled_wh'] is not None)],
                'mask_precision_min': min(c['mask_red_pixel_precision_min'] for c in members
                                          if c['mask_red_pixel_precision_min'] is not None),
                'mask_coverage_min': min(c['mask_red_pixel_coverage_min'] for c in members
                                         if c['mask_red_pixel_coverage_min'] is not None),
                'max_plan_centerline_distance_m': max(c['max_plan_centerline_distance_m'] for c in members
                                                      if c['max_plan_centerline_distance_m'] is not None),
                'max_physical_corridor_distance_m': max(c['max_physical_corridor_distance_m'] for c in members
                                                        if c['max_physical_corridor_distance_m'] is not None),
                'rgb_hz_min': min(c['rgb_hz'] for c in members if c['rgb_hz'] is not None),
                'depth_hz_min': min(c['depth_hz'] for c in members if c['depth_hz'] is not None),
            })
    required = {'A-up', 'A-down', 'B-up', 'B-down'}
    covered = {f"{g['route']}-{g['direction']}" for g in groups}
    complete = covered == required and all(g['run_count'] >= 3 for g in groups)
    status = ('PASS' if cases and complete and all(g['all_pass'] and g['all_nav2_goals_succeeded']
                                                   for g in groups) else 'FAIL')
    result = {
        'status': status,
        'scope': ('repeated simulated warehouse SAM3 semantic runs at 320x240 with frozen red-mat '
                  'prompt/policy; repeated-run stability only, no other-object, 640x480, or physical '
                  'electrical calibration claim'),
        'prompt': 'red mat',
        'policy': 'avoid-target/v1',
        'resolution': '320x240',
        'series_directories': [str(d) for d in directories],
        'trial_count': len(cases),
        'route_directions': sorted(covered),
        'groups': groups,
        'cases': cases,
    }
    (directories[0] / 'semantic-repeatability-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('series', type=Path, nargs='+')
    args = parser.parse_args()
    result = run(args.series)
    print(json.dumps(result))
    raise SystemExit(result['status'] != 'PASS')
