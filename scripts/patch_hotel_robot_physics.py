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
    canonical = robot.find("canonical_link")
    if canonical is None:
        canonical = ET.Element("canonical_link")
        robot.insert(1, canonical)
    canonical.text = "base_link"
    footprint_inertial = robot.find(".//link[@name='base_footprint']/inertial")
    if footprint_inertial is not None:
        mass = footprint_inertial.find("mass")
        if mass is not None:
            mass.text = "0.1"
        inertia = footprint_inertial.find("inertia")
        if inertia is not None:
            for name in ("ixx", "iyy", "izz"):
                value = inertia.find(name)
                if value is not None:
                    value.text = "0.001"
    changed = 0
    for friction in robot.findall(".//friction"):
        for element in friction.findall("./ode") + friction.findall("./bullet"):
            for name in ("mu", "mu2", "friction", "friction2"):
                value = element.find(name)
                if value is not None and float(value.text) > 10.0:
                    value.text = "1.0"
                    changed += 1
    if changed == 0:
        print("no excessive robot wheel friction values found")
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
