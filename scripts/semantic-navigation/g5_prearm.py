"""G5-only fresh-setup eligibility with a retained early-failure summary.

G4's classifier deliberately rejects any summary. G5 can additionally establish
no arming from a complete zero-packet trace, empty coordinator/fault histories,
zero results, and the specific pre-arm readiness timeout. No armed retry allowed.
"""
import json
from pathlib import Path


def readiness_setup_failure(directory):
    d=Path(directory)
    try:
        summary=json.loads((d/'runtime/summary.json').read_text())
        worker=json.loads((d/'observer-status.json').read_text())
        leases=worker.get('leases') or {}
        guards=json.loads((d/'runtime/guard-events.json').read_text())
        events=json.loads((d/'runtime/fault-injection-events.json').read_text())
        rows=[json.loads(line) for line in (d/'runtime/trace.jsonl').read_text().splitlines() if line.strip()]
        return bool('WaitTimeout: timeout: SAM3 observation readiness before arming' in (d/'test.log').read_text()
            and summary.get('passed') is False and summary.get('checks')
            and all(c.get('passed') is True for c in summary['checks'])
            and type(worker.get('results')) is int and worker['results']==0
            and 'semantic' in leases and leases['semantic'] is None
            and guards.get('coordinator')==[] and events==[] and rows
            and all(type(row.get('received_packets')) is int and row['received_packets']==0 for row in rows)
            and all(row.get('armed') is False for row in rows))
    except (OSError,ValueError,KeyError,TypeError):return False
