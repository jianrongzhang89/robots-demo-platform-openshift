import csv
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from audit_qualification import audit_trial
from audit_routes import audit as audit_route

ARCHIVE=Path(__file__).resolve().parents[2]/'docs/validation/warehouse-energy/phase-0/qualification-20261116/ramp-evidence.tar.gz'
DEVELOPMENT=ARCHIVE.with_name('development-attempts.tar.gz')


class RawAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Raw trace archives were removed from the repository to save
        # storage (see docs/validation/warehouse-energy/README.md);
        # regenerate them with run_matrix.py to run these tests.
        if not ARCHIVE.exists():
            raise unittest.SkipTest(f"raw archive removed for storage: {ARCHIVE.name}")
        with tarfile.open(ARCHIVE) as archive:
            cls.files={name:archive.extractfile('matrix-v1/A-up-p0-r1/'+name).read()
                       for name in ['design.json','world.sdf','physics.jsonl','torque.csv']}

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for name,content in self.files.items():(self.root/name).write_bytes(content)
        self.addCleanup(self.temp.cleanup)

    def test_original_raw_trace_passes(self):
        self.assertEqual(audit_trial(self.root)['status'],'PASS')

    def test_over_limit_torque_fails_even_if_runner_report_says_pass(self):
        with (self.root/'torque.csv').open() as stream:
            rows=list(csv.DictReader(stream))
        rows[20]['left_nm']='0.081'
        with (self.root/'torque.csv').open('w') as output:
            writer=csv.DictWriter(output,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
        (self.root/'result.json').write_text('{"status":"PASS"}')
        self.assertIn('actuator bound/evidence',audit_trial(self.root)['errors'])

    def test_missing_hold_fails(self):
        rows=[json.loads(line) for line in (self.root/'physics.jsonl').read_text().splitlines()]
        for row in rows:
            if row['phase']=='hold':row['phase']='drive'
        (self.root/'physics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.assertIn('stationary observation duration',audit_trial(self.root)['errors'])


class RouteAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DEVELOPMENT.exists():
            raise unittest.SkipTest(f"raw archive removed for storage: {DEVELOPMENT.name}")
        with tarfile.open(DEVELOPMENT) as archive:
            cls.files={name:archive.extractfile('navigation-series-v1/A-up/'+name).read()
                       for name in ['design.json','result.json','task-request.json','physical.jsonl',
                         'adapter-events.jsonl','schedule-mirror.jsonl','plans.jsonl','itineraries.jsonl','torque.csv']}

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for name,content in self.files.items():(self.root/name).write_bytes(content)
        self.addCleanup(self.temp.cleanup)

    def test_recorded_route_passes(self):
        self.assertEqual(audit_route(self.root)['status'],'PASS')

    def test_submitted_itinerary_without_schedule_acceptance_fails(self):
        (self.root/'schedule-mirror.jsonl').write_text('')
        self.assertIn('schedule missing or outside corridor',audit_route(self.root)['errors'])

    def test_missing_nav2_result_identity_fails(self):
        rows=[json.loads(line) for line in (self.root/'adapter-events.jsonl').read_text().splitlines()]
        for row in rows:
            if row['event']=='nav2_terminal':row['goal_id']=''
        (self.root/'adapter-events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.assertIn('missing or failed Nav2 goal results',audit_route(self.root)['errors'])


if __name__=='__main__':unittest.main()
