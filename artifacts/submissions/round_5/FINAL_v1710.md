# R5 FINAL CHAMPION — best_v1710_circle_pair

## Performance

| Metric | Backtest 3-day | vs v1630 | vs v1614 | vs v1611 |
|---|---:|---:|---:|---:|
| **PnL Total** | **907,375** | **+5,887** | **+11,027** | **+26,650** |
| Max DD | 28,244 (9.5%) | +2,046 | +1,007 | -117 |
| Day 4 (LIVE) DD | 17,354 (5.5%) | -152 | -3,7 pp | -41 pp |
| Win rate | 0.548 | -0.001 | +0.003 | +0.006 |
| Volume | 46,691 passive trades | -290 | -724 | -1090 |

## Champion composition (v1611 → v1614 → v1630 → v1710 evolution)

Three pair_skip overlays added on top of Tibo's specialized alphas:

| Step | Change | PnL gain | Day 4 DD |
|---|---|---:|---:|
| v1611 baseline | Tibo's full strategy + Leo's overlays | 880,725 | 9.6% |
| v1614 | + MICROCHIP_RECTANGLE pair_skip(SQUARE) | +15,623 | 9.2% |
| v1630 | + ROBOT_LAUNDRY pair_skip(VACUUMING) | +5,140 | **5.5%** |
| **v1710** | **+ MICROCHIP_CIRCLE pair_skip(TRIANGLE)** | **+5,887** | **5.5%** |
| **TOTAL** | | **+26,650** | **-4.1 pp** |

## Composition (45 active products)

### Tibo's specialized alphas (kept)
- **pebbles_arb_v1** on PEBBLES_XL → ~+89k (conservation 50000)
- **ar1_mean_rev_v1** on ROBOT_DISHES → ~+140k (z-score taker thresh=20)
- **trend_follow_v2** on 11 products → ~+97k
- **coint_mm_v1** on ROBOT_VACUUMING → ~+14k (LAUNDRY now pair_skip)
- **trend_follow_v2** on MICROCHIP_SQUARE → ~+55k

### Pair-skip overlays (Leo's contribution, +33k cumul)
- **PEBBLES_S ↔ PEBBLES_XL → +62k** (synergy with pebbles_arb)
- **MICROCHIP_RECTANGLE ↔ SQUARE → +26k** ← v1614 add
- **ROBOT_LAUNDRY ↔ VACUUMING → +17k** ← v1630 add
- **MICROCHIP_CIRCLE ↔ TRIANGLE → +16k** ← v1710 add (NEW)
- SNACKPACK_VANILLA ↔ CHOCOLATE → +4k
- SNACKPACK_RASPBERRY ↔ STRAWBERRY → +15k

### Inventory carry overlays
- PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, PEBBLES_L → +4,650 cumul

### Drops (perpetual losers)
- TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL (Tibo)
- UV_VISOR_MAGENTA, OXYGEN_SHAKE_MINT (Leo)

## Tested in this final session (extended)

| Variant | PnL | vs v1614 | Verdict |
|---|---:|---:|---|
| v1614 (RECTANGLE pair_skip) | 896,348 | baseline | base |
| v1630 (+ LAUNDRY pair_skip) | 901,488 | +5,140 | **GOOD** |
| v1640 (VACUUMING pair_skip alone) | 885,433 | -10,915 | Bad |
| v1650/1660 (both robots) | 890,573 | -5,775 | Bad combo |
| v1700 (OVAL+TRIANGLE pair) | 894,330 | -2,018 | Bad combo |
| v1720 (OVAL only) | 902,684 | +6,336 | OK (weaker) |
| **v1710 (CIRCLE pair_skip)** | **907,375** | **+11,027** | **CHAMPION** |

## Asymmetric pair_skip insight

Three independent confirmations of asymmetric behavior:
- ROBOT_LAUNDRY > ROBOT_VACUUMING (LAUNDRY pair_skip works, VACUUMING doesn't)
- MICROCHIP_CIRCLE > MICROCHIP_OVAL > MICROCHIP_TRIANGLE
- Both robots together hurt; both microchips together hurt

**Hypothesis**: For each correlated pair, the slower-moving / lagging product
benefits from pair_skip (the partner's z-score predicts adverse moves before
your own price reflects them). The leading/faster product has nothing useful
to learn from a lagging partner.

## DD profile

| Day | DD abs | DD % |
|---|---:|---:|
| Day 2 | 23,180 | 19.4% |
| Day 3 | 28,244 | 57.7% |
| **Day 4 (LIVE)** | **17,354** | **5.5%** |
| Total chained | 28,244 | 9.5% |

## Submission

- File: `artifacts/submissions/round_5/best_v1710_circle_pair_round5_submission.py`
- Validated: syntax OK, no banned imports, instantiates, runs 200 ticks (avg 0.83ms, max 2.93ms)
- 45 active products
- Runtime well under the 900ms IMC limit

## Backups (in case v1710 fails for some reason)

1. `best_v1720_oval_only_round5_submission.py` (902,684, OVAL-only)
2. `best_v1630_laundry_pair_round5_submission.py` (901,488, robot-only)
3. `best_v1614_rectangle_pair_round5_submission.py` (896,348, RECT-only)
