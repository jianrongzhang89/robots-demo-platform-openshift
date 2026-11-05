"""Independent native physical stop/trajectory metrics, not contact detection."""
import math


def metrics(trace, events, *, fault_injected_steady_ns=None):
    revoke=next((e for e in reversed(events) if e["event"]=="permission_revoked"),None)
    if not revoke: return {"passed":False,"reason":"missing_revocation"}
    coordinator_trigger=revoke["trigger_steady_ns"]
    trigger=coordinator_trigger
    session_start=next((e["steady_ns"] for e in reversed(events)
        if e["event"]=="arm_requested" and revoke.get("session")
        and e.get("session")==revoke["session"] and e["steady_ns"]<=coordinator_trigger),None)
    lower=(fault_injected_steady_ns if fault_injected_steady_ns is not None else
           session_start if session_start is not None else trigger)
    zero=next((r for r in trace if r["stop_applied_steady_ns"]>=lower and
               r["applied_vx"]==r["applied_wz"]==0),None)
    origin="coordinator"
    if fault_injected_steady_ns is not None or session_start is not None:
        if fault_injected_steady_ns is not None and coordinator_trigger<fault_injected_steady_ns:
            return {"passed":False,"reason":"revoked_before_injection"}
        if not zero: return {"passed":False,"reason":"missing_post_injection_zero"
                            if fault_injected_steady_ns is not None else "missing_session_zero"}
        native_trigger=zero.get("stop_applied_trigger_ns",0)
        if not lower<=native_trigger<=zero["stop_applied_steady_ns"]:
            return {"passed":False,"reason":"native_stop_not_bound_to_injection"
                    if fault_injected_steady_ns is not None else "native_stop_not_bound_to_session"}
        # The native lease can expire first (it has its own clock uncertainty
        # allowance). Bind that event to the same active session, never count
        # a pre-existing or different session's zero as a successful stop.
        before_native=[r for r in trace if r.get("steady_ns",0)<=native_trigger]
        preceding=before_native[-1] if before_native else {}
        if (not revoke.get("session") or preceding.get("session")!=revoke["session"]
                or not preceding.get("armed")
                or not 0<=native_trigger-preceding.get("steady_ns",0)<=50_000_000):
            return {"passed":False,"reason":"native_stop_session_unproven"}
        if native_trigger<coordinator_trigger:
            trigger=native_trigger; origin="native_watchdog"
        if any(r["applied_vx"] or r["applied_wz"] or r.get("armed") or r.get("pending")
               for r in trace if r.get("steady_ns",0)>=zero["stop_applied_steady_ns"]):
            return {"passed":False,"reason":"motion_or_authority_after_native_zero"}
    points={r["physical"]["sequence"]:r["physical"] for r in trace if r.get("physical") and r["physical"]["velocity_valid"]}
    ordered=[points[k] for k in sorted(points)]
    before=[p for p in ordered if p["steady_ns"]<=trigger]
    after=[p for p in ordered if p["steady_ns"]>trigger]
    if not zero or not before or not after: return {"passed":False,"reason":"missing_stop_samples"}
    start=before[-1]; trajectory=[start]+after
    quiet_since=None; stopped=None; distance=0.; coverage=True
    for a,b in zip(trajectory,trajectory[1:]):
        distance+=math.hypot(b["x"]-a["x"],b["y"]-a["y"])
        if not 0<b["steady_ns"]-a["steady_ns"]<=50_000_000: coverage=False
        if b["speed"]<.005 and b["angular_speed"]<.02:
            if quiet_since is None: quiet_since=b["steady_ns"]
            if b["steady_ns"]-quiet_since>=250_000_000:
                stopped=b; break
        else: quiet_since=None
    latency=(zero["stop_applied_steady_ns"]-trigger)/1e6
    gap=(trigger-start["steady_ns"])/1e6
    bounded=all(-.1<=r["applied_vx"]<=.15 and abs(r["applied_wz"])<=.5 for r in trace)
    return {"passed":bool(stopped and coverage and bounded and 0<=latency<=100 and gap<=50),"reason":revoke["reason"],
            "measurement_origin":origin,"first_trigger_to_applied_zero_ms":latency,
            "revoke_to_applied_zero_ms":(zero["stop_applied_steady_ns"]-coordinator_trigger)/1e6,
            "pretrigger_sample_gap_ms":gap,
            "first_trigger_to_confirmed_stationary_ms":(stopped["steady_ns"]-trigger)/1e6 if stopped else None,
            "revoke_to_confirmed_stationary_ms":(stopped["steady_ns"]-coordinator_trigger)/1e6 if stopped else None,
            "sampled_distance_to_confirmed_stationary_m":distance,
            "maximum_applied_forward_mps":max(r["applied_vx"] for r in trace),
            "displacement_m":math.hypot(ordered[-1]["x"]-ordered[0]["x"],ordered[-1]["y"]-ordered[0]["y"]),
            "scope":"normal completion/revocation only; not a fault-matrix qualification"}
