# Warehouse energy evidence: storage policy

**Date:** November 18, 2026

This directory holds the audited evidence for warehouse energy Stages 0–4
and the operator demonstration. To keep the repository lean, the bulky
**raw runtime artifacts** are not stored in git:

- **Raw trace archives** (`*.tar.gz` of full trial directories) were
  generated, SHA-256-recorded in each stage's evidence manifest at
  execution time, and then removed from the repository. Their digests
  remain in the `removed_raw_archives` sections of the manifests below.
- **Process logs** (`ros-logs/`, `gazebo.log`, `nav2.log`, bridge and
  dispatcher logs) were removed from the retained trial directories; the
  substantive evidence — traces, audits, results, selection records,
  manifests, reports, and the Phase 1 semantic capture images — is kept.

Regenerate any raw evidence with the committed sweep tooling
(`scripts/warehouse-energy/README.md`):

| Removed archive | Regenerate with |
| --- | --- |
| `phase-0/qualification-20261116/ramp-evidence.tar.gz` | `run_matrix.py` + `audit_qualification.py` |
| `phase-0/qualification-20261116/navigation-evidence.tar.gz` | `run_navigation_matrix.py` |
| `phase-1/phase1-telemetry-series-v1.tar.gz` | `run_navigation.py` series + `audit_phase1.py` |
| `phase-3a/stage3-raw-v1.tar.gz` | `stage3-sweep.sh` + `build_stage3_dataset.py` |
| `phase-4/stage4-series-v1.tar.gz` | `run_stage4_series.py` |
| `demo/energy-demo-v1.tar.gz` | `run_energy_demo.py` |

The retained loose evidence per stage: audits, gate results, reports,
evidence manifests, frozen configurations, per-trial selection and result
records, and (Phase 1) the semantic RGB/mask capture pairs underlying the
reviewer-accepted repeatability series. Everything is reproducible from
the committed scripts and frozen configurations on the pinned cluster
runtime.
