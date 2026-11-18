#!/usr/bin/env python3
"""Unit tests for the energy demonstration summary generation."""
import json
import unittest
from pathlib import Path

from run_energy_demo import build_html, svg_chart, svg_map

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "config/warehouse-energy/fixture-v1.json").read_text())

EVIDENCE = {
    "date": "2026-11-18 00:00 UTC",
    "deliveries": [
        {"label": "Delivery 1: arm A", "route": "A", "predicted": 0.95,
         "observed": 0.877, "error": -0.073, "duration_s": 314.0,
         "estimator_mode": "physics", "snapshots_dir": "/nonexistent", "final_soc": 0.77},
        {"label": "Delivery 2: arm B", "route": "A", "predicted": 0.95,
         "observed": 0.877, "error": -0.073, "duration_s": 314.0,
         "estimator_mode": "physics", "snapshots_dir": "/nonexistent", "final_soc": 0.77},
        {"label": "Delivery 3: arm C", "route": "A", "predicted": 0.88,
         "observed": 0.877, "error": -0.003, "duration_s": 314.0,
         "estimator_mode": "served", "snapshots_dir": "/nonexistent", "final_soc": 0.77},
    ],
    "payload_sensitivity": [
        {"payload_kg": 0.0, "route": "A", "physics_wh": 0.475, "served_wh": 0.44,
         "predicted_final_soc": 0.777},
        {"payload_kg": 0.5, "route": "A", "physics_wh": 0.476, "served_wh": 0.441,
         "predicted_final_soc": 0.777},
    ],
    "fallback": {"route": "A", "observed_wh": 0.438, "duration_s": 157.0,
                 "estimator_mode": "fallback"},
}


class DemoSummaryTest(unittest.TestCase):
    def test_svg_map_contains_all_nodes(self):
        svg = svg_map(FIXTURE)
        for node in FIXTURE["geometry"]["nodes"]:
            self.assertIn(f">{node}<", svg)
        self.assertIn("Route A", svg)
        self.assertIn("Route B", svg)

    def test_svg_chart_bars(self):
        svg = svg_chart(EVIDENCE["deliveries"])
        self.assertIn("predicted vs consumed", svg)
        self.assertEqual(svg.count("<rect"), 7)  # background plus two bars per delivery

    def test_html_summary_structure(self):
        html = build_html(EVIDENCE, FIXTURE)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Energy-aware warehouse delivery demonstration", html)
        self.assertIn("Delivery 3: arm C", html)
        self.assertIn("serving endpoint unavailable", html)
        self.assertIn("no energy saving is claimed", html)
        for row in EVIDENCE["payload_sensitivity"]:
            self.assertIn(f"{row['served_wh']:.4f}", html)


if __name__ == "__main__":
    unittest.main()
