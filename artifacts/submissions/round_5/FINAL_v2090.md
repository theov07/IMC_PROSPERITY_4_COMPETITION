# R5 FINAL CHAMPION — best_v2090_revive_space_gray

## Performance — 959,945 PnL

| Metric | Backtest 3-day | vs v2010 | vs v1611 | vs v10 |
|---|---:|---:|---:|---:|
| **PnL Total** | **959,945** | **+4,193** | **+79,220** | **+112,265** |
| Max DD | 23,830 (8.6%) | 0 | -4,531 | -4,531 |
| Day 4 (LIVE) DD | 16,412 (4.7%) | 0 | -4.9pp | -4.9pp |

## Composition (now 46 active products)

15 pair_skip overlays:

| Pair (lagger ← leader) | Group | PnL |
|---|---|---:|
| PEBBLES_S ← PEBBLES_XL | PEBBLES | +62k |
| MICROCHIP_RECTANGLE ← SQUARE | MICROCHIP | +26k |
| MICROCHIP_CIRCLE ← OVAL | MICROCHIP | +19k |
| MICROCHIP_OVAL ← TRIANGLE | MICROCHIP | +12k |
| ROBOT_LAUNDRY ← VACUUMING | ROBOT | +17k |
| SLEEP_POD_SUEDE ← NYLON | SLEEP_POD | +19k |
| SLEEP_POD_COTTON ← NYLON | SLEEP_POD | +20k |
| UV_VISOR_RED ← AMBER | UV_VISOR | +20k |
| UV_VISOR_ORANGE ← YELLOW | UV_VISOR | +21k |
| TRANSLATOR_ECLIPSE ← VOID | TRANSLATOR | +12k |
| **TRANSLATOR_SPACE_GRAY ← VOID (revive)** | TRANSLATOR | **+4k** |
| GALAXY_DARK_MATTER ← PLANETARY | GALAXY | +11k |
| GALAXY_BLACK_HOLES ← PLANETARY | GALAXY | +16k |
| SNACKPACK_VANILLA ← CHOCOLATE | SNACKPACK | +4k |
| SNACKPACK_RASPBERRY ← STRAWBERRY | SNACKPACK | +15k |

## v1611 → v2090 evolution

| Metric | v1611 | v2090 | Δ |
|---|---:|---:|---:|
| **PnL** | 880,725 | **959,945** | **+79,220 (+9.0%)** |
| Max DD abs | 28,361 | 23,830 | **-4,531 (-16%)** |
| Day 4 DD % | 9.6% | 4.7% | -4.9 pp |

## Submission

- File: `artifacts/submissions/round_5/best_v2090_revive_space_gray_round5_submission.py`
- Validated, runs well under 900ms IMC limit
