#!/usr/bin/env python3
"""Render D1 resources, embedding the exact reviewed Nav2 candidate params."""
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "helm/semantic-navigation/phase6-demo-d1.yaml"
PARAMS = ROOT / "helm/semantic-navigation/phase6-demo-nav2-candidate.yaml"


def render_documents():
    documents = list(yaml.safe_load_all(MANIFEST.read_text()))
    documents[0]["data"]["phase6-demo-nav2-candidate.yaml"] = PARAMS.read_text()
    return documents


if __name__ == "__main__":
    yaml.safe_dump_all(render_documents(), sys.stdout, sort_keys=False)
