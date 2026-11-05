#!/usr/bin/env python3
"""Align private physics gaps with resource counters; correlation, not causation."""
import argparse
import json
from pathlib import Path


def delta(before, after):
    return {key:after[key]-value for key,value in before.items()
            if key in after and isinstance(value,(int,float)) and isinstance(after[key],(int,float))}


def window(samples, start, end):
    before=next((r for r in reversed(samples) if r["end_steady_ns"]<=start),None)
    after=next((r for r in samples if r["steady_ns"]>=end),None)
    if before is None or after is None: return {"covered":False}
    rows=[r for r in samples if before["steady_ns"]<=r["steady_ns"]<=after["steady_ns"]]
    result={"covered":True,"start_steady_ns":before["steady_ns"],"end_steady_ns":after["end_steady_ns"],
            "before_margin_ms":(start-before["end_steady_ns"])/1e6,
            "after_margin_ms":(after["steady_ns"]-end)/1e6,
            "maximum_sample_gap_ms":max((b["steady_ns"]-a["steady_ns"])/1e6
                                          for a,b in zip(rows,rows[1:])),
            "sampling_errors":[r["errors"] for r in rows if r["errors"]]}
    for kind in ("cpu.stat","memory.events"):
        result[kind]=delta(before[kind],after[kind]) if kind in before and kind in after else None
    for kind in ("cpu.pressure","io.pressure","memory.pressure"):
        result[kind]={key:after[kind][key]["total"]-v["total"]
                      for key,v in before.get(kind,{}).items() if key in after.get(kind,{})}
    return result


def analyze(directory):
    resources=json.loads((directory/"resource-samples.json").read_text())
    samples=resources["samples"]
    events=json.loads((directory/"guard-events.json").read_text())["coordinator"]
    arm=next((e["steady_ns"] for e in events if e["event"]=="arm_requested"),None)
    stop=next((e for e in events if e["event"]=="permission_revoked"),None)
    points={}
    for line in (directory/"trace.jsonl").read_text().splitlines():
        row=json.loads(line)
        if row.get("physical"): points[row["physical"]["sequence"]]=row["physical"]
    ordered=sorted(points.values(),key=lambda r:r["steady_ns"])
    gaps=[]
    for a,b in zip(ordered,ordered[1:]):
        duration=(b["steady_ns"]-a["steady_ns"])/1e6
        if duration<40: continue
        gaps.append({"duration_ms":duration,"start_sim_ns":a["sim_ns"],"end_sim_ns":b["sim_ns"],
            "start_steady_ns":a["steady_ns"],"end_steady_ns":b["steady_ns"],
            "overlaps_task":arm is not None and stop is not None
                and b["steady_ns"]>=arm and a["steady_ns"]<=stop["steady_ns"],
            "resource_window":window(samples,a["steady_ns"],b["steady_ns"])})
    return {"scope":"diagnostic correlation only; not qualification or proof of stall cause",
            "arm_steady_ns":arm,"stop":stop,"gaps":gaps,
            "stop_resource_window":window(samples,stop["steady_ns"]-100_000_000,stop["steady_ns"]+100_000_000)
                if stop else None,
            "resource_capacity_reached":resources["capacity_reached"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    report=analyze(args.runtime)
    if args.output:
        with args.output.open("x") as handle: json.dump(report,handle,indent=2)
    else: print(json.dumps(report,indent=2))


if __name__=="__main__": main()
