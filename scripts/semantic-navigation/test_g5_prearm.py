import json
from pathlib import Path
import tempfile
import unittest
from g5_prearm import readiness_setup_failure

class PrearmTests(unittest.TestCase):
    def test_explicit_zero_packet_proof_and_armed_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory);(d/'runtime').mkdir()
            for name,value in {'runtime/summary.json':{'passed':False,'checks':[{'passed':True}]},'observer-status.json':{'results':0,'leases':{'semantic':None}},'runtime/guard-events.json':{'coordinator':[]},'runtime/fault-injection-events.json':[]}.items():
                (d/name).write_text(json.dumps(value))
            (d/'test.log').write_text('WaitTimeout: timeout: SAM3 observation readiness before arming')
            trace=d/'runtime/trace.jsonl';trace.write_text(json.dumps({'received_packets':0,'armed':False})+'\n')
            self.assertTrue(readiness_setup_failure(d))
            for row in [{'received_packets':1,'armed':False},{'received_packets':0,'armed':True},{}]:
                trace.write_text(json.dumps(row)+'\n');self.assertFalse(readiness_setup_failure(d))
            trace.write_text(json.dumps({'received_packets':0,'armed':False})+'\n'+json.dumps({'armed':False})+'\n')
            self.assertFalse(readiness_setup_failure(d))
            trace.write_text(json.dumps({'received_packets':0,'armed':False})+'\n')
            for worker in [{'results':False,'leases':{'semantic':None}},{'results':0,'leases':{}}]:
                (d/'observer-status.json').write_text(json.dumps(worker))
                self.assertFalse(readiness_setup_failure(d))

if __name__=='__main__':unittest.main()
