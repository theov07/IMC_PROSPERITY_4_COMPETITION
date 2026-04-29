# R5 FINAL CHAMPION — best_v1740_circle_oval_partner

## Performance

| Metric | Backtest 3-day | vs v1710 | vs v1630 | vs v1611 |
|---|---:|---:|---:|---:|
| **PnL Total** | **909,984** | **+2,609** | **+8,496** | **+29,259** |
| Max DD | **26,508 (9.0%)** | -1,736 | +310 | -1,853 |
| Day 4 (LIVE) DD | 17,570 (5.5%) | +216 | +64 | -41pp |
| Win rate | 0.548 | 0 | -0.001 | +0.006 |
| Volume | 46,667 passive trades | -24 | -314 | -1,114 |

## Champion composition (v1611 → v1614 → v1630 → v1740 evolution)

Three pair_skip overlays added on top of Tibo's specialized alphas. The final
gain came from understanding that **CIRCLE pair_skip works best with OVAL as
partner**, not TRIANGLE.

| Step | Change | PnL gain | Day 4 DD |
|---|---|---:|---:|
| v1611 baseline | Tibo's full strategy + Leo's overlays | 880,725 | 9.6% |
| v1614 | + MICROCHIP_RECTANGLE pair_skip(SQUARE) | +15,623 | 9.2% |
| v1630 | + ROBOT_LAUNDRY pair_skip(VACUUMING) | +5,140 | **5.5%** |
| **v1740** | **+ MICROCHIP_CIRCLE pair_skip(OVAL)** | **+8,496** | **5.5%** |
| **TOTAL** | | **+29,259** | **-4.1pp** |

## Composition (45 active products)

### Tibo's specialized alphas (kept)
- **pebbles_arb_v1** on PEBBLES_XL → ~+89k
- **ar1_mean_rev_v1** on ROBOT_DISHES → ~+140k
- **trend_follow_v2** on 11 products → ~+97k
- **trend_follow_v2** on MICROCHIP_SQUARE → ~+55k
- **coint_mm_v1** on ROBOT_VACUUMING → ~+14k

### Pair-skip overlays (Leo's contribution, +43k cumul)
- **PEBBLES_S ↔ PEBBLES_XL → +62k** (synergy with pebbles_arb)
- **MICROCHIP_RECTANGLE ↔ SQUARE → +26k** ← v1614 add
- **MICROCHIP_CIRCLE ↔ OVAL → +19k** ← v1740 add (NEW, was 10k naive_mm)
- **ROBOT_LAUNDRY ↔ VACUUMING → +17k** ← v1630 add
- SNACKPACK_VANILLA ↔ CHOCOLATE → +4k
- SNACKPACK_RASPBERRY ↔ STRAWBERRY → +15k

### Inventory carry overlays
- PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, PEBBLES_L → +4,650 cumul

### Drops (perpetual losers)
- TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL (Tibo)
- UV_VISOR_MAGENTA, OXYGEN_SHAKE_MINT (Leo)

## Asymmetric pair_skip insight (validated 4 times)

| Pair | Good partner | Bad partner | Notes |
|---|---|---|---|
| ROBOT_LAUNDRY/VACUUMING | LAUNDRY pair_skip(VAC) | VAC pair_skip(LAU) | LAUNDRY is the lagger |
| MICROCHIP_OVAL/TRIANGLE | OVAL pair_skip(TRI) ok | TRIANGLE pair_skip bad | OVAL is the lagger |
| MICROCHIP_CIRCLE/OVAL | CIRCLE pair_skip(OVAL) BEST | n/a | CIRCLE is the lagger |
| MICROCHIP_RECTANGLE/SQUARE | RECT pair_skip(SQUARE) | n/a | RECT is the lagger |

**Pattern**: For each correlated pair, the slower-moving / lagging product
benefits from pair_skip (the partner's z-score predicts adverse moves before
your own price reflects them). The leading/faster product has nothing useful
to learn from a lagging partner.

## DD profile

| Day | DD abs | DD % |
|---|---:|---:|
| Day 2 | 22,920 | 19.3% |
| Day 3 | 26,508 | 57.1% |
| **Day 4 (LIVE)** | **17,570** | **5.5%** |
| Total chained | 26,508 | 9.0% |

## Submission

- File: `artifacts/submissions/round_5/best_v1740_circle_oval_partner_round5_submission.py`
- Validated: syntax OK, no banned imports, instantiates, runs 200 ticks (avg 1.23ms, max 3.69ms)
- 45 active products
- Runtime well under the 900ms IMC limit

## Backups (in case v1740 fails)

1. `best_v1730_circle_oval_round5_submission.py` (908,572)
2. `best_v1710_circle_pair_round5_submission.py` (907,375)
3. `best_v1720_oval_only_round5_submission.py` (902,684)
4. `best_v1630_laundry_pair_round5_submission.py` (901,488)
