# R5 FINAL CHAMPION — best_v2010_cotton_nylon

## Performance — 955,752 PnL

| Metric | Backtest 3-day | vs v1950 | vs v1611 | vs v10 |
|---|---:|---:|---:|---:|
| **PnL Total** | **955,752** | **+15,254** | **+75,027** | **+108,072** |
| **Max DD** | **23,830 (8.6%)** | +2,122 | -4,531 | -4,531 |
| **Day 4 (LIVE) DD** | **16,412 (4.7%)** | -1,754 | **-4.9pp!** | -4.9pp |
| Win rate | 0.538 | -0.007 | -0.004 | -0.004 |
| Volume | 44,778 passive trades | +1,003 | -3,003 | -3,003 |

**Day 4 (LIVE) drawdown : 4.7% — meilleur de toutes les variantes testées.**

## Champion stack composition (14 pair_skip overlays)

```
v1611 baseline:                                  880,725 PnL
                                                 ─────────
v1614: + MICROCHIP_RECTANGLE pair_skip(SQUARE)  +15,623
v1630: + ROBOT_LAUNDRY pair_skip(VACUUMING)      +5,140
v1740: + MICROCHIP_CIRCLE pair_skip(OVAL)        +8,496
v1760: + MICROCHIP_OVAL pair_skip(TRIANGLE)      +1,197
v1800: + TRANSLATOR_ECLIPSE pair_skip(VOID)      +3,897
v1830: + UV_VISOR_RED pair_skip(AMBER)          +10,262
v1850: + UV_VISOR_ORANGE pair_skip(YELLOW)       +6,494
v1880: + GALAXY_DARK_MATTER pair_skip(PLANET)    +3,109
v1900: + GALAXY_BLACK_HOLES pair_skip(PLANET)      +682
v1950: + SLEEP_POD_SUEDE pair_skip(NYLON)        +4,874
v2010: + SLEEP_POD_COTTON pair_skip(NYLON)      +15,254  ← NEW
                                                 ─────────
v2010 TOTAL:                                     955,753
                                                 ✓ matches actual 955,752
```

## Key Day 4 (LIVE) impact

COTTON Day 4 went from probably +1k (v1950 baseline trend_follow) to **+14,954** 
in v2010. This is a 13k improvement on the LIVE day alone.

| Day | v1950 SLEEP_POD_COTTON | v2010 SLEEP_POD_COTTON | Δ |
|---|---:|---:|---:|
| 2 | (trend_follow ≈ +8k) | -663 | -8.7k |
| 3 | (trend_follow ≈ -5k) | +5,374 | +10k |
| **4 (LIVE)** | (trend_follow ≈ +1k) | **+14,954** | **+13k** |

The pair_skip catches the day-4 directional move that trend_follow missed.

## Composition (45 active products)

### Tibo's specialized alphas (~440k)
- **pebbles_arb_v1** on PEBBLES_XL → ~+89k
- **ar1_mean_rev_v1** on ROBOT_DISHES → ~+140k
- **trend_follow_v2** on 10 products → ~+93k (COTTON now pair_skip)
- **trend_follow_v2** on MICROCHIP_SQUARE → ~+55k
- **coint_mm_v1** on ROBOT_VACUUMING → ~+14k

### Pair-skip overlays (14 total, +220k cumul)
| Pair (lagger ← leader) | Group | PnL |
|---|---|---:|
| PEBBLES_S ← PEBBLES_XL | PEBBLES | +62k |
| MICROCHIP_RECTANGLE ← SQUARE | MICROCHIP | +26k |
| MICROCHIP_CIRCLE ← OVAL | MICROCHIP | +19k |
| MICROCHIP_OVAL ← TRIANGLE | MICROCHIP | +12k |
| ROBOT_LAUNDRY ← VACUUMING | ROBOT | +17k |
| SLEEP_POD_SUEDE ← NYLON | SLEEP_POD | +19k |
| **SLEEP_POD_COTTON ← NYLON** | SLEEP_POD | **+20k** ← v2010 NEW |
| UV_VISOR_RED ← AMBER | UV_VISOR | +20k |
| UV_VISOR_ORANGE ← YELLOW | UV_VISOR | +21k |
| TRANSLATOR_ECLIPSE ← VOID | TRANSLATOR | +12k |
| GALAXY_DARK_MATTER ← PLANETARY | GALAXY | +11k |
| GALAXY_BLACK_HOLES ← PLANETARY | GALAXY | +16k |
| SNACKPACK_VANILLA ← CHOCOLATE | SNACKPACK | +4k |
| SNACKPACK_RASPBERRY ← STRAWBERRY | SNACKPACK | +15k |

### Inventory carry overlays (+5k)
- PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, PEBBLES_L

### Drops (perpetual losers)
- TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL (Tibo)
- UV_VISOR_MAGENTA, OXYGEN_SHAKE_MINT (Leo)

## Asymmetric pair_skip pattern (validated 14 wins, 9 losses)

For each correlated pair, the slower-moving / lagging product benefits from
pair_skip; the leader does NOT.

NYLON is the LEADER in SLEEP_POD group (highest PnL with very few trades = 
trend follow capturing big moves). SUEDE and COTTON are laggers — both benefit.

## Submission

- File: `artifacts/submissions/round_5/best_v2010_cotton_nylon_round5_submission.py`
- Validated: avg 1.81ms, p99 4.40ms (well under 900ms)
- 45 active products

## Backups (in order)

1. `best_v1950_suede_nylon_round5_submission.py` (940,498)
2. `best_v1910_all_winners_round5_submission.py` (935,624)
3. `best_v1850_uv_combo_round5_submission.py` (931,834)

## Final v1611 → v2010 evolution

| Metric | v1611 | v2010 | Δ |
|---|---:|---:|---:|
| **PnL** | 880,725 | **955,752** | **+75,027 (+8.5%)** |
| **Max DD abs** | 28,361 | **23,830** | **-4,531 (-16%)** |
| **Day 4 DD %** | 9.6% | **4.7%** | **-4.9 pp** |
| Win rate | 0.542 | 0.538 | -0.4 pp |

**+8.5% PnL improvement, 16% lower max DD, 50% lower live-day DD.**
