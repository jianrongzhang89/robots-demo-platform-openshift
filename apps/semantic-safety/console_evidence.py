"""Fail-closed evidence contract for the private console-only Gazebo candidate."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

EXECUTABLE=Path("/opt/semantic-safety/bin/phase5_console_server")


def lifecycle_complete(log_text):
    markers=("stop_begin","stop_end","stop_worker_joined","destructor_begin","destructor_end")
    positions={name:log_text.find("phase5 lifecycle: "+name) for name in markers}
    returned=log_text.find("phase5 lifecycle: run_returned result=0")
    ordered=list(positions.values())
    return {"passed":all(p>=0 for p in ordered) and ordered==sorted(ordered)
            and 0<=returned<positions["stop_worker_joined"],
            "marker_positions":positions,"run_returned_position":returned}


def validate_world(text):
    root=ET.fromstring(text)
    if root.tag!="sdf" or len(root.findall("world"))!=1:
        raise ValueError("console fixture requires exactly one SDF world")
    for plugin in root.iter("plugin"):
        name=plugin.get("name","").lower()
        filename=plugin.get("filename","").lower()
        if "logrecord" in name or "logplayback" in name or "log-system" in filename:
            raise ValueError("world recording/playback plugin forbidden in console-only fixture")


def recording_absent(output, maps=""):
    files=sorted(str(p.relative_to(output)) for p in output.rglob("*") if ".tlog" in p.name)
    libraries=sorted({line.split()[-1] for line in maps.splitlines()
                      if "log-system" in line.lower()})
    return {"passed":not files and not libraries,"recording_files":files,
            "recording_libraries":libraries}


def identity(pid, expected_sources, *, proc=Path("/proc"), executable=EXECUTABLE,
             source=Path("/opt/semantic-safety/console-launcher")):
    actual=(proc/str(pid)/"exe").resolve(strict=True)
    maps=(proc/str(pid)/"maps").read_text()
    installed={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in expected_sources}
    return {"passed":bool(expected_sources) and actual==executable.resolve(strict=True) and installed==expected_sources,
            "executable":str(actual),"sha256":hashlib.sha256(actual.read_bytes()).hexdigest(),
            "source_hashes":installed,"maps":maps}
