"""Read retained runs only. No cluster calls or changes to control behavior."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
BASE = OUT.parent
MS = 1_000_000

def read(path):
    return json.loads(path.read_text())

def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]

def load(number):
    root = BASE / f'navigation-demo-on-{number}' / 'trial'
    runtime = root / 'runtime'
    trace = lines(runtime / 'trace.jsonl')
    coordinator = read(runtime / 'guard-events.json')['coordinator']
    leases = [r for r in coordinator if r['event'] == 'lease_enqueued']
    return root, runtime, trace, coordinator, leases

def packet(row, token):
    return {'schema': 'phase5-drive/v1', 'session': token,
            **{k: row[k] for k in ('sequence', 'issued_wall', 'expires_wall', 'velocity')}}

comparisons = []
for number in [2, 3, 5, 6]:
    root, runtime, trace, coordinator, leases = load(number)
    armed = [r for r in trace if r['armed']]
    first, last = armed[0], armed[-1]
    resources = read(runtime/'resource-samples.json')['samples']
    before = min(resources, key=lambda r: abs(r['steady_ns']-first['steady_ns']))
    after = min(resources, key=lambda r: abs(r['steady_ns']-last['steady_ns']))
    dt = (after['steady_ns']-before['steady_ns']) / 1e9
    summary = read(runtime/'summary.json')
    timing = next(c for c in summary['checks'] if c['case']=='sam3_observation_timing')
    windows = [(r['expires_wall']-r['issued_wall'])/MS for r in leases]
    comparisons.append({'run': number, 'fixture_passed': summary['passed'],
        'armed_rtf': (last['physical']['sim_ns']-first['physical']['sim_ns']) /
                     (last['wall_ns']-first['wall_ns']),
        'fixture_cpu_cores_during_armed_interval':
            (after['cpu.stat']['usage_usec']-before['cpu.stat']['usage_usec']) / 1e6/dt,
        'fixture_throttled_usec_during_armed_interval':
            after['cpu.stat']['throttled_usec']-before['cpu.stat']['throttled_usec'],
        'minimum_emitted_window_ms': min(windows),
        'windows_at_or_below_2ms': sum(v<=2 for v in windows),
        'semantic_capture_p95_ms': timing['p95_capture_age_ms']})

_, runtime5, trace5, events5, leases5 = load(5)
l5 = {r['sequence']:r for r in leases5}
fault5 = next(r for r in trace5 if r['reason']=='packet_invalid')
token5 = next(r['session'] for r in trace5 if r['armed'])
short = l5[7696]
run5 = {'short_sequence':7696,
        'window_ms':(short['expires_wall']-short['issued_wall'])/MS,
        'native_uncertainty_ms':2,
        'previous_packet_expiry_wall_ns':l5[7695]['expires_wall'],
        'short_packet_expiry_wall_ns':short['expires_wall'],
        'expiry_regression_ms':(l5[7695]['expires_wall']-short['expires_wall'])/MS,
        'same_source_as_previous':short['source_wall']==l5[7695]['source_wall'],
        'next_packet_same_source':short['source_wall']==l5[7697]['source_wall'],
        'next_packet_expiry_restoration_ms':(l5[7697]['expires_wall']-short['expires_wall'])/MS,
        'native_reason':fault5['reason']}

_, runtime6, trace6, events6, leases6 = load(6)
l6 = {r['sequence']:r for r in leases6}
fault6 = next(r for r in trace6 if r['reason']=='lease_expired')
trigger = fault6['trigger_steady_ns']
old_boundary = l6[4129]['expires_wall']-2*MS
sends6 = lines(runtime6/'native-link-sends.jsonl')
sent6 = next(r for r in sends6 if r.get('side')=='worker' and r.get('sequence')==4130)
commands6 = read(runtime6/'commands.json')
checked6 = next(r for r in commands6 if r.get('kind')=='checked' and r.get('bound')==l6[4130]['source_wall'] and r.get('admitted'))
stages = read(runtime6/'stage-timings.json')['pump']
slow = [r for r in stages['slow'] if abs(r['start_steady_ns']-trigger)<50*MS]
run6 = {'native_reason':fault6['reason'],'last_accepted_sequence':4129,
        'native_expiry_wall_ns':old_boundary,
        'next_renewal_sequence':4130,
        'next_renewal_issued_before_native_expiry_ms':(old_boundary-l6[4130]['issued_wall'])/MS,
        'worker_send_before_native_expiry_ms':(old_boundary-sent6['wall_ns'])/MS,
        'issue_to_worker_send_ms':(sent6['wall_ns']-l6[4130]['issued_wall'])/MS,
        'checked_publication_before_expiry_ms':(old_boundary-checked6['source_timestamp'])/MS,
        'checked_callback_before_expiry_ms':(old_boundary-checked6['wall_received'])/MS,
        'callback_to_worker_send_ms':(sent6['wall_ns']-checked6['wall_received'])/MS,
        'source_age_at_worker_send_ms':(sent6['wall_ns']-l6[4130]['source_wall'])/MS,
        'slow_stages_near_expiry':slow,
        'native_zero_latency_ms':(fault6['stop_applied_steady_ns']-trigger)/MS,
        'lease_queue_drops':sum(bool(r.get('dropped')) for r in sends6),
        'receive_timestamp_limit':'Native status retains last receive only, not per-packet recv/lock/accept timestamps. Cannot isolate scheduler vs mutex wait.'}

resources = read(runtime6/'resource-samples.json')['samples']
before = max((r for r in resources if 'processes' in r and r['steady_ns']<trigger-100*MS),key=lambda r:r['steady_ns'])
after = min((r for r in resources if 'processes' in r and r['steady_ns']>trigger),key=lambda r:r['steady_ns'])
run6['scheduling_window_ms']=(after['steady_ns']-before['steady_ns'])/MS
run6['main_thread_scheduling']={}
for pid,b in before['processes'].items():
    a=after['processes'].get(pid)
    if a and 'schedstat' in a and 'schedstat' in b:
        run6['main_thread_scheduling'][pid]={'comm':b['comm'],'parent_pid':b['ppid'],
            'on_cpu_ms':(a['schedstat'][0]-b['schedstat'][0])/MS,
            'run_queue_wait_ms':(a['schedstat'][1]-b['schedstat'][1])/MS}

result={'comparison':comparisons,'run5':run5,'run6':run6}
(OUT/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
replay={'run5':{'previous_packet':packet(l5[7695],token5),'short_packet':packet(short,token5)},
        'run6':{'previous_packet':packet(l6[4129],next(r['session'] for r in trace6 if r['armed'])),
                'renewal':packet(l6[4130],next(r['session'] for r in trace6 if r['armed'])),
                'worker_send_wall':sent6['wall_ns']}}
(OUT/'replay-input.json').write_text(json.dumps(replay,indent=2)+'\n')
print(json.dumps({'comparison':comparisons,'run5':run5,
                 'run6':{k:v for k,v in run6.items() if k!='main_thread_scheduling'}},indent=2))
