#!/usr/bin/env python3
"""Additional attribution proof: actual pod deletion must precede guarded stop."""
import argparse
import json
from pathlib import Path


def evaluate(result, events, replacement, expected_digest):
    injections=[e for e in result.get('events',[]) if e.get('event')=='delete_serving_pod']
    motion=next((e for e in events if e.get('event')=='semantic_fault_injected'),{})
    stopped=next((e for e in events if e.get('event')=='guard_stopped_after_semantic_fault'),{})
    native=motion.get('native_status') or {};physical=native.get('physical') or {}
    stop_wall=(motion.get('wall_ns',0)+stopped.get('steady_ns',0)-motion.get('steady_ns',0)) if motion and stopped else 0
    injection=injections[0] if len(injections)==1 else {}
    at=injection.get('fixture_delete_upper_ns',0)
    lower=injection.get('fixture_delete_lower_ns',0)
    checks={'fixture_gate':result.get('fixture_passed') is True,
        'one_real_deletion':len(injections)==1,
        'verified_motion':native.get('armed') is True and native.get('applied_vx',0)>.02 and physical.get('velocity_valid') is True and physical.get('speed',0)>.02,
        'delete_before_stop':bool(motion and stopped and motion['wall_ns']<=lower<=at<stop_wall),
        'replacement_uid':bool(replacement) and replacement.get('metadata',{}).get('uid')!=injection.get('uid'),
        'replacement_identity':any(c.get('name')=='kserve-container' and c.get('imageID','').endswith('@'+expected_digest) for c in replacement.get('status',{}).get('containerStatuses',[])),
        'cleanup':result.get('cleanup_ok') is True}
    return {'passed':all(checks.values()),'checks':checks,'deletion_to_stop_ms':(stop_wall-at)/1e6 if at and stop_wall else None,
        'timing_note':'Stop wall time reconstructed from fixture wall/steady anchor. Deletion interval is anchored in the fixture clock and conservatively spans the full host-monotonic command round trip; no host/fixture wall-clock equality assumed.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();d=a.run_dir
    r=evaluate(json.loads((d/'result.json').read_text()),json.loads((d/'trial/runtime/fault-injection-events.json').read_text()),json.loads((d/'serving-replacement.json').read_text()),json.loads((d/'protocol.json').read_text())['model_identity']['container_digest'])
    with (d/'attribution.json').open('x') as h:h.write(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r));return 0 if r['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
