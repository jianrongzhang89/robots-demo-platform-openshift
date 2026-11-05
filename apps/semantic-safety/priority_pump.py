"""Bounded single-thread callback scheduling; no timing/authority decisions.

Command ingress has its own executor. Each of four groups services four
command polls, task responses, native captures and the guard before one
observer callback. This bounds audit backlog and prevents a full observer
batch from consuming a short native lease. All callbacks stay on one thread;
no source timestamps or safety deadlines are changed.
"""
import time


class StageTimings:
    """Bounded diagnostics only; never supplies time or authority to the guard."""
    def __init__(self, *, now=time.monotonic_ns, threshold_ns=10_000_000, capacity=2000):
        self.now, self.threshold_ns, self.capacity = now, threshold_ns, capacity
        self.stages, self.slow, self.dropped = {}, [], 0

    def call(self, stage, callback):
        start = self.now()
        try:
            return callback()
        finally:
            end = self.now()
            duration = end-start
            stats = self.stages.setdefault(stage, {"calls":0, "maximum_ns":0})
            stats["calls"] += 1
            stats["maximum_ns"] = max(stats["maximum_ns"], duration)
            if duration >= self.threshold_ns:
                if len(self.slow) < self.capacity:
                    self.slow.append({"stage":stage, "start_steady_ns":start,
                                      "end_steady_ns":end, "duration_ns":duration})
                else:
                    self.dropped += 1

    def report(self):
        return {"stages":self.stages, "slow":self.slow, "dropped":self.dropped,
                "threshold_ns":self.threshold_ns}


def audit_timing(info, callback_wall):
    """Installed rclpy passes MessageInfo as a dictionary; audit hop only."""
    return {"wall_received":callback_wall,
            "audit_source_timestamp":info["source_timestamp"],
            "audit_received_timestamp":info["received_timestamp"]}


def pump_round(*, ingress, observer, task, native, guard, diagnostics):
    native()
    for _ in range(4):
        for _ in range(4):
            ingress()
        task()
        native()
        guard()
        observer()
        native()
    diagnostics()
