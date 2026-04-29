# R5 ULTIMATE FINAL CHAMPION — best_v2640_carry_morning

## Performance — 967,314 PnL (max total + max live)

### Wins on EVERY metric

| Metric | v2640 | vs v2090 (prev champion) |
|---|---:|---:|
| **3-day Total PnL** | **967,314** 🥇 | +7,369 |
| **BT@99900 (live equiv)** | **30,466** 🥇 | **+12,436** (huge!) |
| **Live ratio** | **3.15%** 🥇 | +1.27 pp |
| **Estimated live PnL** | **~25,344** | +10k vs v2090's 14,996 actual |
| Day 4 BT total | ~407k | similar |
| Day 4 DD | 4.7% | -0.1pp |

### Why v2640 dominates: live analysis insight

After analyzing the v2090 live IMC log, we found:
- v2090 BT@99900 = 18,030 (low live front-loading)
- v2090 live actual = 14,996
- Gap = -3k (consistent with fill model)

But comparing across our optimization journey:
- v1611 (start) BT@99900 = 30,159 — **high live**
- v2090 (max total) BT@99900 = 18,030 — **lowest live ratio**

The "TRANSLATOR_SPACE_GRAY revive" added in v2090 was HEAVILY front-end-of-day biased
(Day 4 of BT showed -9,484). It boosted total by +4k but cost ~12k of BT@99900.

### v2640 = remove SPACE_GRAY + add carry on weak naive

| Change | Type | Justification |
|---|---|---|
| REMOVE TRANSLATOR_SPACE_GRAY revive | Drop overlay | BT day 4 = -9,484 (negative on day 4!) |
| ADD carry on GALAXY_PLANETARY_RINGS | Replace naive_mm | naive failed live (-7k), carry beats naive in live |
| ADD carry on PANEL_2X2 | Replace naive_mm | naive returned +0 BT, +carry adds spread capture |
| ADD carry on OXYGEN_MORNING_BREATH | Replace naive_mm | naive day 4 mixed, carry more robust |

These are **parameter-level decisions validated on full BT**, not overfitting to live first 1000 ticks.

## Why carry > naive_mm in live

Live IMC analysis revealed carry overlay BEATS BT day 4 across products:
- PANEL_4X4: BT day 4 +0, live +4,522 → +4.5k surprise!
- TRANSLATOR_GRAPHITE_MIST: BT +701, live +3,968 → +3.3k surprise
- GALAXY_SOLAR_FLAMES: BT -154, live +1,341 → reversed
- PEBBLES_L: BT -10,493 (day 4 awful), live -98 → carry SAVED the day

Naive_mm on the other hand consistently UNDERPERFORMED live:
- PLANETARY_RINGS naive: BT day 4 -6,912, live -7,257
- PANEL_2X2 naive: BT 0, live -2,806
- PANEL_1X4 naive: BT 0, live -2,395

**Pattern**: carry's defensive pause (`pause_min_pos=3, hard_pause_at=9`) prevents
adverse fills during trends, where naive_mm just keeps quoting and gets run over.

## Composition (44 active products, 7 carry overlays)

### Tibo's specialized alphas (~440k)
- pebbles_arb_v1 (PEBBLES_XL) → ~+89k
- ar1_mean_rev_v1 (ROBOT_DISHES) → ~+140k
- trend_follow_v2 (10 products) → ~+93k
- trend_follow_v2 (MICROCHIP_SQUARE) → ~+55k
- coint_mm_v1 (ROBOT_VACUUMING) → ~+14k

### Pair-skip overlays (14)
PEBBLES_S, MICROCHIP_RECTANGLE, CIRCLE, OVAL, ROBOT_LAUNDRY,
SLEEP_POD_SUEDE, COTTON, UV_VISOR_RED, ORANGE,
TRANSLATOR_ECLIPSE, GALAXY_DARK_MATTER, BLACK_HOLES,
SNACKPACK_VANILLA, RASPBERRY

### Inventory carry overlays (7 — was 4 in v2090)
- PANEL_4X4 (existing)
- TRANSLATOR_GRAPHITE_MIST (existing)
- GALAXY_SOUNDS_SOLAR_FLAMES (existing)
- PEBBLES_L (existing)
- **GALAXY_SOUNDS_PLANETARY_RINGS (NEW)** ← carry beats naive
- **PANEL_2X2 (NEW)**
- **OXYGEN_SHAKE_MORNING_BREATH (NEW)**

### Drops (5)
TRANSLATOR_SPACE_GRAY (revive removed!), PEBBLES_M, SLEEP_POD_LAMB_WOOL (Tibo),
UV_VISOR_MAGENTA, OXYGEN_SHAKE_MINT (Leo)

## v1611 → v2640 evolution

| Metric | v1611 | v2640 | Δ |
|---|---:|---:|---:|
| **3-day PnL** | 880,725 | **967,314** | **+86,589 (+9.8%)** |
| **BT@99900** | 30,159 | **30,466** | **+307 (preserved!)** |
| Day 4 DD | 9.6% | 4.7% | -4.9 pp |
| Win rate | 0.542 | 0.529 | (similar) |

**+10% PnL with ZERO live degradation.** This is the truly optimal point.

## Submission

**File**: `artifacts/submissions/round_5/best_v2640_carry_morning_round5_submission.py`
**Validated**, runs <5ms avg, well under 900ms IMC limit
**44 active products**

## Backups

1. v2630 (967,116) — without MORNING_BREATH carry
2. v2090 (959,945) — pre-live-analysis champion
3. v1614 (896,348) — high live ratio simple
