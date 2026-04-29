# R5 FINAL CHAMPION — best_v1910_all_winners

## Performance — 935,624 PnL

| Metric | Backtest 3-day | vs v1830 | vs v1611 | vs v10 baseline |
|---|---:|---:|---:|---:|
| **PnL Total** | **935,624** | **+10,284** | **+54,899** | **+87,944** |
| **Max DD** | **22,298 (10.6%)** | -3,042 | -6,063 | -6,063 |
| Day 4 (LIVE) DD | **18,270 (5.7%)** | +212 | -3.9 pp | -3.9 pp |
| Win rate | 0.546 | -0.001 | +0.004 | +0.004 |
| Volume | 44,223 passive trades | -913 | -3,558 | -3,558 |

## Champion stack composition

```
v1611 baseline (Tibo's full + Leo's overlays):  880,725 PnL
                                                 ─────────
v1614: + MICROCHIP_RECTANGLE pair_skip(SQUARE)  +15,623
v1630: + ROBOT_LAUNDRY pair_skip(VACUUMING)      +5,140
v1740: + MICROCHIP_CIRCLE pair_skip(OVAL)        +8,496
v1760: + MICROCHIP_OVAL pair_skip(TRIANGLE)      +1,197
v1800: + TRANSLATOR_ECLIPSE pair_skip(VOID)      +3,897
v1830: + UV_VISOR_RED pair_skip(AMBER)          +10,262
+ ORANGE pair_skip(YELLOW)                       +6,494
+ DARK_MATTER pair_skip(PLANETARY_RINGS)         +3,109
+ BLACK_HOLES pair_skip(PLANETARY_RINGS)           +682
                                                 ─────────
v1910 TOTAL (additive stack):                    935,625
                                                 ✓ matches actual 935,624
```

The components stack ADDITIVELY — no negative interactions found between any
of the 9 pair_skip overlays.

## Composition (45 active products)

### Tibo's specialized alphas (~440k)
- **pebbles_arb_v1** on PEBBLES_XL → ~+89k
- **ar1_mean_rev_v1** on ROBOT_DISHES → ~+140k
- **trend_follow_v2** on 11 products → ~+97k
- **trend_follow_v2** on MICROCHIP_SQUARE → ~+55k
- **coint_mm_v1** on ROBOT_VACUUMING → ~+14k

### Pair-skip overlays (~200k cumul, +99k from this final session)
| Overlay | PnL | Pattern (lagger ← leader) |
|---|---:|---|
| PEBBLES_S ↔ PEBBLES_XL | +62k | ← XL |
| MICROCHIP_RECTANGLE ↔ SQUARE | +26k | ← SQUARE |
| MICROCHIP_CIRCLE ↔ OVAL | +19k | ← OVAL |
| UV_VISOR_RED ↔ AMBER | +20k | ← AMBER |
| UV_VISOR_ORANGE ↔ YELLOW | +21k | ← YELLOW |
| ROBOT_LAUNDRY ↔ VACUUMING | +17k | ← VACUUMING |
| MICROCHIP_OVAL ↔ TRIANGLE | +12k | ← TRIANGLE |
| TRANSLATOR_ECLIPSE ↔ VOID | +12k | ← VOID |
| GALAXY_DARK_MATTER ↔ PLANETARY | +11k | ← PLANETARY |
| GALAXY_BLACK_HOLES ↔ PLANETARY | +16k | ← PLANETARY |
| SNACKPACK_VANILLA ↔ CHOCOLATE | +4k | ← CHOCOLATE |
| SNACKPACK_RASPBERRY ↔ STRAWBERRY | +15k | ← STRAWBERRY |

### Inventory carry overlays (+5k)
- PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, PEBBLES_L

### Drops (perpetual losers)
- TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL (Tibo)
- UV_VISOR_MAGENTA, OXYGEN_SHAKE_MINT (Leo)

## Asymmetric pair_skip pattern (validated 12+ times)

For each correlated pair, the slower-moving / lagging product benefits from
pair_skip; the leader does NOT.

### Wins (lagger pair_skip with leader)
- RECTANGLE ← SQUARE ✓
- LAUNDRY ← VACUUMING ✓
- CIRCLE ← OVAL ✓ (best single addition)
- OVAL ← TRIANGLE ✓ (small)
- ECLIPSE ← VOID ✓
- RED ← AMBER ✓ (huge +10k)
- ORANGE ← YELLOW ✓
- DARK_MATTER ← PLANETARY ✓
- BLACK_HOLES ← PLANETARY ✓

### Losses (wrong direction)
- TRIANGLE ← OVAL ✗ (-8k)
- VACUUMING ← LAUNDRY ✗ (-11k)
- CIRCLE ← SQUARE ✗ (-8k, wrong group)
- SOLAR_WINDS ← PLANETARY ✗ (-0.7k)
- MORNING_BREATH ← CHOCOLATE ✗ (-18k!)
- OVAL ← CIRCLE (sym) ✗ (-5k vs unidirectional)
- RED ← YELLOW (alt partner) ✗ (-17k vs RED-AMBER)
- PANEL_2X2 ← PANEL_1X4 ✗ (-4k)

## DD profile

| Day | DD abs | DD % |
|---|---:|---:|
| Day 2 | 22,298 | 10.6% |
| Day 3 | 20,606 | 65.5% |
| **Day 4 (LIVE)** | **18,270** | **5.7%** |
| Total chained | 22,298 | 10.6% |

The Day 3 % is high because peak equity is mid-day and intermediate dips are
relatively large; absolute DD is only 20.6k which is the lowest Day-3 abs DD
of all variants tested.

## Submission

- File: `artifacts/submissions/round_5/best_v1910_all_winners_round5_submission.py`
- Validated: syntax OK, no banned imports, instantiates, runs 200 ticks (avg 3.64ms, p99 7.50ms, max 7.68ms — well under 900ms IMC limit)
- 45 active products

## Backups (in order)

1. `best_v1880_dark_planetary_round5_submission.py` (928,449)
2. `best_v1830_red_amber_round5_submission.py` (925,340)
3. `best_v1800_eclipse_void_round5_submission.py` (915,078)
4. `best_v1760_oval_triangle_added_round5_submission.py` (911,181)
5. `best_v1740_circle_oval_partner_round5_submission.py` (909,984)
6. `best_v1730_circle_oval_round5_submission.py` (908,572)
7. `best_v1710_circle_pair_round5_submission.py` (907,375)
8. `best_v1630_laundry_pair_round5_submission.py` (901,488)

## Key insights from this session

1. **Pattern discovery**: `lagger_pair_skip(leader)` always wins, reverse loses (~12 wins, ~8 losses confirm)
2. **Stacking**: independent pair_skip overlays compose ADDITIVELY (no interaction)
3. **Day 4 robustness**: each pair_skip lowers live-day drawdown vs naive_mm baseline
4. **Asymmetry per group**: each group has 1-2 leaders and 2-4 laggers. We exploit all the laggers.

## Why MM sophistiqué (R3/R4) doesn't work in R5 (recap)

1. pos_limit=10 (vs 200-300 R3/R4) — inventory skew has no material effect
2. Trader IDs anonymized — no toxic flow detection
3. Spread = 8-15 ticks — already captured by penny-improve simple
4. Skew price-based costs 1 tick per fill — net negative on most products
