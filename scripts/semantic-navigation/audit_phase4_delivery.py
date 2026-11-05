#!/usr/bin/env python3
"""Correlate publisher logs with recorded costmap updates in a stable epoch.

Run before private-pod cleanup. Preserve the selected publisher records as raw
evidence; this is published-to-applied yield, not raw-camera admission yield.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with gzip.open(args.updates, "rt") as handle:
        rows = [json.loads(line) for line in handle]
    names = ("global_semantic", "local_semantic")
    applied = {}
    for name in names:
        epochs = {row["maps"][name]["epoch"] for row in rows}
        assert len(epochs) == 1, "delivery interval crosses a layer epoch"
        applied[name] = {row["maps"][name]["last"]["stamp_ns"] for row in rows
                         if row["maps"][name]["last"] and "costmap_wall_ns" in row["maps"][name]["last"]}
    low = max(min(stamps) for stamps in applied.values())
    high = min(max(stamps) for stamps in applied.values())
    wall = min(row["maps"][names[0]]["last"]["capture_wall_ns"] for row in rows)
    since = dt.datetime.fromtimestamp(wall/1e9, dt.timezone.utc).isoformat()
    text = subprocess.check_output(["oc","logs","-n","semantic-navigation","semantic-phase4-inference",
                                    "-c","sam3-inference","--timestamps","--since-time="+since],text=True)
    publications = []
    for line in text.splitlines():
        try:
            record = json.loads(line[line.index("{"):])
        except (ValueError,TypeError):
            continue
        if record.get("event") == "valid_result" and low <= record["capture_stamp_ns"] <= high:
            publications.append({"log_timestamp":line.split(" ",1)[0],"record":record})
    published = {row["record"]["capture_stamp_ns"] for row in publications}
    assert published, "no matching publisher evidence"
    raw = args.output_dir/"publications.jsonl.gz"
    with gzip.open(raw,"wt") as handle:
        for row in publications:
            handle.write(json.dumps(row,separators=(",",":"))+"\n")
    report = {"window":"inclusive common capture-stamp interval, wall-filtered to exclude pre-reset stamp reuse",
              "first_stamp_ns":low,"last_stamp_ns":high,"log_since_utc":since,
              "published_unique":len(published),"publication_duplicates":len(publications)-len(published),
              "raw_sha256":hashlib.sha256(raw.read_bytes()).hexdigest(),"maps":{}}
    for name, stamps in applied.items():
        stamps = {s for s in stamps if low <= s <= high}
        report["maps"][name] = {"applied_unique":len(stamps),"missing_stamps":sorted(published-stamps),
            "unexpected_stamps":sorted(stamps-published),"published_to_applied_percent":len(published & stamps)/len(published)*100}
    (args.output_dir/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
