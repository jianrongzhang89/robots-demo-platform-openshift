#!/usr/bin/env python3
"""Stabilize the pre-spawned robot's wheel contacts for lift travel."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def main() -> None:
    path = sys.argv[1]
    tree = ET.parse(path)
    root = tree.getroot()
    robot = root.find(".//model[@name='robot_1']")
    if robot is None:
        raise RuntimeError("robot_1 model not found")
    changed = 0
    for friction in robot.findall(".//friction"):
        for element in friction.findall("./ode") + friction.findall("./bullet"):
            for name in ("mu", "mu2", "friction", "friction2"):
                value = element.find(name)
                if value is not None and float(value.text) > 10.0:
                    value.text = "1.0"
                    changed += 1
    if changed == 0:
        raise RuntimeError("no excessive robot wheel friction values found")
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
