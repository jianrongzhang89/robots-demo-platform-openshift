# Phase 2 development label-review packet

Status: deferred at user request on 2026-10-15. No review decisions have been recorded. When resumed, review every candidate image and mask without SAM3 predictions; correct or reject labels before scoring.

The 9 prior pilot samples were independently accepted by JZ on 2026-10-15. The following 31 newly captured samples are candidates; they are not accepted ground truth until review decisions are recorded.

| ID | Presence / reason | Episode | Range | View | RGB | Candidate label | Overlay |
|---|---|---|---:|---|---|---|---|
| `ep3-pilot` | positive: visible target | semantic-dev-episode-3-20261015 | 2.00 m | frontal (-0.20 rad) | [RGB](episode-3/pilot/ep3-pilot-0000.jpg) | [mask](episode-3/pilot/target-candidate.png) | — |
| `ep3-pos01` | positive: visible target | semantic-dev-episode-3-20261015 | 2.00 m | oblique (-0.28 rad) | [RGB](episode-3/ep3-pos01/ep3-pos01-0000.jpg) | [mask](episode-3/ep3-pos01/target-candidate.png) | — |
| `ep3-pos04` | positive: visible target | semantic-dev-episode-3-20261015 | 2.00 m | frontal (-0.00 rad) | [RGB](episode-3/ep3-pos04/ep3-pos04-0000.jpg) | [mask](episode-3/ep3-pos04/target-candidate.png) | — |
| `ep3-pos07` | positive: visible target | semantic-dev-episode-3-20261015 | 2.00 m | frontal (+0.24 rad) | [RGB](episode-3/ep3-pos07/ep3-pos07-0000.jpg) | [mask](episode-3/ep3-pos07/target-candidate.png) | — |
| `ep3-pos09` | positive: visible target | semantic-dev-episode-3-20261015 | 1.71 m | frontal (-0.05 rad) | [RGB](episode-3/ep3-pos09/ep3-pos09-0000.jpg) | [mask](episode-3/ep3-pos09/target-candidate.png) | — |
| `ep3-pos12` | positive: visible target | semantic-dev-episode-3-20261015 | 1.41 m | frontal (+0.18 rad) | [RGB](episode-3/ep3-pos12/ep3-pos12-0000.jpg) | [mask](episode-3/ep3-pos12/target-candidate.png) | — |
| `ep3-pos19` | positive: visible target | semantic-dev-episode-3-20261015 | 1.44 m | oblique (+0.49 rad) | [RGB](episode-3/ep3-pos19/ep3-pos19-0000.jpg) | [mask](episode-3/ep3-pos19/target-candidate.png) | — |
| `ep5-pos01` | positive: visible target | semantic-dev-episode-5-20261015 | 2.00 m | frontal (-0.00 rad) | [RGB](episode-5/ep5-pos01/ep5-pos01-0000.jpg) | [mask](episode-5/ep5-pos01/target-candidate.png) | — |
| `ep5-pos02` | positive: visible target | semantic-dev-episode-5-20261015 | 2.00 m | frontal (-0.18 rad) | [RGB](episode-5/ep5-pos02/ep5-pos02-0000.jpg) | [mask](episode-5/ep5-pos02/target-candidate.png) | — |
| `ep5-pos04` | positive: visible target | semantic-dev-episode-5-20261015 | 2.00 m | frontal (+0.22 rad) | [RGB](episode-5/ep5-pos04/ep5-pos04-0000.jpg) | [mask](episode-5/ep5-pos04/target-candidate.png) | — |
| `ep5-pos05` | positive: visible target | semantic-dev-episode-5-20261015 | 1.71 m | frontal (+0.26 rad) | [RGB](episode-5/ep5-pos05/ep5-pos05-0000.jpg) | [mask](episode-5/ep5-pos05/target-candidate.png) | — |
| `ep5-pos06` | positive: visible target | semantic-dev-episode-5-20261015 | 1.43 m | oblique (+0.31 rad) | [RGB](episode-5/ep5-pos06/ep5-pos06-0000.jpg) | [mask](episode-5/ep5-pos06/target-candidate.png) | — |
| `ep3-neg05` | negative: target_out_of_view | semantic-dev-episode-3-20261015 | 1.46 m | oblique (-1.39 rad) | [RGB](episode-3/ep3-neg05/ep3-neg05-0000.jpg) | [mask](episode-3/ep3-neg05/target-candidate.png) | — |
| `ep3-neg06` | negative: target_out_of_view | semantic-dev-episode-3-20261015 | 1.46 m | oblique (-1.77 rad) | [RGB](episode-3/ep3-neg06/ep3-neg06-0000.jpg) | [mask](episode-3/ep3-neg06/target-candidate.png) | — |
| `ep3-neg07` | negative: target_out_of_view | semantic-dev-episode-3-20261015 | 1.46 m | oblique (-2.15 rad) | [RGB](episode-3/ep3-neg07/ep3-neg07-0000.jpg) | [mask](episode-3/ep3-neg07/target-candidate.png) | — |
| `ep3-neg08` | negative: target_out_of_view | semantic-dev-episode-3-20261015 | 1.45 m | oblique (-2.52 rad) | [RGB](episode-3/ep3-neg08/ep3-neg08-0000.jpg) | [mask](episode-3/ep3-neg08/target-candidate.png) | — |
| `ep3-neg09` | negative: ordinary_floor | semantic-dev-episode-3-20261015 | 1.45 m | oblique (-2.90 rad) | [RGB](episode-3/ep3-neg09/ep3-neg09-0000.jpg) | [mask](episode-3/ep3-neg09/target-candidate.png) | — |
| `ep3-neg10` | negative: ordinary_floor | semantic-dev-episode-3-20261015 | 1.45 m | oblique (+2.90 rad) | [RGB](episode-3/ep3-neg10/ep3-neg10-0000.jpg) | [mask](episode-3/ep3-neg10/target-candidate.png) | — |
| `ep3-neg11` | negative: ordinary_floor | semantic-dev-episode-3-20261015 | 1.44 m | oblique (+2.42 rad) | [RGB](episode-3/ep3-neg11/ep3-neg11-0000.jpg) | [mask](episode-3/ep3-neg11/target-candidate.png) | — |
| `ep3-neg12` | negative: ordinary_floor | semantic-dev-episode-3-20261015 | 1.44 m | oblique (+2.14 rad) | [RGB](episode-3/ep3-neg12/ep3-neg12-0000.jpg) | [mask](episode-3/ep3-neg12/target-candidate.png) | — |
| `ep4-tile01` | negative: similar_tile_distractor | semantic-dev-episode-4-20261015 | 2.01 m | oblique (-0.98 rad) | [RGB](episode-4/ep4-tile01/ep4-tile01-0000.jpg) | [mask](episode-4/ep4-tile01/target-candidate.png) | — |
| `ep4-tile02` | negative: similar_tile_distractor | semantic-dev-episode-4-20261015 | 2.01 m | oblique (-1.06 rad) | [RGB](episode-4/ep4-tile02/ep4-tile02-0000.jpg) | [mask](episode-4/ep4-tile02/target-candidate.png) | — |
| `ep4-tile03` | negative: similar_tile_distractor | semantic-dev-episode-4-20261015 | 2.01 m | oblique (-1.14 rad) | [RGB](episode-4/ep4-tile03/ep4-tile03-0000.jpg) | [mask](episode-4/ep4-tile03/target-candidate.png) | — |
| `ep4-tile04` | negative: similar_tile_distractor | semantic-dev-episode-4-20261015 | 2.01 m | oblique (-1.22 rad) | [RGB](episode-4/ep4-tile04/ep4-tile04-0000.jpg) | [mask](episode-4/ep4-tile04/target-candidate.png) | — |
| `ep4-oov02` | negative: target_out_of_view | semantic-dev-episode-4-20261015 | 2.01 m | oblique (-2.37 rad) | [RGB](episode-4/ep4-oov02/ep4-oov02-0000.jpg) | [mask](episode-4/ep4-oov02/target-candidate.png) | — |
| `ep4-oov03` | negative: target_out_of_view | semantic-dev-episode-4-20261015 | 2.01 m | oblique (-2.74 rad) | [RGB](episode-4/ep4-oov03/ep4-oov03-0000.jpg) | [mask](episode-4/ep4-oov03/target-candidate.png) | — |
| `ep5-tile01` | negative: similar_tile_distractor | semantic-dev-episode-5-20261015 | 1.44 m | oblique (-0.67 rad) | [RGB](episode-5/ep5-tile01/ep5-tile01-0000.jpg) | [mask](episode-5/ep5-tile01/target-candidate.png) | — |
| `ep5-tile02` | negative: similar_tile_distractor | semantic-dev-episode-5-20261015 | 1.44 m | oblique (-0.75 rad) | [RGB](episode-5/ep5-tile02/ep5-tile02-0000.jpg) | [mask](episode-5/ep5-tile02/target-candidate.png) | — |
| `ep5-tile03` | negative: similar_tile_distractor | semantic-dev-episode-5-20261015 | 1.44 m | oblique (-0.83 rad) | [RGB](episode-5/ep5-tile03/ep5-tile03-0000.jpg) | [mask](episode-5/ep5-tile03/target-candidate.png) | — |
| `ep5-tile04` | negative: similar_tile_distractor | semantic-dev-episode-5-20261015 | 1.44 m | oblique (-0.91 rad) | [RGB](episode-5/ep5-tile04/ep5-tile04-0000.jpg) | [mask](episode-5/ep5-tile04/target-candidate.png) | — |
| `ep6-tile01` | negative: similar_tile_distractor | semantic-dev-episode-6-20261015 | 2.01 m | oblique (-1.95 rad) | [RGB](episode-6/ep6-tile01/ep6-tile01-0000.jpg) | [mask](episode-6/ep6-tile01/target-candidate.png) | — |

For each candidate, record accept/correct/reject, reviewer initials, date, and final mask SHA-256 in [`review-decisions-template.json`](review-decisions-template.json). The original candidate masks are retained; corrections must be saved as new versioned files.
