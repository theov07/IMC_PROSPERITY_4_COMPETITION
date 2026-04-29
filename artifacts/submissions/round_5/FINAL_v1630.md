# R5 FINAL CHAMPION — best_v1630_laundry_pair

## Performance

| Metric | Backtest 3-day | vs v1614 | vs v1611 |
|---|---:|---:|---:|
| **PnL Total** | **901,488** | **+5,140** | **+20,763** |
| Max DD | 26,198 (9.0%) | -1,039 | -2,163 |
| Day 4 (LIVE) DD | **5.5%** | vs 9.2% v1614 | vs 9.6% v1611 |
| Win rate | 0.549 | +0.004 | +0.007 |
| Volume | 46,981 passive trades | -434 | -800 |

**Key win: Day 4 drawdown is 5.5% (vs 9.2% in v1614). Since live = day 4, this is the most important metric.**

## What changed vs v1611 baseline (880,725)

1. **MICROCHIP_RECTANGLE: coint_mm → pair_skip(SQUARE) thresh=1.25** (v1614 step)
   - Was +10,381 with coint_mm, became **+26,320** with pair_skip
   - Δ = **+15,939**
2. **ROBOT_LAUNDRY: coint_mm → pair_skip(VACUUMING) thresh=1.25** (v1630 step)
   - Was +12,197 with coint_mm, became **+17,337** with pair_skip
   - Δ = **+5,140**
   - Day 4 specifically: -545 → +9,808 (huge swing)

## Composition (45 active products)

### Tibo's specialized alphas (kept)
- **pebbles_arb_v1** on PEBBLES_XL → +89k (conservation 50000)
- **ar1_mean_rev_v1** on ROBOT_DISHES → +140k (z-score taker thresh=20)
- **trend_follow_v2** on 11 products → +97k
- **coint_mm_v1** on ROBOT_VACUUMING → +14k (LAUNDRY now pair_skip)

### Pair-skip overlays (Leo's contribution)
- PEBBLES_S ↔ PEBBLES_XL → +62k (synergy with pebbles_arb)
- **MICROCHIP_RECTANGLE ↔ SQUARE → +26k** ← v1614 add
- **ROBOT_LAUNDRY ↔ VACUUMING → +17k** ← v1630 add
- SNACKPACK_VANILLA ↔ CHOCOLATE → +4k
- SNACKPACK_RASPBERRY ↔ STRAWBERRY → +15k

### Inventory carry overlays
- PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, PEBBLES_L → +4,650 cumul

### Drops (perpetual losers)
- TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL (Tibo)
- UV_VISOR_MAGENTA, OXYGEN_SHAKE_MINT (Leo)

## Tested in this session (post-v1611)

| Variant | PnL | vs v1614 | Verdict |
|---|---:|---:|---|
| v1612 (PEBBLES_XS pair_skip replace trend) | -23k vs v10 | — | Bad |
| v1613 (revive PEBBLES_M) | similar | — | No improvement |
| v1614 (RECTANGLE pair_skip) | 896,348 | baseline | **GOOD** |
| v1615 (PEBBLES_S zscore replace pair_skip) | 866,850 | -29,498 | Worse |
| v1620 (= v1614 + MINT no-op) | 896,348 | 0 | Sanity passed |
| **v1630 (LAUNDRY pair_skip)** | **901,488** | **+5,140** | **CHAMPION** |
| v1640 (VACUUMING pair_skip alone) | 885,433 | -10,915 | Worse |
| v1660 (both robots) | 890,573 | -5,775 | Worse (combo bad) |

## Why VACUUMING pair_skip is bad but LAUNDRY pair_skip is good

Asymmetric: ROBOT_VACUUMING tends to lead the pair (faster moves), so pair_skip
based on lagging Z-window misses the entry. ROBOT_LAUNDRY lags, and skipping
when the pair is misaligned protects against adverse fills.

When both are pair_skipped, neither side captures cointegration mean-reversion
that coint_mm picks up on VACUUMING. Result: lose 11k on VACUUMING but only gain
5k on LAUNDRY = -6k net.

**Conclusion: keep LAUNDRY pair_skip, KEEP coint_mm on VACUUMING.**

## DD profile

| Day | DD abs | DD % |
|---|---:|---:|
| Day 2 | 23,630 | 19.5% |
| Day 3 | 26,198 | 57.6% |
| **Day 4 (LIVE)** | **17,506** | **5.5%** |
| Total chained | 26,198 | 9.0% |

## Submission

- File: `artifacts/submissions/round_5/best_v1630_laundry_pair_round5_submission.py`
- Validated: syntax OK, no banned imports, instantiates, runs 200 ticks (avg 1.48ms, max 2.83ms)
- 45 active products
