# R5 FINAL CHAMPION — best_v1760_oval_triangle_added

## Performance

| Metric | Backtest 3-day | vs v1740 | vs v1611 |
|---|---:|---:|---:|
| **PnL Total** | **911,181** | **+1,197** | **+30,456** |
| **Max DD** | **24,648 (8.3%)** | -1,860 | -3,713 |
| Day 4 (LIVE) DD | 17,858 (5.6%) | +288 | -40pp |
| Win rate | 0.548 | 0 | +0.006 |
| Volume | 46,388 passive trades | -279 | -1,393 |

## Champion composition (v1611 → v1614 → v1630 → v1740 → v1760)

Four pair_skip overlays added on top of Tibo's specialized alphas:

| Step | Change | Cumul PnL | Cumul DD% |
|---|---|---:|---:|
| v1611 baseline | Tibo's full strategy + Leo's overlays | 880,725 | 9.7% |
| v1614 | + MICROCHIP_RECTANGLE pair_skip(SQUARE) | 896,348 (+15.6k) | 9.2% |
| v1630 | + ROBOT_LAUNDRY pair_skip(VACUUMING) | 901,488 (+5.1k) | 9.0% |
| v1740 | + MICROCHIP_CIRCLE pair_skip(OVAL) | 909,984 (+8.5k) | 9.0% |
| **v1760** | **+ MICROCHIP_OVAL pair_skip(TRIANGLE)** | **911,181 (+1.2k)** | **8.3%** |
| **TOTAL** | | **+30,456** | **-1.4pp** |

## Composition (45 active products)

### Tibo's specialized alphas (kept)
- **pebbles_arb_v1** on PEBBLES_XL → ~+89k
- **ar1_mean_rev_v1** on ROBOT_DISHES → ~+140k
- **trend_follow_v2** on 11 products → ~+97k
- **trend_follow_v2** on MICROCHIP_SQUARE → ~+55k
- **coint_mm_v1** on ROBOT_VACUUMING → ~+14k

### Pair-skip overlays (Leo's contribution, +44k cumul)
- **PEBBLES_S ↔ PEBBLES_XL → +62k** (synergy with pebbles_arb)
- **MICROCHIP_RECTANGLE ↔ SQUARE → +26k** ← v1614
- **MICROCHIP_CIRCLE ↔ OVAL → +19k** ← v1740 (NEW partner)
- **MICROCHIP_OVAL ↔ TRIANGLE → +12k** ← v1720/v1760
- **ROBOT_LAUNDRY ↔ VACUUMING → +17k** ← v1630
- SNACKPACK_VANILLA ↔ CHOCOLATE → +4k
- SNACKPACK_RASPBERRY ↔ STRAWBERRY → +15k

### Inventory carry overlays
- PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, PEBBLES_L → +4,650 cumul

### Drops (perpetual losers)
- TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL (Tibo)
- UV_VISOR_MAGENTA, OXYGEN_SHAKE_MINT (Leo)

## Asymmetric pair_skip insight (validated 5+ times)

Pattern: For each correlated pair, the slower-moving / lagging product
benefits from pair_skip; using the leader as partner gives the strongest signal.

| Pair (lagger ← leader) | Status | PnL Δ |
|---|---|---:|
| RECTANGLE ← SQUARE | v1614 ✓ | +15.6k |
| LAUNDRY ← VACUUMING | v1630 ✓ | +5.1k |
| CIRCLE ← OVAL | v1740 ✓ | +8.5k |
| OVAL ← TRIANGLE | v1760 ✓ | +1.2k |
| Failed: TRIANGLE ← OVAL | v1700 ✗ | -8.3k |
| Failed: VACUUMING ← LAUNDRY | v1640 ✗ | -10.9k |
| Failed: CIRCLE ← SQUARE | v1770 ✗ | -8.3k |
| Failed: OVAL ← CIRCLE (sym) | v1750 ✗ | -4.8k vs v1740 |

## DD profile

| Day | DD abs | DD % |
|---|---:|---:|
| Day 2 | 22,920 | 19.3% |
| Day 3 | 24,648 | 51.0% |
| **Day 4 (LIVE)** | **17,858** | **5.6%** |
| Total chained | 24,648 | 8.3% |

## Submission

- File: `artifacts/submissions/round_5/best_v1760_oval_triangle_added_round5_submission.py`
- Validated: syntax OK, no banned imports, instantiates, runs 200 ticks (avg 0.83ms, max 2.21ms)
- 45 active products

## Backups

1. `best_v1740_circle_oval_partner_round5_submission.py` (909,984)
2. `best_v1730_circle_oval_round5_submission.py` (908,572)
3. `best_v1710_circle_pair_round5_submission.py` (907,375)
4. `best_v1630_laundry_pair_round5_submission.py` (901,488)
