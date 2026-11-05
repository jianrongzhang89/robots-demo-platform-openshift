"""Offline analysis of DISARMED command evidence; never grants motion authority."""
import argparse
import json
from pathlib import Path
from safety_core import COMMAND_NS, UNCERTAINTY_NS


def analyze(commands):
    raw=[r for r in commands if r["kind"]=="raw"]
    if not raw or raw[-1]["velocity"]!=[0,0,0]:
        raise ValueError("requires terminal raw zero; otherwise window is ambiguous")
    cutoff=raw[-1]["source_timestamp"]
    checked=[r for r in commands if r["kind"]=="checked" and r["source_timestamp"]<cutoff]
    eligible=sorted([r for r in checked if r["admitted"] and r["processed_wall"]<cutoff],
                    key=lambda r:r["processed_wall"])
    if not eligible: raise ValueError("no capture-eligible output")
    end=None; gaps=[]
    for row in eligible:
        start=row["processed_wall"]
        deadline=row["bound"]+COMMAND_NS-UNCERTAINTY_NS
        if deadline<=start: raise ValueError("eligible record already expired")
        if end is not None and start>end:
            gaps.append({"from_wall":end,"to_wall":start,"duration_ms":(start-end)/1e6})
        end=max(end or 0,deadline)
    return {"qualification":"offline optimistic command-authority coverage; NOT actuator or publisher qualification",
        "window":"first eligible checked command to last eligible checked command before terminal raw zero",
        "terminal_zero_source_wall":cutoff,"checked_before_terminal_zero":len(checked),
        "eligible_checked_before_terminal_zero":len(eligible),"source_lifetime_ms":COMMAND_NS/1e6,
        "uncertainty_ms":UNCERTAINTY_NS/1e6,"gaps":gaps,
        "maximum_gap_ms":max((g["duration_ms"] for g in gaps),default=0),
        "continuous_coverage":not gaps,
        "limitation":"uses original wall capture bounds; omits later supervisor/lease scheduling, so coverage is optimistic"}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commands",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=analyze(json.loads(args.commands.read_text()))
    with args.output.open("x") as handle: json.dump(result,handle,indent=2)
    print(json.dumps(result))
