"""Measure zero-only Wait after the native actuator applies normalization."""


def wait_zero_metrics(trace, first_hold, end, session):
    failed={"passed":False,"reason":"missing_wait_native_evidence","native_samples":0}
    if first_hold is None or end is None or not session: return failed
    rows=[r for r in trace if first_hold<=r.get("steady_ns",0)<=end]
    first=next((i for i,r in enumerate(rows) if r["applied_vx"]==r["applied_wz"]==0
                and first_hold<=r["applied_steady_ns"]<=r["steady_ns"]),None)
    if first is None: return failed
    latency=(rows[first]["applied_steady_ns"]-first_hold)/1e6
    held=rows[first:]
    maximum=max(max(abs(r["applied_vx"]),abs(r["applied_wz"])) for r in held)
    gap=max(((b["steady_ns"]-a["steady_ns"])/1e6 for a,b in zip(rows,rows[1:])),default=0.)
    # A hold enqueued in Python is not instant actuation. Only the already
    # permitted <=0.005 settling tail may precede native zero; never accept
    # renewed motion after native zero, lost authority, or missing coverage.
    passed=(len(held)>=10 and 0<=latency<=100 and rows[0]["steady_ns"]-first_hold<=50_000_000
            and 0<=gap<=50 and end-rows[-1]["steady_ns"]<=50_000_000
            and all(r.get("session")==session and r.get("armed") and not r.get("pending") for r in rows)
            and all(max(abs(r["applied_vx"]),abs(r["applied_wz"]))<=.005 for r in rows[:first])
            and maximum==0)
    return {"passed":bool(passed),"reason":"native_zero_hold" if passed else "wait_zero_contract_failed",
            "native_samples":len(held),"normalization_to_native_zero_ms":latency,
            "pre_zero_samples":first,"maximum_abs_applied_velocity":maximum,
            "maximum_sample_gap_ms":gap}
