#!/usr/bin/env python3
"""Remove lift cabin wall collisions that block the robot entry path."""

import sys
import xml.etree.ElementTree as ET


def main() -> None:
    path = sys.argv[1]
    tree = ET.parse(path)
    root = tree.getroot()
    removed = 0
    for model in root.findall(".//model"):
        if model.get("name") not in {"Lift1", "Lift2"}:
            continue
        for collision in list(model.findall(".//collision")):
            if collision.get("name") == "floor_collision":
                size = collision.find("./geometry/box/size")
                if size is not None:
                    values = size.text.split()
                    if len(values) == 3:
                        values[1] = "3.0"
                        size.text = " ".join(values)
                continue
            parent = next(
                (element for element in model.iter()
                 if collision in list(element)), None)
            if parent is not None:
                parent.remove(collision)
                removed += 1
    tree.write(path, encoding="unicode")
    print(f"removed {removed} lift wall collisions")


if __name__ == "__main__":
    main()
