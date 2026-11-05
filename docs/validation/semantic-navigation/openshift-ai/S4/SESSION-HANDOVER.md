# Session handover — after G4 acceptance

Updated 2026-11-04, end of the G4 qualification-and-acceptance session. **G4 is PASS and user-accepted.** This document hands the work to the next session.

## What this session accomplished

1. **Diagnosed and fixed the attempt-3 armed failure** (semantic-lease renewal race in the fixture's evidence plumbing) and every subsequent failure class across 22 qualification attempts and 20 standalone series attempts — each root-caused with retained evidence, each fix documented at its site and in `S4/report.md`.
2. **Passed all five G4 stages in qualification-22** — serving-faults 12/12 (every wire proof), observation/recovery/moving-stop/semantic-faults 10/10 each (`served-phase5-qualification.json`).
3. **Ran the paired series to a strong evidence position**: 293/309 trials completed across 20 attempts; all 40 nominal off/on pairs completed three times (series-4, 12, 16); all 6 target-absent pairs twice; perfect hull-exposure reduction in every measured pair (series-16: off 28.10 m vs on 0.0 m, zero collisions); the full 110-trial series never completed in one attempt — two characterized residual tails (goal-approach TF ~3.5%/on-arm-trial, with a 0.3→0.5 s tolerance lever available; watchdog command-boundary ~1.6%/armed-trial, no in-policy lever) account for every genuine stop.
4. **User paused the campaign and accepted G4 on that evidence** (November 4). `S4/gate-result.json` records PASS with `accepted: true`, including the verbatim distinction that acceptance rests on the stages, the three nominal sweeps, the exposure reduction and the characterized residuals — not on a completed 110/110 series.
5. **Left the cluster clean**: G4 topology removed, no proxy certificates, A10G rendering reservation Ready, accepted local SAM3 deployment (`semantic-phase6-sam3`) preserved.

## Where everything lives

- **Gate records**: `S0`–`S4` each hold `gate-result.json`; S4's is the acceptance record.
- **Full evidence tree**: `S4/g4-qualification-20261031/` — qualifications 1–22, pilots 1–10, series 1–20 with per-series protocols, and `serving-transport-pilot-1-rationale.md` documenting every fix's rationale.
- **The complete narrative**: `S4/report.md` — every failure diagnosis, every fix, the standing G4 position, and the acceptance record.
- **Commits**: `6f55ca7c` (campaign pause + evidence) and `be091bd2` (acceptance). Working tree clean.

## Key engineering knowledge from this session (not obvious from the tree)

- The 30 Hz G4 candidate runs at **RTF ~0.675** vs the historical Phase 6's ~0.9; four wall-domain parameters were RTF-recalibrated (user-approved, documented at each site): wait-ownership cap 1.5→2.5 s, nav2 transform tolerances 0.2/0.1→0.3/0.15 s, navigation window 90→135 s, controller frequency 40→60 sim-Hz. Any future candidate change needs the same RTF audit.
- The workstation's network has recurring multi-minute outages (~every 2.5–3 h during November 2–3); the harness now survives them via log-based evidence recovery (`TRACE_PHYS` stdout tee + `recover_evidence_from_log` in `run_phase5_native.py`).
- The cluster garbage-collected all Build objects in `semantic-navigation` on November 3; image provenance now falls back to the imagestream-tag digest match (recorded per-trial in `build.json`).
- The adapter node `ip-10-0-53-174` was freed by scaling the leftover `semantic-hotel-sim` to 0 (user-approved; it was consuming 10.9 cores). Keep it at 0 for any G4-class work.
- The model server leaf certificate expires **2026-11-07 02:58:59 UTC** — check and rotate before any further served work.

## What's next (from the proposal)

- **G5 — lifecycle and operations demonstration** (`docs/semantic-navigation-openshift-ai-serving-proposal.md` §S5): registry metadata, dashboards, operator runbook, credential rotation, planned update/rollback (three cycles returning to pinned identity), pod-loss recovery, external egress denial — performed by a new presenter. This is the next milestone after G4.
- **G6 — fleet serving** is the remaining gate after that.
- If the paired-series completion is ever wanted: the two residual levers are documented (the 0.5 s TF tolerance bump is ready; the watchdog race has no in-policy lever), the harness is fully hardened, and the resume protocol is in `S4/HANDOVER.md` §"To resume".

## Rules that still govern

The acceptance criteria, waivers and stop rules in `S4/HANDOVER.md` and `S4/report.md` remain the record. No acceptance criterion was relaxed at any point; all harness fixes were robustness-only and documented. Any new candidate change requires a fresh qualification and retained evidence.
