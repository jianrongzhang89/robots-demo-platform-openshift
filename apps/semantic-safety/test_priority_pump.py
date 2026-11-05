import unittest

from priority_pump import StageTimings, audit_timing, pump_round


class PriorityPumpTests(unittest.TestCase):
    def test_timing_returns_value_and_retains_bounded_slow_samples(self):
        ticks=iter((0,20,30,31,40,60))
        timings=StageTimings(now=lambda:next(ticks),threshold_ns=10,capacity=1)
        self.assertEqual(timings.call("ingress",lambda:42),42)
        timings.call("ingress",lambda:None)
        timings.call("ingress",lambda:None)
        self.assertEqual(timings.stages["ingress"],{"calls":3,"maximum_ns":20})
        self.assertEqual(len(timings.slow),1)
        self.assertEqual(timings.dropped,1)

    def test_timing_preserves_exception_and_records_duration(self):
        ticks=iter((0,20))
        timings=StageTimings(now=lambda:next(ticks),threshold_ns=10)
        def fail(): raise RuntimeError("original failure")
        with self.assertRaisesRegex(RuntimeError,"original failure"):
            timings.call("guard",fail)
        self.assertEqual(timings.slow[0]["stage"],"guard")

    def test_dictionary_metadata_does_not_overwrite_original_source(self):
        row={"source_timestamp":80,"received_timestamp":85,"stamp":70}
        row.update(audit_timing({"source_timestamp":90,"received_timestamp":95},100))
        self.assertEqual(row,{"source_timestamp":80,"received_timestamp":85,"stamp":70,
                              "wall_received":100,"audit_source_timestamp":90,
                              "audit_received_timestamp":95})

    def test_bounded_priority_and_guard_before_diagnostics(self):
        calls=[]
        callbacks={name:(lambda n=name:calls.append(n)) for name in
                   ("ingress","observer","task","native","guard","diagnostics")}
        pump_round(**callbacks)
        self.assertEqual(calls,["native"]+(["ingress"]*4+
                         ["task","native","guard","observer","native"])*4+
                         ["diagnostics"])

    def test_pending_renewal_precedes_slow_observers_and_survives_native_deadline(self):
        # Recording run 6 lost continuity with an old lease while a valid
        # renewal waited behind other work. Use the real receiver and a
        # deterministic 24 ms observer batch, not a wall-clock sleep.
        from safety_core import Command, FinalReceiver, MS, Now
        session="00000000-0000-4000-a000-000000000001"
        elapsed=[0]
        def now(): return Now((1000+elapsed[0])*MS,(10000+elapsed[0])*MS,(2000+elapsed[0])*MS)
        receiver=FinalReceiver()
        self.assertTrue(receiver.arm(session,now(),stationary=True))
        self.assertTrue(receiver.receive(Command(session,0,now().wall,now().wall+20*MS,(.1,0.,0.)),now()))
        def observer():
            elapsed[0]+=6
            receiver.tick(now())
        sequence=[0]
        def guard():
            sequence[0]+=1
            renewal=Command(session,sequence[0],now().wall,now().wall+15*MS,(.1,0.,0.))
            self.assertTrue(receiver.receive(renewal,now()))
        pump_round(ingress=lambda:None,task=lambda:None,native=lambda:None,
                   guard=guard,observer=observer,diagnostics=lambda:None)
        self.assertEqual(receiver.session,session)
        # Scheduling never lets the last accepted lease run indefinitely.
        elapsed[0]=104
        self.assertEqual(receiver.tick(now()),(0.,0.,0.))
        self.assertEqual(receiver.reason,"lease_expired")

    def test_sustained_audit_traffic_does_not_accumulate_behind_observers(self):
        from collections import deque
        pending=deque()
        processed=[]
        for round_number in range(100):
            # Eight arrivals per observer round, interspersed with executor
            # polls that only advance the ready-set iterator.
            pending.extend([round_number]*8)
            polls=[0]
            def ingress():
                polls[0]+=1
                if polls[0]%2==0 and pending:
                    processed.append(round_number-pending.popleft())
            pump_round(ingress=ingress,observer=lambda:None,task=lambda:None,
                       native=lambda:None,guard=lambda:None,diagnostics=lambda:None)
        self.assertFalse(pending)
        self.assertEqual(max(processed),0)

    def test_busy_ingress_cannot_starve_other_work(self):
        counts={name:0 for name in ("ingress","observer","task","native","guard","diagnostics")}
        def call(name): counts[name]+=1
        for _ in range(16):
            pump_round(**{name:(lambda n=name:call(n)) for name in counts})
        self.assertEqual(counts,{"ingress":256,"observer":64,"task":64,
                                 "native":144,"guard":64,"diagnostics":16})


if __name__=="__main__": unittest.main()
