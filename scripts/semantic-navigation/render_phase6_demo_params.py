#!/usr/bin/env python3
"""Render an opt-in semantic demo overlay without changing hotel Nav2 behavior.

This is a local configuration candidate only. It does not deploy or authorize
motion. The original Nav2 parameters are copied verbatim except for adding the
semantic layer to both costmaps before inflation.
"""
import argparse
import copy
from pathlib import Path

import yaml


SEMANTIC_LAYER = "semantic_layer"
SEMANTIC_CONFIG = {
    "plugin": "demo_semantic_costmap::SemanticLayer",
    "enabled": True,
    "topic_prefix": "/robot_1/semantic",
    "observation_lifetime": 1.0,
    "max_capture_age": 0.5,
    "target_cost": 200,
    "optical_frame": "camera_color_optical_frame",
}


def candidate(source):
    """Return source plus only the fixed-policy semantic costmap additions."""
    config = copy.deepcopy(source)
    for name in ("global_costmap", "local_costmap"):
        params = config[name][name]["ros__parameters"]
        plugins = params["plugins"]
        if SEMANTIC_LAYER in plugins or SEMANTIC_LAYER in params:
            raise ValueError(f"{name} already contains a semantic layer")
        inflation_index = plugins.index("inflation_layer")
        plugins.insert(inflation_index, SEMANTIC_LAYER)
        params[SEMANTIC_LAYER] = copy.deepcopy(SEMANTIC_CONFIG)
    return config


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new file only")
    args = parser.parse_args()

    source = yaml.safe_load((root / "config/nav2/hotel_nav2_params.yaml").read_text())
    rendered = candidate(source)
    with args.output.open("x") as handle:
        handle.write(
            "# GENERATED Phase 6 demo-only Nav2 candidate; local preflight only.\n"
            "# Not deployed, motion-qualified, or a production safety profile.\n"
        )
        yaml.safe_dump(rendered, handle, sort_keys=False)


if __name__ == "__main__":
    main()
