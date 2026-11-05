"""Bounded join for independently delivered native/ROS captures.

Waiting for a clock bracket or raw command never changes its original capture
deadline. It grants NO actuator or publisher authority; runtime callers must
validate provenance before enqueueing and pass resolved rows to the guard.
"""
from safety_core import MS


class CaptureJoiner:
    def __init__(self, ledger, wall_bound, *, capacity=256, wait_ns=20*MS,
                 diagnostics=None, clock=None):
        if type(capacity) is not int or capacity<1 or not 0<wait_ns<=20*MS:
            raise ValueError("bounded join required")
        self.ledger,self.wall_bound=ledger,wall_bound
        self.session=ledger.session
        self.capacity,self.wait_ns=capacity,wait_ns
        self.pending=[]
        # Optional per-row drain diagnostics (pilot-1 off-arm admission-gap
        # investigation): a bounded deque of every drain attempt, recording
        # the phase, the bracket result and the ledger state. Appends are
        # GIL-atomic; None disables. `clock` is diagnostics-only
        # introspection and never participates in the join decision.
        self.diagnostics=diagnostics
        self.clock=clock

    def _diag(self,row,arrival,now,phase,bound,in_entries):
        if self.diagnostics is None: return
        entry={"k":row.get("kind"),"s":row.get("stamp"),"a":arrival,
               "n":now.steady,"w":now.wall,"ros":now.ros,
               "p":phase,"b":bound,"e":in_entries}
        if self.clock is not None:
            last=getattr(self.clock,"last",None)
            samples=getattr(self.clock,"samples",None)
            entry["cl"]=last.get("wall_ns") if last else None
            entry["cs"]=samples[-1][0] if samples else None
            entry["cf"]=getattr(self.clock,"fault",None)
        self.diagnostics.append(entry)

    def receive(self,row,now):
        row.update(admitted=False,bound=None)
        if len(self.pending)>=self.capacity:
            old,_=self.pending.pop(0); old["join_reason"]="capacity_exceeded"
        self.pending.append((row,now.steady))

    def drain(self,now):
        admitted=[]
        if self.ledger.session!=self.session:
            for row,_ in self.pending: row["join_reason"]="session_changed"
            self.pending.clear()
            return admitted
        remaining=[]
        # Raw commands first, by capture, regardless of inter-topic delivery.
        work=sorted(self.pending,key=lambda pair:(pair[0]["kind"]!="raw",pair[0]["stamp"]))
        for row,arrival in work:
            age=now.steady-arrival
            if not 0<=age<=self.wait_ns:
                row["join_reason"]="join_wait_expired"
                self._diag(row,arrival,now,"expired",None,None)
                continue
            stamp,kind=row["stamp"],row["kind"]
            bound=self.wall_bound(stamp,now.wall)
            if bound is None or stamp>now.ros:
                self._diag(row,arrival,now,"wait_bracket",bound,None)
                remaining.append((row,arrival)); continue
            row["bound"]=bound
            if kind=="raw":
                accepted=self.ledger.record(self.session,stamp,bound,row["velocity"],now)
                self._diag(row,arrival,now,"raw_ok" if accepted else "raw_rejected",
                           bound,stamp in self.ledger.entries)
            elif kind=="checked":
                if stamp not in self.ledger.entries:
                    self._diag(row,arrival,now,"wait_source",bound,False)
                    remaining.append((row,arrival)); continue
                accepted=self.ledger.resolve(self.session,stamp,row["velocity"],now) is not None
                self._diag(row,arrival,now,"checked_ok" if accepted else "checked_rejected",
                           bound,True)
            else:
                row["join_reason"]="audit_only"; continue
            row.update(admitted=accepted,processed_wall=now.wall,
                       join_reason="capture_bound" if accepted else "source_rejected_or_expired")
            if accepted: admitted.append(row)
        self.pending=remaining
        return admitted
