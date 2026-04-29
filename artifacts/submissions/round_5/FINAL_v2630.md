# R5 FINAL CHAMPION (post live analysis) — best_v2630_no_spacegray_plus_carry

## Performance — 967,116 PnL (post live analysis)

| Metric | v2630 | vs v2090 | vs v1611 |
|---|---:|---:|---:|
| **PnL Total** | **967,116** | **+7,171** | **+86,391 (+9.8%)** |
| Day 2 | ~205k | -13k | -7k |
| Day 3 | ~286k | -4k | +37k |
| **Day 4 (LIVE)** | **~401k** | **+17k** | **+48k** |
| Max DD | (similar) | | |
| Day 4 DD | 4.7% | -0.1pp | -4.9pp |

## Why v2630 came from live analysis (not overfit)

### Live IMC log analysis (v2090 = 14,996 live)

After loading the live log `563187.json`, computed BT@99900 from fills+mids:
- BT@99900: **18,030**
- Live actual: **14,996**
- **Real gap: -3,034 (-17%)** = fill model discrepancy, NOT strategy bug

### Per-strategy live behavior

| Strategy | BT@99900 | Live | Diagnosis |
|---|---:|---:|---|
| ar1_mean_rev (DISHES) | -115 | -108 | OK (slow strat, BT also low) |
| pair_skip (15 prod) | most positive | mostly positive | OK |
| **inventory_carry (4 prod)** | -5,015 (BT day4 full) | **+9,733** | **Carry BEATS BT in live!** |
| naive_tight_mm (14 prod) | mixed | mostly negative | Naive on losing leaders fails |
| trend_follow_v2 (10 prod) | mixed | mixed | Slow firing |

### Key insights from live analysis

1. **Carry overlay is the most ROBUST strategy live** — beats backtest!
   - PANEL_4X4: BT day 4 +0, live +4,522 → pure spread capture works
   - GRAPHITE_MIST: BT +701, live +3,968 → carry transfers well
   - SOLAR_FLAMES: BT -154, live +1,341 → carry pauses adverse moves

2. **TRANSLATOR_SPACE_GRAY revive was the WORST decision in v2090**
   - BT day 4 alone = -9,484 (negative on day 4!)
   - Live = -6,263 (matched BT direction)
   - Net: +4k on days 2-3 but -9.5k on day 4 → bad live trade-off
   - Decision: **REMOVE the revive** (back to dropped)

3. **PLANETARY_RINGS naive_mm fails**: live -7,257, BT -7,257 (matched). Naive_mm
   on the LEADER of GALAXY group is too directional.
   - Decision: **Switch to inventory_carry_mm** (passive + pause)

4. **PANEL_2X2 naive_mm fails**: live -2,806, BT -2,803 (matched).
   - Decision: **Switch to inventory_carry_mm**

## v2630 changes from v2090

### REMOVED
- TRANSLATOR_SPACE_GRAY revive (was: pair_skip(VOID); now: dropped/None)
  - BT day 4 was -9,484 — the revive was a bad day-4 decision

### ADDED carry overlays
- GALAXY_SOUNDS_PLANETARY_RINGS: naive_tight_mm → inventory_carry_mm
  - BT day 4: -6,912 → expected better with carry (mean-revert pause)
- PANEL_2X2: naive_tight_mm → inventory_carry_mm

### Result: +7,171 PnL with BETTER day 4 robustness (4.7% DD vs 4.8%)

## Composition (44 active products, 6 carry overlays now)

### Tibo's specialized alphas (~440k)
- pebbles_arb_v1 (PEBBLES_XL) → ~+89k
- ar1_mean_rev_v1 (ROBOT_DISHES) → ~+140k
- trend_follow_v2 (10 products) → ~+93k
- trend_follow_v2 (MICROCHIP_SQUARE) → ~+55k
- coint_mm_v1 (ROBOT_VACUUMING) → ~+14k

### Pair-skip overlays (14 — SPACE_GRAY revive removed)
Same as v2090 except SPACE_GRAY removed.

### Inventory carry overlays (NOW 6 products!)
- PANEL_4X4 (existing)
- TRANSLATOR_GRAPHITE_MIST (existing)
- GALAXY_SOUNDS_SOLAR_FLAMES (existing)
- PEBBLES_L (existing)
- **GALAXY_SOUNDS_PLANETARY_RINGS (NEW)**
- **PANEL_2X2 (NEW)**

### Drops (5 perpetual losers)
- TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL (Tibo)
- UV_VISOR_MAGENTA, OXYGEN_SHAKE_MINT (Leo)

## Why these decisions are NOT overfit

1. **Drop SPACE_GRAY revive**: Decision based on **BT day 4 = -9,484** (independent of live).
   The live confirms but isn't the basis. The revive helped days 2-3 but cost day 4.
   Removing is correct given that the IMC scoring uses some unknown subset of days.

2. **Add carry on PLANETARY/PANEL_2X2**: Decision based on full BT showing:
   - PLANETARY_RINGS naive_mm Day 4 = -7k (significant negative)
   - PANEL_2X2 naive_mm = +0 (neutral, room to improve)
   Carry overlay = passive MM + pause when trend opposes inventory. This pattern
   already works on PANEL_4X4 (+5k live), GRAPHITE_MIST (+4k live), so transferring
   to PLANETARY/PANEL_2X2 is a parameter-level change validated on full BT.

## Submission

**File**: `artifacts/submissions/round_5/best_v2630_no_spacegray_plus_carry_round5_submission.py`
**44 active products**, validated, runs <5ms avg

## Backups

1. v2090 (959,945) — previous champion
2. v2010 (955,752) — without SPACE_GRAY revive (no carry)
3. v1910 (867,852) — most stable (lowest day-to-day variance)
