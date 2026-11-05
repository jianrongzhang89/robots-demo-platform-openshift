#!/usr/bin/env python3
"""Render the Phase 6 semantic-on candidate from the Phase 5 guarded candidate.

The Phase 6 "on" arm must differ from the qualified Phase 5 guarded candidate
ONLY by the additive fixed-policy semantic layer in the GLOBAL costmap (soft
cost 200, conservative maximum merge, before inflation). The "off" arm uses the
Phase 5 candidate unchanged, so planner, controller, smoother, collision
monitor, footprint, rates, map and speed caps stay identical between arms.
The layer configuration is the same frozen block proven in the Phase 6D D1/D2
demo (see render_phase6_demo_params.SEMANTIC_CONFIG).

The local costmap deliberately keeps the exact Phase 5 geometry-only
configuration (user-approved October 28, 2026): the local map's semantic
subscription loaded ~26 MB/s of observation clouds into the controller's own
process, whose reader lag then tripped the layer's 500 ms isCurrent window and
blocked the controller's cycle past the 100 ms command authority (pilot-1
pair-1-on-tfdiag/-qosfix). The paired route contrast comes from the global
planner avoiding the mat.
"""
import argparse
import copy
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_phase6_demo_params import SEMANTIC_CONFIG, SEMANTIC_LAYER


def candidate(source, target_cost=200):
    """Return source plus the semantic layer in the global costmap only.

    The default target cost is the qualified soft cost 200. The lethal
    254 variant is the implementation plan's separate exclusion experiment
    ("Evaluate lethal cost 254 as a separate exclusion experiment. A
    model-only restriction is not a production safety boundary.") — it is
    rendered to its own candidate file and selected explicitly.
    """
    if target_cost not in (200, 254):
        raise ValueError("target cost must be the soft cost 200 or the lethal exclusion 254")
    config = copy.deepcopy(source)
    for name in ("global_costmap", "local_costmap"):
        params = config[name][name]["ros__parameters"]
        if SEMANTIC_LAYER in params["plugins"] or SEMANTIC_LAYER in params:
            raise ValueError(f"{name} already contains a semantic layer")
    params = config["global_costmap"]["global_costmap"]["ros__parameters"]
    plugins = params["plugins"]
    plugins.insert(plugins.index("inflation_layer"), SEMANTIC_LAYER)
    config_block = copy.deepcopy(SEMANTIC_CONFIG)
    config_block["target_cost"] = target_cost
    params[SEMANTIC_LAYER] = config_block
    return config


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new file only")
    parser.add_argument("--target-cost", type=int, choices=(200, 254), default=200,
                        help="200 = qualified soft cost (default); 254 = the lethal exclusion experiment")
    args = parser.parse_args()
    source = yaml.safe_load((root / "helm/semantic-navigation/phase5-nav2-candidate.yaml").read_text())
    rendered = candidate(source, target_cost=args.target_cost)
    header = ("# GENERATED Phase 6 semantic-on candidate; differs from the Phase 5\n"
              "# candidate ONLY by the additive semantic_layer in the GLOBAL costmap\n"
              "# (user-approved October 28, 2026: the local map's semantic subscription\n"
              "# loaded ~26 MB/s of observation clouds into the controller's own process,\n"
              "# whose reader lag then tripped the layer's 500 ms isCurrent window and\n"
              "# blocked the controller's cycle past the 100 ms command authority — see\n"
              "# pilot-1 pair-1-on-tfdiag/-qosfix. The paired route contrast comes from\n"
              "# the global planner avoiding the mat; the local costmap keeps the exact\n"
              "# Phase 5 geometry-only configuration). The off arm uses\n"
              "# helm/semantic-navigation/phase5-nav2-candidate.yaml.\n")
    if args.target_cost == 254:
        header += ("# LETHAL-COST EXCLUSION EXPERIMENT (implementation plan: 'Evaluate\n"
                   "# lethal cost 254 as a separate exclusion experiment. A model-only\n"
                   "# restriction is not a production safety boundary.') — target cost 254\n"
                   "# instead of the qualified soft cost 200. Experiment only.\n")
    with args.output.open("x") as handle:
        handle.write(header)
        yaml.safe_dump(rendered, handle, sort_keys=False)
    print({"output": str(args.output), "semantic_layer": rendered[
        "global_costmap"]["global_costmap"]["ros__parameters"][SEMANTIC_LAYER]})


if __name__ == "__main__":
    main()
