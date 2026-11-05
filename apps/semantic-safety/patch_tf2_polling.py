#!/usr/bin/env python3
"""Reduce only TF2's blocking advanced-lookup poll interval for a private test."""
import re
import sys
from pathlib import Path


SLEEP_10MS = "std::this_thread::sleep_for(std::chrono::milliseconds(10));"
SLEEP_1MS = "std::this_thread::sleep_for(std::chrono::milliseconds(1));"
ADVANCED_LOOKUP = re.compile(
    r"bool\s+Buffer::canTransform\(\s*"
    r"const std::string\s*&\s*target_frame,\s*"
    r"const tf2::TimePoint\s*&\s*target_time,\s*"
    r"const std::string\s*&\s*source_frame,\s*"
    r"const tf2::TimePoint\s*&\s*source_time,\s*"
    r"const std::string\s*&\s*fixed_frame,",
    re.DOTALL,
)


def patch_file(path: Path) -> None:
    source = path.read_text()
    match = ADVANCED_LOOKUP.search(source)
    if match is None or ADVANCED_LOOKUP.search(source, match.end()) is not None:
        raise RuntimeError("expected exactly one advanced two-time canTransform overload")
    end = source.find("TransformStampedFuture", match.end())
    if end < 0:
        raise RuntimeError("could not locate end of advanced canTransform overload")
    block = source[match.start():end]
    if block.count(SLEEP_10MS) != 1 or SLEEP_1MS in block:
        raise RuntimeError("expected one unpatched 10 ms sleep in advanced canTransform")
    patched = block.replace(SLEEP_10MS, SLEEP_1MS, 1)
    path.write_text(source[:match.start()] + patched + source[end:])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_tf2_polling.py /path/to/tf2_ros/src/buffer.cpp")
    patch_file(Path(sys.argv[1]))
