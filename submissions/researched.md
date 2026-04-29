# ITERATION 1:

Research from first analyst:

v5 = 591,214 PnL (+127k from AR1 ROBOT_DISHES alone). Only 2 products show profitable AR1 at thresh=20 across all 50: ROBOT_DISHES (+5.36 net/trade) and ROBOT_IRONING (+1.20, but already tested — hurts portfolio). v5 is the ceiling for now.

Full Recap — Round 5 Research Per Product/Signal
What the correlation table (correl.md) gave us
Every pair tested for return cross-correlation at lag 1, 2, 5, 10, 20 — all max |r| < 0.01, direction accuracy ≈ 50%. The table shows level correlations from co-trending, not causal lead-lag signals. ROBOT_DISHES → GALAXY_SOUNDS_BLACK_HOLES lag=-1 shows corr 0.839 vs no-lag corr 0.839 (identical) — trivially spurious. No usable predictive signal from any pair in the table.

SNACKPACK — CHOCOLATE + VANILLA (sum ≈ 20000)
Return corr CHOC–VANI = -0.916 (same-tick anticorrelation, strong)
Sum conservation: std ≈ 40 ticks per day (not tight enough for arb, PEBBLES is 3x tighter)
snackpack_pairs_v1 tested: CHOC -1,716 + VANI +2,159 = +443 net
naive_tight_mm on same products: CHOC +18,025 + VANI +1,599 = +19,624 net
Verdict: pairs strategy is 44× worse than simple MM. Use naive_tight_mm for all 5 SNACKPACK.
SNACKPACK — PISTACHIO / STRAWBERRY / RASPBERRY
PISTA+STRAW return corr = +0.913 (move together), RASP vs STRAW = -0.924 (opposite)
PISTA+RASP sum drifts between days (std 88–162/day per day) — not conserved enough for arb
Verdict: no exploitable signal. Use naive_tight_mm.
PEBBLES — Exact Conservation Law (sum = 50000, std = 2.8)
PEBBLES_XL + PEBBLES_XS: pebbles_arb_v1 uses the exact conservation to fire taker orders when one product momentarily deviates from fair value (= 50000 − sum(others)). Fires 1.5% of ticks (447 buy + 406 sell events), entry at ~14 ticks below fair → genuine 8–14 tick edge.
XL: +89,243 (trending up, taker buys compound the conservation gain)
XS: +11,750 (trending down, taker sells profitable)
PEBBLES_L, M, S: pebbles_arb_v1 passive MM in a downtrend accumulates long positions that keep losing → L: -30k, M: -27k, S: -49k. Switched to naive_tight_mm → L: -11.5k, M: -14.8k, S: +38.7k (dramatic improvement)
Verdict: pebbles_arb_v1 for XL/XS, naive_tight_mm for L/M/S.
ROBOT_DISHES — AR1 Mean-Reversion
AR1 = -0.232 (strongest of all 50 products), spread = 7.4 ticks
When ROBOT_DISHES moves >20 ticks in one tick, the NEXT tick reverts by expected 14.3 ticks (sell signal) / 13.8 ticks (buy signal). Net after half-spread (3.7) = +10.4 ticks/trade.
ar1_mean_rev_v1 at thresh=20: +139,774 PnL over 3 days (1,560 taker signals)
Verdict: Use ar1_mean_rev_v1 thresh=20.
ROBOT_IRONING — AR1 Mean-Reversion (tested, rejected)
AR1 = -0.125, spread = 6.4 → thresh=20 gives +2.97 net/trade (~354 signals)
Portfolio test with both ROBOT_DISHES+ROBOT_IRONING: worse than ROBOT_DISHES alone (-22k)
Verdict: skip AR1 for ROBOT_IRONING, keep naive_tight_mm.
Other AR1 candidates (OXYGEN_SHAKE_EVENING_BREATH, OXYGEN_SHAKE_CHOCOLATE)
AR1 ≈ -0.09 to -0.12 but spreads are 12 ticks → net/trade ≈ 0.3 at thresh=20 (not enough to beat spread)
Verdict: naive_tight_mm only.
SLEEP_POD_LAMB_WOOL — Skipped
Loses on all 3 historical days (−29,880 total) with naive_tight_mm
Product makes a large intraday swing (+2,000 ticks rise then crash) — classic passive-MM adverse selection trap
Verdict: skip (None).
Final Config: tibo_r5_v5 — 591,214 PnL, 26.7% drawdown
Product(s)	Strategy	3-day PnL
PEBBLES_XL, XS	pebbles_arb_v1 (conservation taker)	+101k
PEBBLES_L, M, S	naive_tight_mm	+13k
ROBOT_DISHES	ar1_mean_rev_v1 thresh=20	+140k
SNACKPACK ×5	naive_tight_mm	+50k
SLEEP_POD_LAMB_WOOL	None (skip)	saved +30k
All other 38 products	naive_tight_mm	+257k


Research from 2nd analyst (in parrallel of the first): 

Round 5 — Per-Product Signal Exploration Recap
Key architectural finding (applies to all products)
Tick-level return correlation ≈ 0. The high correlations in the original table are purely level-driven (long-term price trends), not lead-lag relationships. No pair-trading or stat-arb signal exists within a day.

TrendFollowV1 (dual-EMA: fast_ema - slow_ema) failed universally. The fast EMA (hl=50) amplifies the first 50-200 ticks of intra-day noise, which frequently runs opposite to the true daily trend. Every product tested lost heavily (~-10k to -30k per product).

TrendFollowV2 (EMA vs session start price) is the working approach. Signal = EMA(mid, hl) − start_price. The EMA lags enough to filter early noise, and the threshold acts as a gate: only enter once the price has clearly committed to a direction.

Key insight per product: the only things worth tuning are:

ema_half_life: how fast EMA tracks price (longer = more lag = more noise filtering, but later entry)
threshold: how large the deviation must be before entering (must exceed the intra-day "false start" amplitude)
exit_threshold: how far the signal must cross zero to close a position
warmup_ticks: additional mandatory wait before any entry
GROUP A — Visor / Pebble / Panel
UV_VISOR_AMBER — Final: ema_hl=100, threshold=80, exit_thr=30 → +21,955

Consistently down all 3 days (−364, −1190, −1310 from start)
Very clean trend, early noise ~50-80 ticks max
threshold=80 safely clears the noise, enters short early, rides the full daily fall
Nothing else tried — worked first time
PEBBLES_XS — Final: ema_hl=150, threshold=250, exit_thr=80 → +25,450

Consistently down all 3 days (−1518, −954, −1506 from start)
Early false-up oscillation of ~200 ticks on some days → threshold=250 clears it
threshold=80 failed (entered during early spike, got whipsawed); threshold=250 with ema_hl=150 worked cleanly
PANEL_2X4 — Final: ema_hl=200, threshold=300, exit_thr=100, warmup=1000 → +9,105

Consistently up all 3 days
Day 4 has an early dip of −474 before the main up move → threshold=300 + warmup=1000 avoids it
Lower thresholds tested: entered during the false dip, went short, then lost on the up move
PEBBLES_XL — Final: ema_hl=300, threshold=500, exit_thr=150, warmup=2000 → +29,060

Mixed direction across days but large absolute moves; the product has huge intra-day swings (±800-1500)
Needed very high ema_hl + threshold + warmup to avoid the early noise
threshold=80 (v2 default): catastrophic, entered in wrong direction on every day
threshold=500, warmup=2000, ema_hl=300: filters noise, still catches large trend when it commits
GROUP B — Sleep Pods / Robots / Translator
ROBOT_MOPPING — Final: ema_hl=150, threshold=100, exit_thr=40 → +11,688

Consistently trending across days, moderate-size moves
threshold=80 worked but ema_hl=150 is slightly more stable
Nothing surprising
SLEEP_POD_COTTON — Final: ema_hl=100, threshold=80, exit_thr=30 → +4,411

Clean trend, small-to-medium moves
threshold=80 works fine; small absolute PnL because moves are modest
Day 2 shows +8,220 but loses some on days 3/4 due to partial reversals; net positive across all 3 days
SLEEP_POD_NYLON — Final: ema_hl=100, threshold=80, exit_thr=30 → +19,734

Very clean, consistent up trend all 3 days with minimal early noise
threshold=80 works perfectly; one of the best-performing products
Appears in both Group B and C (identical params); only counted once in combined
SLEEP_POD_POLYESTER — v2 (threshold=80): −1,228 → v3 (ema_hl=150, threshold=600): +13,417

Days 2 and 3: large up moves (+1766, +1118) but with early dips of −314 and −524
Day 4: reverses (−917) after early rise of +550
Problem: threshold=80 entered short during the day 2/3 dips, then price rocketed up → big loss
Fix: threshold=600 means EMA never crosses −600 during the early dip (EMA only reaches ~−200), skips day 4 entirely (rise only +550), enters long on days 2/3 after EMA confirms up direction
SLEEP_POD_SUEDE — v2 (threshold=80): −15,060 → v3 (ema_hl=300, threshold=400): +8,462

Days 2 and 3: large up moves (+1099, +1048) but early dips of −404 and −211
Day 4: reverses (−338) with an early rise of +598
Problem: threshold=80 entered short on the early dips
Fix: ema_hl=300 is very slow; the day 4 rise of +598 never gets the slow EMA above +400, so day 4 is skipped entirely. Days 2/3 have large enough moves that EMA eventually crosses +400 → enters long → profitable
SLEEP_POD_SUEDE daily path (key insight): Day 4 max=+598, but with ema_hl=300, the EMA only reaches ~+200-250 before price reverses. Threshold=400 acts as the exact filter.

TRANSLATOR_VOID_BLUE — v2 (threshold=80): −11,847 → v3 (ema_hl=150, threshold=600): +3,919

Day 2: up +1082, but early dip −533 (EMA goes to ~−200, not crossing −600 → no false short)
Day 3: ↑↓ pattern — rises +541 then falls to −426. With threshold=600, EMA reaches ~+200 during rise, never crosses +600 → no entry → PnL=0 (avoids the loss)
Day 4: up +871, small dip −118 → EMA crosses +600 → profitable
threshold=80: entered wrong direction on day 3 (went long on rise, price then fell)
UV_VISOR_MAGENTA — v2 (threshold=80): −33,395 → REMOVED

Day 2: up +1300, but huge dip −274 first
Day 3: up only +254 but enormous intra-day swing of −676 (dips deeply before going up)
Day 4: essentially flat (−49) but rises +800 intra-day (reversal trap)
Analysis: no threshold works cleanly. Day 3 dip of −676 forces threshold>676 to avoid false short. But then EMA never reaches +676 on day 3 (ends only +254) → PnL=0. Day 4 has +800 intra-day rise that triggers long entries, then reverses to −49 → loss regardless of threshold.
Conclusion: no exploitable trend. Removed entirely.
SNACKPACK_STRAWBERRY — v2 (threshold=50): −2,245 → v3 (threshold=150): −5,685 → REMOVED

Nominally "always up" but daily moves are tiny (+436, +358, +98) with large counter-direction oscillations (−446 on day 2!)
Day 2: drops −446 before rising to +436. Any threshold between 50-400 catches the dip, enters short, then loses on the full up move
threshold=50 v2: entered short during dip → −2,245
threshold=150 v3: EMA crosses −150 during the dip → enters short → price rips +882 above entry → −5,685 (worse!)
threshold=500+: would avoid all entries, PnL≈0. But the "always up" daily move is only +436 max, so threshold=500 would also skip profitable entries.
Conclusion: intra-day noise is larger than the daily signal. Not tradeable. Removed.
GROUP C — Panels / Microchip / Robots
MICROCHIP_TRIANGLE — Final: ema_hl=150, threshold=100, exit_thr=40 → +3,831

Moderate trend, some noise. threshold=100 with ema_hl=150 works cleanly
Low absolute PnL but consistently positive; no issues found
PANEL_1X2 — Final: ema_hl=100, threshold=80, exit_thr=30 → +12,550

Clean, consistent trend. threshold=80 works perfectly
One of the cleaner products to trade
PANEL_1X4 — Final: ema_hl=200, threshold=200, exit_thr=80, warmup=500 → +12,157

Consistent trend but slightly more noise than PANEL_1X2
threshold=80 tested first: minor whipsaw on some days
threshold=200 + warmup=500 + ema_hl=200: enters slightly later but more cleanly
ROBOT_IRONING — Final: ema_hl=150, threshold=100, exit_thr=40 → +17,460

Clean, consistent trend across all 3 days
threshold=100 with ema_hl=150 is the sweet spot; no issues
PANEL_2X2 — v2 (threshold=80): −18,531 → REMOVED

Daily moves are tiny (+112, −884, +196) with enormous intra-day swings (±799, ±976, ±861)
No consistent directional trend
Day 2: ends only +112 but swings −799 intra-day. Day 3: ends −884 but false-rises +776 first.
Any threshold small enough to capture the tiny daily moves gets trapped by the large intra-day noise
Any threshold large enough to avoid the noise (>900) would never trigger (daily moves are ≤884)
Conclusion: intra-day noise > daily signal. Untradeable trend-follower target. Removed.
OXYGEN_SHAKE_MORNING_BREATH — v2 (threshold=80): −3,021 → REMOVED

Day 2: clean up (+1000). Day 3: violent DOWN (−1467) after initial false rise (+374). Day 4: flat (+18)
No consistent direction. threshold=80 entered long on day 3 (false rise), then price crashed → loss
Higher thresholds (>400): might catch the day 3 down move as a short after EMA crosses −400, but timing is unreliable (EMA lags too much, enters near the bottom)
Conclusion: no consistent trend. Removed.
GROUP D — Additional consistently-trending products
OXYGEN_SHAKE_GARLIC — Final: ema_hl=150, threshold=700, exit_thr=150 → +19,445

Days 2 and 4: very large up moves (+1828, +1958) with small early dips (~−384, −394)
Day 3: only +111 end, but has large dip −662 and max +686 — noisy day
threshold=700: day 3's max is +686 (EMA reaches ~+250 → never crosses +700 → no entry, PnL=0). Days 2/4 have moves large enough that EMA crosses +700 → enter long → profitable
MICROCHIP_OVAL — Final: ema_hl=200, threshold=450, exit_thr=100 → +4,031

Consistently down all 3 days (−744, −1824, −1898)
Day 2: early false-up oscillation of +433 (EMA reaches ~+170, never crosses +450 → no long entry)
Days 3 and 4 have tiny early ups (max +397, +164) then large down moves
threshold=450 skips all false-up entries; EMA eventually crosses −450 on all 3 days → enters short → profitable
Lower absolute PnL on day 2 because EMA enters later in the down move
GALAXY_SOUNDS_BLACK_HOLES — Final: ema_hl=200, threshold=900, exit_thr=200 → +3,280

Days 2 and 4: up (+1446, +1320) but with intra-day dips (−392, −436)
Day 3: up only +688 but massive early dip of −852 — danger zone
threshold=900 is above the day 3 dip magnitude (EMA reaches ~−400, never crosses −900 → no false short). Day 3 price ends +688 but EMA never reaches +900 → PnL=0 on day 3
Days 2 and 4: large enough up moves that EMA crosses +900 → profitable
Low PnL per day due to late entry (entering near day end), but positive
PEBBLES_S — threshold=800: −2,245 → REMOVED

Nominally "always down" but day 2 is very whippy: rises +512 at t500, then erratic until final crash at t7000-t9000 (from +18 to −1029)
Day 3: tiny net move (−177) with massive whipsaw in both directions
Day 4: clean down (−937)
Problem: with threshold=800, the EMA barely crosses −800 right as the day 2 price is at its low point (−1029), then price recovers to −840 → entered short at the trough → immediate reversal → loss
threshold=1200+: would only enter on day 4 (the only clean day), giving tiny PnL
Conclusion: days 2 and 3 are too noisy for the signal size. Removed.
UV_VISOR_RED — threshold=1000: −8,005 → REMOVED

Nominally "always up" with large daily moves (+842, +182, +698)
Day 2: rises strongly to +1370 peak, then FALLS BACK to +447 at t7000 before recovering to +842. The mid-day reversal catches any entry made during the rise.
Day 3: falls to −904 before recovering to +182. The dip is larger than the threshold we'd need.
threshold=1000: enters long on day 2 rise (around price +1100), then falls to +447 mid-day, EMA holds position (signal stays positive → no exit), ends +842. But entered at +1100 and price fell to +447 mid-day before recovering = large unrealized loss. Actual PnL is the difference between entry ~+1100 and exit +842 = −2580. Day 4 similar mid-day reversal.
No threshold avoids the mid-day reversal trap because the peak is also the entry trigger.
Conclusion: intra-day reversals too large relative to daily move. Removed.
SNACKPACK_PISTACHIO — threshold=300: −70 (flat) → REMOVED

Daily moves are small (−489, −124, −282). Day 3 only −124 end.
threshold=300 barely triggers on days 2 and 4; day 3's net move is too small to overcome entry costs
Near-zero PnL after 3 days. Not worth keeping.
SLEEP_POD_LAMB_WOOL — Not tested, rejected on analysis

Nominally "always up" but day 2 peaks at +2036 and ends at only +404. Day 4 peaks at +697 and ends at +16.
The price goes way up intra-day then comes back. Any trend entry would be near the peak and exit at a much lower end-of-day price → consistent losses.
Conclusion: not a trend, it's an intra-day spike that reverts. Never tested.
Summary table
Product	v2 (th=80)	Final	Final PnL	Status
UV_VISOR_AMBER	works	ema_hl=100, th=80	+21,955	✓
PEBBLES_XS	works	ema_hl=150, th=250	+25,450	✓
PANEL_2X4	needs warmup	ema_hl=200, th=300, w=1000	+9,105	✓
PEBBLES_XL	fails	ema_hl=300, th=500, w=2000	+29,060	✓
ROBOT_MOPPING	works	ema_hl=150, th=100	+11,688	✓
SLEEP_POD_COTTON	works	ema_hl=100, th=80	+4,411	✓
SLEEP_POD_NYLON	works	ema_hl=100, th=80	+19,734	✓
SLEEP_POD_POLYESTER	fails	ema_hl=150, th=600	+13,417	✓
SLEEP_POD_SUEDE	fails	ema_hl=300, th=400	+8,462	✓
TRANSLATOR_VOID_BLUE	fails	ema_hl=150, th=600	+3,919	✓
MICROCHIP_TRIANGLE	works	ema_hl=150, th=100	+3,831	✓
PANEL_1X2	works	ema_hl=100, th=80	+12,550	✓
PANEL_1X4	needs tuning	ema_hl=200, th=200, w=500	+12,157	✓
ROBOT_IRONING	works	ema_hl=150, th=100	+17,460	✓
OXYGEN_SHAKE_GARLIC	—	ema_hl=150, th=700	+19,445	✓
MICROCHIP_OVAL	—	ema_hl=200, th=450	+4,031	✓
GALAXY_SOUNDS_BLACK_HOLES	—	ema_hl=200, th=900	+3,280	✓
UV_VISOR_MAGENTA	fails	no threshold works	—	✗ removed
SNACKPACK_STRAWBERRY	fails	noise > signal	—	✗ removed
PANEL_2X2	fails	noise > signal	—	✗ removed
OXYGEN_SHAKE_MORNING_BREATH	fails	no consistent direction	—	✗ removed
PEBBLES_S	—	EMA enters at trough, price recovers	—	✗ removed
UV_VISOR_RED	—	mid-day reversal trap	—	✗ removed
SNACKPACK_PISTACHIO	—	moves too small	—	✗ removed
SLEEP_POD_LAMB_WOOL	—	intra-day spike, not trend	—	✗ rejected
The ~25 remaining products (other Galaxy Sounds, other Oxygen Shakes, other Snackpacks, etc.) were not individually analyzed — they either showed zero or inconsistent PnL in the v1 group backtests.


Research from 2nd analyst (continued from iteration 1):

# Iteration 2 — v6: TrendFollowV2 where it beats v5 naive_mm

### Context
v5 (1st analyst) = **591,214 PnL** using naive_tight_mm for ~42 products, pebbles_arb_v1 for PEBBLES_XL/XS, ar1_mean_rev_v1 for ROBOT_DISHES, and None for SLEEP_POD_LAMB_WOOL.

Goal: build v6 = v5 base, replacing naive_mm with trend_follow_v2 only where trend_follow_v2 beats naive_mm on the 3-day realistic backtest.

### Method
Ran full v5 backtest with JSON output to get per-product PnL for every product. Then compared with the trend_v2 PnLs from iteration 1. Products where trend_v2 PnL > v5 PnL → use trend_v2 in v6. All others → keep v5 strategy.

### Full comparison table (naive_mm vs trend_v2, where different)

| Product | v5 (naive_mm) | trend_v2 | Winner | Delta |
|---------|--------------|---------|---------|-------|
| UV_VISOR_AMBER | +14,584 | +21,955 | **trend_v2** | +7,371 |
| PANEL_2X4 | +16,338 | +9,105 | v5 | -7,233 |
| ROBOT_MOPPING | **-13,471** | +11,688 | **trend_v2** | +25,159 |
| SLEEP_POD_COTTON | +1,231 | +4,411 | **trend_v2** | +3,180 |
| SLEEP_POD_NYLON | +14,530 | +19,734 | **trend_v2** | +5,204 |
| SLEEP_POD_POLYESTER | +8,623 | +13,417 | **trend_v2** | +4,794 |
| SLEEP_POD_SUEDE | +13,234 | +8,462 | v5 | -4,772 |
| TRANSLATOR_VOID_BLUE | +17,546 | +3,919 | v5 | -13,627 |
| MICROCHIP_TRIANGLE | +12,214 | +3,831 | v5 | -8,383 |
| PANEL_1X2 | **-18,154** | +12,550 | **trend_v2** | +30,704 |
| PANEL_1X4 | +26,897 | +12,157 | v5 | -14,740 |
| ROBOT_IRONING | +14,392 | +17,460 | **trend_v2** | +3,068 |
| OXYGEN_SHAKE_GARLIC | +15,987 | +19,445 | **trend_v2** | +3,458 |
| MICROCHIP_OVAL | +10,675 | +4,031 | v5 | -6,644 |
| GALAXY_SOUNDS_BLACK_HOLES | +15,419 | +3,280 | v5 | -12,139 |
| PEBBLES_XL (arb) | +89,243 | +29,060 | v5 arb | -60,183 |
| PEBBLES_XS (arb) | +11,749 | +25,450 | **trend_v2** | +13,701 |

**Key insight**: PEBBLES_XS arb only makes +11,749 while trend_v2 makes +25,450 — switch XS to trend_v2. The pebbles_arb for XL (+89,243) is untouchable.

**Key insight**: PANEL_1X2 was -18,154 with naive_mm (adverse selection due to consistent trending), +12,550 with trend_v2. ROBOT_MOPPING similarly: -13,471 → +11,688. The large swing products are actively LOSING with naive_mm.

**Why does v5 win on some products despite trends?**
- PANEL_1X4: v5 naive_mm = +26,897 >> trend_v2 = +12,157. Panel_1X4 has a consistent trend but the naive_mm is more profitable because the spread is narrow and the product fills continuously. The trend_v2 only enters once per day while naive_mm collects spread all day.
- TRANSLATOR_VOID_BLUE, MICROCHIP_TRIANGLE, GALAXY_SOUNDS_BLACK_HOLES: similar logic — MM captures spread throughout the day, while trend_v2 enters late and captures only part of the move.

### New product discovered: MICROCHIP_SQUARE
Not in my iteration 1 list. Path analysis shows:
- Day 2: end=+2456, early dip=-168 at t1000 (then strong rise)
- Day 3: end=+3438, tiny dip=-62 (then strong rise to +4024 peak, ends +3438)
- Day 4: end=-2278, drops from t500 (-102), -469 at t1000, -1289 at t2000

With ema_hl=100, threshold=250:
- Day 2/3: EMA never crosses -250 (early dips are < 250), then crosses +250 → enters long → profitable
- Day 4: EMA crosses -250 around t700-800 → enters short → profitable

v5 naive_mm = +8,704 for MICROCHIP_SQUARE. Expected trend_v2 >> this.

### Products explored but NOT tradeable (new findings)
Checked ~15 unexplored products from the 50-product universe:
- **TRANSLATOR_SPACE_GRAY** (-11,188 in v5): days 2+4 down, day 3 up — inconsistent
- **TRANSLATOR_GRAPHITE_MIST** (-4,418 in v5): day 4 reversal trap (rises +448 then crashes)
- **UV_VISOR_MAGENTA** (-7,314 in v5): confirmed reversal trap (already rejected in iter 1)
- **MICROCHIP_CIRCLE**: day 2 down, day 3 mixed, day 4 up — inconsistent
- **MICROCHIP_RECTANGLE**: days 2+3 down but day 4 up — inconsistent
- **GALAXY_SOUNDS_PLANETARY_RINGS**: days 2+3 up, day 4 down — inconsistent
- **GALAXY_SOUNDS_SOLAR_FLAMES**: day 2 up, day 3 down — inconsistent
- **PANEL_4X4**: days 2+4 are reversal traps (up then down)
- **ROBOT_VACUUMING**: only day 3 has clean trend
- **ROBOT_LAUNDRY**: no consistent trend

### Final v6 config (tibo_r5_v6)
**Baseline**: tibo_r5_v5 (591,214 PnL)
**Changes**: 9 products switched to trend_v2, PEBBLES_XS switched from arb to trend_v2
**Expected delta**: ~+97k PnL → estimated **~688k+ PnL**

Products in v6:
- PEBBLES_XL: pebbles_arb_v1 (unchanged from v5)
- PEBBLES_XS: **trend_v2** (ema_hl=150, th=250) — was arb
- PEBBLES_L/M/S: naive_tight_mm (unchanged)
- ROBOT_DISHES: ar1_mean_rev_v1 (unchanged)
- SNACKPACK ×5: naive_tight_mm (unchanged)
- SLEEP_POD_LAMB_WOOL: None (unchanged)
- UV_VISOR_AMBER: **trend_v2** (ema_hl=100, th=80)
- ROBOT_MOPPING: **trend_v2** (ema_hl=150, th=100)
- SLEEP_POD_COTTON: **trend_v2** (ema_hl=100, th=80)
- SLEEP_POD_NYLON: **trend_v2** (ema_hl=100, th=80)
- SLEEP_POD_POLYESTER: **trend_v2** (ema_hl=150, th=600)
- PANEL_1X2: **trend_v2** (ema_hl=100, th=80)
- ROBOT_IRONING: **trend_v2** (ema_hl=150, th=100)
- OXYGEN_SHAKE_GARLIC: **trend_v2** (ema_hl=150, th=700)
- MICROCHIP_SQUARE: **trend_v2** (ema_hl=100, th=250) → +54,771 vs v5 +8,704 = **+46,067**!
- All remaining products: naive_tight_mm (from base ROUND_5 config)

### Actual v6 backtest result (confirmed)
**tibo_r5_v6 = 733,918 PnL** (+142,704 over v5, +24% improvement)
Drawdown: 40,920 / 14.5% (significantly better than v5's 44,884 / 26.7%)

### Final file locations
- Config: `MEMBER_OVERRIDES["tibo_r5_v6"]` in `prosperity/config.py`
- Backtest wrapper: `submissions/tibo_r5_v6.py`
- IMC submission: `artifacts/submissions/round_5/tibo/tibo_r5_v6_round5_submission.py`


# Iteration 3 (v7):

## Research from 1st analyst

## Context
Starting from tibo_r5_v6 (733,918 PnL). Three tasks: (A) tune naive_tight_mm maker_size per group, (B) test PEBBLES_L/M conservation taker-only, (C) cointegration analysis within groups.

---

## Task A — maker_size tuning

**Method**: classified all naive_tight_mm products in v6 by 3-day PnL sign consistency.

**All 3 days positive** (safe to increase — won't amplify losses):  
PANEL_1X4, OXYGEN_SHAKE_CHOCOLATE, OXYGEN_SHAKE_EVENING_BREATH, TRANSLATOR_VOID_BLUE, PANEL_2X4, UV_VISOR_ORANGE, OXYGEN_SHAKE_MORNING_BREATH, MICROCHIP_OVAL, UV_VISOR_RED, GALAXY_SOUNDS_DARK_MATTER, PANEL_2X2  
Plus SNACKPACK × 5 (all explicitly positive).

**Key finding — saturation at maker_size=5**: the realistic backtest fill model limits fills to market trade sizes. Testing maker_size=3,5,7 showed that 5 and 7 give IDENTICAL results (market provides ≤5 units/tick at our price). Going from 3→5 captures more fills; going from 5→7 adds nothing.

| Config | Total PnL | Delta vs v6 |
|--------|-----------|-------------|
| v6 baseline (size=3 all) | 733,918 | — |
| SNACKPACK only → size=5 | 738,904 | +4,986 |
| All 16 all-positive → size=5 | 741,720 | +7,802 |
| size=7 (same 16 products) | 741,720 | identical to size=5 |

**Verdict**: set maker_size=5 for all 16 consistently-positive products. Applied in best_v7.

---

## Task B — PEBBLES_L/M conservation taker-only

**Hypothesis**: the pebbles_arb_v1 strategy fires 447 buy + 406 sell conservation takers per product. For downtrending L/M, removing the passive MM (passive_size=0) might isolate the genuine conservation edge without accumulating losing long positions.

**Result** (pebbles_lm_taker_test config):
- PEBBLES_L taker-only: **-23,862** vs naive_tight_mm **-11,500** → **WORSE by 12k**
- PEBBLES_M taker-only: similar degradation
- Total portfolio: 712,009 vs 733,918 → **-21,909 worse**

**Why it failed**: the conservation taker fires BUY orders when a product temporarily underperforms others. For downtrending L/M, those "underperformance dips" are genuine trend accelerations — buying into them loses money because L/M continue falling. Without any passive component to offset, the taker-only strategy generates pure directional losses.

**Verdict**: keep naive_tight_mm for PEBBLES_L/M. No improvement possible via conservation arb on the downtrending pebbles without a directional filter.

---

## Task C — Within-group cointegration analysis (report only, not implemented)

Method: Engle-Granger cointegration test on all pairs within each group + each product vs group average, 3-day data.

**SNACKPACK** — most cointegrated group, multiple significant pairs:
- SNACKPACK_RASPBERRY ↔ SNACKPACK_VANILLA: **p=0.0068** (very strong)
- SNACKPACK_RASPBERRY ↔ SNACKPACK_STRAWBERRY: p=0.0242
- SNACKPACK_PISTACHIO ↔ SNACKPACK_STRAWBERRY: p=0.0313
- SNACKPACK_CHOCOLATE ↔ SNACKPACK_STRAWBERRY: p=0.0356
- SNACKPACK_CHOCOLATE ↔ SNACKPACK_PISTACHIO: p=0.0453
- SNACKPACK_RASPBERRY vs GROUP_AVG: p=0.0251

**MICROCHIP**: RECTANGLE ↔ SQUARE: p=0.0196 (significant pair)

**Moderate (p<0.10)**: GALAXY_SOUNDS_SOLAR_FLAMES ↔ SOLAR_WINDS, MICROCHIP_OVAL ↔ TRIANGLE, UV_VISOR_AMBER ↔ MAGENTA, ROBOT_LAUNDRY ↔ VACUUMING, SLEEP_POD_LAMB_WOOL ↔ NYLON, OXYGEN_SHAKE_CHOCOLATE ↔ GARLIC

**No cointegration**: PEBBLES, PANEL, TRANSLATOR groups.

**Key caveat**: we already tested SNACKPACK spread trading (snackpack_pairs_v1 using CHOC+VANI sum conservation) and it underperformed naive_tight_mm by 44×. The Engle-Granger test confirms cointegration exists but cointegration alone doesn't guarantee profitability. The spread half-lives are 800–3000 ticks (8–30 minutes), which combined with the 16-tick bid-ask spread makes profitable round trips marginal. Would require very tight spread management, monitoring spread z-score and entering only at 1.5σ+ deviations.

**Most promising for future exploration**: SNACKPACK_RASPBERRY ↔ SNACKPACK_VANILLA (p=0.0068) — the tightest cointegration. RASPBERRY has return corr=-0.924 with STRAWBERRY (same-tick) which might compound the cointegration signal.

---

## Final config: best_v7 = 741,720 PnL, 14.5% drawdown

Changes from v6:
- SNACKPACK × 5: maker_size 3 → **5** (+4,986)
- PANEL_1X4, OXYGEN_SHAKE_CHOCOLATE/EVENING_BREATH/MORNING_BREATH, TRANSLATOR_VOID_BLUE, PANEL_2X4, UV_VISOR_ORANGE/RED, MICROCHIP_OVAL, GALAXY_SOUNDS_DARK_MATTER, PANEL_2X2: maker_size 3 → **5** (+2,816)
- All other strategies unchanged from v6

Config: `MEMBER_OVERRIDES["best_v7"]` in `prosperity/config.py`  
Wrapper: `submissions/best_v7.py`



# Iteration 4 (v8) — Cointegration Pairs Trading
Reference: 1st analyst

## Context
Starting from best_v7 (741,720 PnL). Goal: exploit the cointegration relationships found in iteration 3 to build trading strategies.

---

## Key findings before building strategies

**SNACKPACK cointegration is spurious**: ADF tests show RASPBERRY (p=0.0014) and VANILLA (p=0.0376) are individually near-stationary. Their "cointegration" is really just that each product mean-reverts on its own, not a genuine pair relationship. The naive_tight_mm already captures this. Not exploited.

**Non-SNACKPACK pairs simulation** (normalized spread: A/mean_A - B/mean_B, 10 units, taker at bid/ask):

| Pair | HL (ticks) | Best simulated PnL | Current v7 combined | Delta |
|------|-----------|-------------------|--------------------|----|
| MICROCHIP_OVAL ↔ TRIANGLE | 1059 | +75,210 | +22,889 | +52k |
| ROBOT_LAUNDRY ↔ VACUUMING | 1015 | +45,935 | +6,371 | +40k |
| SLEEP_POD_LAMB_WOOL ↔ NYLON | 1197 | +29,340 | +19,734 | +10k |
| GALAXY_SOUNDS_FLAMES ↔ WINDS | 3762 | +3,645 | +1,090 | +3k |
| MICROCHIP_RECTANGLE ↔ SQUARE | 6285 | -31,880 | +59,446 | ← don't touch |
| UV_VISOR_AMBER ↔ MAGENTA | 7378 | -3,165 | +14,640 | ← skip |

---

## Two strategies built

**`coint_pairs_v1`** (pure pairs, taker only):  
- Normalized z-score of A/mA - B/mB  
- Entry at ±entry_z, exit at 0

**`coint_mm_v1`** (hybrid: coint z-score taker + passive naive_mm):  
- Same z-score signal for taker orders  
- ALSO posts passive bid/ask at best_bid+1 / best_ask-1 (passive_size units)  
- Captures both spread and cointegration reversion

---

## Backtest progression (vs best_v7 = 741,720)

| Config | Strategy | Delta vs v7 |
|--------|----------|-------------|
| v8a: OVAL+TRI (coint_pairs_v1) | pure pairs | +12,767 |
| v8b: LAUNDRY+VACUUMING (coint_pairs_v1) | pure pairs | +13,038 |
| v8c: LAMB_WOOL+NYLON (coint_pairs_v1) | pure pairs | -12,078 ← HURTS (NYLON trend_v2 disrupted) |
| v8d: GALAXY pair | coint_pairs_v1 | +10k over v5, but -10k vs v8e |
| v8ab combined | coint_pairs_v1 | +25,805 |
| **v8e: OVAL=naive, TRI+LAUNDRY+VAC on coint_pairs_v1** | mixed | +29,124 |
| **v8g: TRI+LAUNDRY+VAC on coint_mm_v1 (+ passive MM)** | hybrid | +60,626 |
| **v8h: ALL 4 MICROCHIP+ROBOT on coint_mm_v1** | hybrid | +66,859 |
| **v8j: + RECTANGLE reads from SQUARE** | hybrid | +73,184 |
| **v8m: entry_z=1.2 for MICROCHIP (was 1.5)** | hybrid | +77,488 |

Key insight: `coint_mm_v1` (hybrid) dramatically outperforms `coint_pairs_v1` (pure) because it combines spread capture (passive MM) with the cointegration signal. The MICROCHIP products especially benefit since they have tight spreads.

---

## Parameters for best_v8 cointegration products

| Product | Strategy | Partner | z_win | entry_z | passive_size |
|---------|----------|---------|-------|---------|--------------|
| MICROCHIP_OVAL | coint_mm_v1 | TRIANGLE | 1000 | 1.2 | 5 |
| MICROCHIP_TRIANGLE | coint_mm_v1 | OVAL | 1000 | 1.2 | 3 |
| MICROCHIP_RECTANGLE | coint_mm_v1 | SQUARE | 1000 | 1.2 | 3 |
| ROBOT_LAUNDRY | coint_mm_v1 | VACUUMING | 2000 | 1.5 | 3 |
| ROBOT_VACUUMING | coint_mm_v1 | LAUNDRY | 2000 | 1.5 | 3 |

MICROCHIP_SQUARE stays on trend_v2 (untouched, +54k). RECTANGLE reads SQUARE's price as cointegration signal.

---

## Rejected pairs (tested, worse than v7)

- SLEEP_POD_LAMB_WOOL ↔ NYLON (v8c): -12k vs v7. NYLON trend_v2 is disrupted when both use coint.
- GALAXY_SOUNDS_SOLAR_FLAMES ↔ WINDS (v8f): -10k vs v8e. Long HL=3762 means slow reversion.
- OXYGEN_SHAKE_CHOCOLATE ↔ GARLIC (v8k): -4k vs v8h. Current strategies +42k >> pairs +12k.
- UV_VISOR_AMBER ↔ MAGENTA: simulation -3k. AMBER trend_v2 irreplaceable.
- MICROCHIP_RECTANGLE ↔ SQUARE pure pairs: simulation -32k. SQUARE uptrend too strong.

---

## First backtest of best_v8: 819,208 PnL, 26% drawdown

Config at that point included MICROCHIP_OVAL/TRIANGLE on `coint_mm_v1`.

---

# ITERATION 5: Live diagnosis and best_v8 revision

## Live test results (v8 vs v7)

| Version | Live PnL | Notes |
|---------|----------|-------|
| best_v7 | 20,960 | Baseline |
| best_v8 (original) | 16,009 | −4,951 vs v7 |
| best_v8 (EWMA fix) | 16,001 | Memory overflow fixed, same result |

## Root cause: traderData memory overflow (FIXED)

`coint_mm_v1` originally stored a `zbuf` rolling list of 1000–2000 floats per product.  
5 coint products × ~28,000 chars each ≈ **140,500 chars** total in traderData.  
This silently overflowed IMC's traderData limit, corrupting the state of `trend_v2` strategies (SLEEP_POD_NYLON, ROBOT_MOPPING, PANEL_1X2 all showed position=0 in v8 vs ±10 in v7).

**Fix**: replaced `zbuf` list with EWMA running mean + variance (Welford O(1) update). Memory reduced from ~140,500 to ~600 chars (234× reduction). Applied to `coint_mm_v1.py`.

However, even after the fix, the live PnL gap remained (16,001 vs 20,960). The memory fix was necessary but not sufficient.

## Root cause 2: MICROCHIP cointegration pair broke down in live

Per-product live PnL comparison (best_v8_new vs best_v7):

| Product | Strategy in v8 | v7 PnL | v8 PnL | Delta |
|---------|---------------|--------|--------|-------|
| MICROCHIP_OVAL | coint_mm_v1 | +2,619 | −1,371 | **−3,990** |
| MICROCHIP_TRIANGLE | coint_mm_v1 | +3,036 | +2,113 | **−923** |
| ROBOT_LAUNDRY | coint_mm_v1 | −2,368 | −2,368 | 0 |
| ROBOT_VACUUMING | coint_mm_v1 | +979 | +952 | −27 |

The **−4,913 delta is entirely explained by MICROCHIP_OVAL and TRIANGLE**.

What happened on OVAL: at ts=58,000 and ts=63,200 the z-score fired taker BUY orders (OVAL looked cheap vs TRIANGLE). But OVAL kept falling from 7,401 → 7,239 → 7,128 — the spread widened from −1,900 to −2,237 over 14,000 ticks without reverting. Classic "catching a falling knife."

The cointegration relationship exists in the historical data but the spread's **reversion timescale** is much longer than `z_win=1000` ticks assumes. With alpha=2/1001 and no warmup from the previous day, the EWMA statistics start fresh each live day, making the z-score unreliable in the first few thousand ticks. The ROBOT_LAUNDRY/VACUUMING pair worked because their cointegration relationship held (0 delta).

## Fix applied: best_v8 updated

MICROCHIP_OVAL and MICROCHIP_TRIANGLE reverted to `naive_tight_mm` (same as v7).  
MICROCHIP_RECTANGLE kept on `coint_mm_v1` reading SQUARE (live delta was only −18).  
ROBOT_LAUNDRY/VACUUMING kept on `coint_mm_v1` (worked fine in live, 0 delta).

## Final config: best_v8 = 767,422 backtest PnL

Config: `MEMBER_OVERRIDES["best_v8"]` in `prosperity/config.py`  
Wrapper: `submissions/best_v8.py`  
Strategy files: `coint_mm_v1.py` (O(1) EWMA memory), `coint_pairs_v1.py`

| Product | Strategy | Change vs original v8 |
|---------|----------|-----------------------|
| MICROCHIP_OVAL | naive_tight_mm size=5 | ← reverted (coint broke live) |
| MICROCHIP_TRIANGLE | naive_tight_mm size=3 | ← reverted |
| MICROCHIP_RECTANGLE | coint_mm_v1 reads SQUARE | unchanged |
| ROBOT_LAUNDRY | coint_mm_v1 z_win=2000 | unchanged (worked in live) |
| ROBOT_VACUUMING | coint_mm_v1 z_win=2000 | unchanged |

Backtest is lower than original v8 (767k vs 819k) because the historical data favors the MICROCHIP coint — but live results showed it doesn't hold. The v7 baseline in live was +20,960; this config should be close to that or better (ROBOT coint adds ~0 delta in live).

# ITERATION 4: Live MM inventory carry fix

Reference: 3rd analyst

## Goal

Analyze the live `best_v7` logs instead of blindly optimizing backtests, focusing first on the products still using `naive_tight_mm`.

## What the live logs showed

The main issue was not toxic fills. On the worst live MM names, short-horizon markouts were still positive, but the strategy repeatedly finished with leftover long inventory into a falling close.

Clearest examples from live:

| Product | Live PnL | Final pos | Mid move | Read |
|---------|----------|-----------|----------|------|
| TRANSLATOR_SPACE_GRAY | -6,777 | +7 | -669 | good fills, bad close carry |
| GALAXY_SOUNDS_PLANETARY_RINGS | -7,335 | +7 | -778 | same pattern |
| PANEL_2X2 | -2,806 | +7 | -386 | same pattern |
| UV_VISOR_YELLOW | -422 | +7 | -65.5 | same pattern |

So the live failure mode was: we got paid to accumulate inventory, then donated MTM by carrying it into the end of the session.

## What I tested

I created a sequence of additive-only live-MM variants:

- first variant: broad inventory-aware MM overlay on 9 weak live names
- second variant: softer version, keeping intraday MM but adding earlier late-session flattening
- third variant: very narrow final-ticks flattening on 4 names
- `best_v7_live_mmfix4`: final kept version, same close-only idea but only on 3 names:
  - `TRANSLATOR_SPACE_GRAY`
  - `PANEL_2X2`
  - `UV_VISOR_YELLOW`

Shared strategy kept: `late_flatten_tight_mm_v1`

Rejected:

- the first two broader variants were too intrusive and gave up too much historical PnL
- the third narrow variant improved day 4 but still hurt the `2/3/4` historical chain too much
- `GALAXY_SOUNDS_PLANETARY_RINGS` was removed from the final version because the close-only intervention helped the live replay thesis but worsened its day-4 backtest

## Final keep: `best_v7_live_mmfix4`

Files:

- `submissions/best_v7_live_mmfix4.py`
- `prosperity/config.py`
- `prosperity/strategies/round_5/tibo/late_flatten_tight_mm_v1.py`

Behaviour:

- keep `naive_tight_mm` intraday
- only intervene at the very end of the session
- stop leaning into the same-side inventory late
- use a tiny passive/taker flatten when position is still large near the close

## Why this works better

This fix matches the actual live failure mode much more closely than the earlier broad overlays. It does not try to redesign MM logic intraday. It only removes the specific end-of-session inventory leak that showed up in the logs.

Results:

| Config | Days | PnL | Max DD |
|--------|------|-----|--------|
| `best_v7` | 4 | 314,243 | 19,330 |
| `best_v7_live_mmfix4` | 4 | 319,917 | 21,182 |
| `best_v7` | 2/3/4 | 741,720 | 40,294 |
| `best_v7_live_mmfix4` | 2/3/4 | 747,656 | 38,227 |

Takeaway:

`best_v7_live_mmfix4` is the first live-motivated MM fix from this line of research that improved both the live-replay day and the full historical sanity check. That is why it was kept and the earlier variants were discarded.
---

## Iteration 3 — v7_2: Fixing losers + UV_VISOR_YELLOW (2nd analyst)

### Context
v6 baseline = **733,918 PnL**. Goal: fix 4 user-flagged losers + investigate correlations.

### Q1: Cross-asset correlation strategy

The `research/correl.md` table shows 11 product pairs where product_A leads product_B by `|lag|` ticks.
Key pairs and actionability:

| A (leader) | B (follower) | lag | corr | Current strats | Edge? |
|---|---|---|---|---|---|
| UV_VISOR_AMBER | PEBBLES_XS | 692 | 0.9629 | Both trend_v2 | Low — both already capture same trend |
| SLEEP_POD_NYLON | PANEL_1X2 | 1000 | 0.8412 | Both trend_v2 | Low — same |
| PANEL_1X4 → ROBOT_IRONING | 1000 | 0.8750 | trend_v2 / trend_v2 | Could enter IRONING earlier |
| TRANSLATOR_VOID_BLUE | SLEEP_POD_SUEDE | 1000 | 0.8444 | naive_mm / naive_mm | Potential: use VOID_BLUE trend to trade SUEDE |
| UV_VISOR_MAGENTA | SLEEP_POD_SUEDE | 1000 | 0.8669 | None / naive_mm | — |

**Conclusion**: Where both products already use trend_v2 independently (AMBER→XS, NYLON→1X2), the cross-asset signal adds minimal PnL (both enter on the same underlying move). The more interesting case would be TRANSLATOR_VOID_BLUE → SLEEP_POD_SUEDE: using Void_Blue's EMA momentum to enter Suede early. Implementation would require reading Void_Blue's order depth inside Suede's strategy. Estimated gain: ~3-5k (low priority vs simpler fixes).

**Not implemented in v7_2** — the simpler "set losers to None" approach yielded +83k which dwarfs the ~5k potential from lead-lag signals.

### Q2: Fixing the losers

#### Full per-product PnL audit (v6)
Running the v6 backtest with `--json-out` revealed the actual losers:

| Product | v6 PnL | Fix |
|---|---|---|
| PEBBLES_M | -14,756 | None |
| PEBBLES_L | -11,500 | None |
| TRANSLATOR_SPACE_GRAY | -11,188 | None |
| PANEL_4X4 | -10,672 | None |
| UV_VISOR_MAGENTA | -7,314 | None |
| GALAXY_SOUNDS_SOLAR_FLAMES | -6,034 | None |
| TRANSLATOR_GRAPHITE_MIST | -4,418 | None |
| ROBOT_VACUUMING | -2,700 | None |

**PEBBLES_L and M** were bigger losers than the user-flagged products. 

#### Investigation: PEBBLES_L/M — why naive_mm fails

The pebbles conservation law (XL+XS+L+M+S=50,000) holds PERFECTLY at mid prices at every tick. This means for PEBBLES_L:
- `fair_L = 50,000 - XL - XS - M - S ≈ market_mid_L` always
- XL arb works because XL has the largest moves (+3877/−1167/+3931 per day)
- L and M have smaller, noisier moves. The MM gets adversely selected on larger intraday swings (PEBBLES_L: day4 -1798; PEBBLES_M: day3 +1883). naive_mm accumulates on the wrong side.

**Attempted fix**: pebbles_arb_v1 on L and M (same conservation arb as XL). Result: WORSE (-30k and -27k vs -11.5k and -14.8k).
For XS/S, the issue is that XS and S have their own strong independent trends that oppose what the arb wants to do:
XS arb: −13,701 vs baseline (arb buys XS "cheap" vs conservation while XS is in a −40% 3-day downtrend)
S arb: −87,684 vs baseline (same problem, worse because S has more ticks where arb is fighting the trend)
XL arb works because XL is the basket's biggest mover — it creates genuine temporary dislocations vs the other four. XS and S are themselves driven by XL's movement signal via the conservation, so arbing them just bets on XS/S's individual trend reverting, which they don't.

**Why arb fails**: Because `fair_L ≈ market_mid_L` always, there's no price-level dislocation to exploit. The arb fires on bid/ask spread noise (1363 aggressive fills on L/day4 alone), paying spread 4072 times across 3 days. 

**Resolution**: Set PEBBLES_L and PEBBLES_M to None. PEBBLES_S with naive_mm keeps making +38,672 (different market dynamics — consistent small downtrend with active market).

#### UV_VISOR_YELLOW: NEW product discovered

Not in previous analysis. Huge daily moves: day2=+1458, day3=+314, day4=-2005. trend_v2 results:

| threshold | day2 | day3 | day4 | total |
|---|---|---|---|---|
| 500 | +8,985 | -7,805 | +12,580 | +13,760 |
| 600 | +8,485 | -7,895 | +13,080 | +13,670 |
| **700** | **+8,075** | **0** | **+11,210** | **+19,285** |
| 800 | +6,875 | 0 | +10,600 | +17,475 |

**Key finding**: Day 3 EMA signal reaches minimum −633. Threshold=500/600 triggers a false short (enters at t5700 price=10850, exits at t6863 price=11640 → −7,895 loss). Threshold=700 skips day3 entirely → 0 PnL day3.

threshold=700 is optimal: **+19,285 vs naive_mm +4,592 = +14,693 gain**.

### Final v7_2 config
**tibo_r5_v7_2 = 817,194 PnL** (+83,276 over v6)

Changes vs v6:
- PEBBLES_L → None (+11,500)
- PEBBLES_M → None (+14,756)
- UV_VISOR_MAGENTA → None (+7,314)
- TRANSLATOR_SPACE_GRAY → None (+11,188)
- PANEL_4X4 → None (+10,672)
- GALAXY_SOUNDS_SOLAR_FLAMES → None (+6,034)
- TRANSLATOR_GRAPHITE_MIST → None (+4,418)
- ROBOT_VACUUMING → None (+2,700)
- UV_VISOR_YELLOW → trend_v2 th=700 (+14,693)

Only remaining loser: OXYGEN_SHAKE_MINT at -36 (negligible).

Files:
- Config: `MEMBER_OVERRIDES["tibo_r5_v7_2"]` in `prosperity/config.py`
- Backtest wrapper: `submissions/tibo_r5_v7_2.py`
- IMC submission: `artifacts/submissions/round_5/tibo/tibo_r5_v7_2_round5_submission.py` (54,800 bytes, all checks passed)

The submission: tibo_r5_v7_2_best_round5_submission and config tibo_r5_v7_2_best integrates baseline v7 into v7_2, it is the best v7.


---

# Iteration 4 — v8_a: Live-backtest divergence diagnosis and fix (2nd analyst)

## Context

v7_2_best backtest = **824,996 PnL** but live simulation = **14,539 PnL** vs v7_best live = **20,960 PnL** — v7_2_best performed WORSE in live despite being +83k better in backtest. Investigated by comparing per-product final PnL from the official JSON logs.

## Diagnosis: overfitting by removing products on 3-day history

The 8 products set to `None` in v7_2_best were classified as losers based on backtest days 2/3/4. On the live day, **6 of them reversed and were profitable** under v7_best's naive_mm:

| Product | Backtest 3-day (v6) | Live day PnL (v7_best) | v7_2_best action | Live cost |
|---------|--------------------|-----------------------|------------------|-----------|
| PANEL_4X4 | −10,672 | **+5,567** | Removed ✗ | −5,567 |
| TRANSLATOR_GRAPHITE_MIST | −4,418 | **+4,191** | Removed ✗ | −4,191 |
| GALAXY_SOUNDS_SOLAR_FLAMES | −6,034 | **+2,306** | Removed ✗ | −2,306 |
| ROBOT_VACUUMING | −2,700 | **+979** | Removed ✗ | −979 |
| UV_VISOR_MAGENTA | −7,314 | **+598** | Removed ✗ | −598 |
| PEBBLES_L | −11,500 | **+337** | Removed ✗ | −337 |
| TRANSLATOR_SPACE_GRAY | −11,188 | −6,777 | Removed ✓ | +6,777 |
| PEBBLES_M | −14,756 | −357 | Removed ✓ | +357 |
| UV_VISOR_YELLOW | (not in v7_best) | −422 | Added trend_v2 ✓ | +422 |

**Net impact**: correctly removing TRANSLATOR_SPACE_GRAY + PEBBLES_M saved +7,134. But wrongly removing 6 profitable products cost −13,978. Net: **−6,421** (matches observed live gap exactly).

**Root cause**: naive_mm is profitable when prices are flat or rising (spread capture + long inventory appreciates). It loses when prices trend DOWN and the strategy accumulates long inventory that keeps losing. Days 2/3/4 had specific adverse trends for these 6 products; the live day reversed. Setting them to None is **regime-overfitting** to a 3-day window.

**Structural distinction** (correctly vs wrongly removed):
- TRANSLATOR_SPACE_GRAY: down on days 2/4 in backtest AND down on live → consistently bad
- PEBBLES_M: negative on 2/3 in backtest AND losing in live → consistently bad
- The 6 wrongly-removed products: volatile, reversing direction across days (no consistent regime)

## Fix: tibo_r5_v8_a — restore with halved position limit

**Strategy**: restore the 6 wrongly-removed products using `position_limit=5` (half of standard 10). Same naive_tight_mm strategy, but maximum inventory capped at 5 units instead of 10.

- When prices trend against us: max mark-to-market loss is halved (5 × move vs 10 × move)
- When prices are favorable: captures half the gain, but still participates
- TRANSLATOR_SPACE_GRAY and PEBBLES_M: stay at None (both lost in live too)

**Backtest result** (days 2/3/4, realistic mode):

| Config | Backtest 3-day | Live day |
|--------|---------------|----------|
| v7_2_best | 824,996 | 14,539 |
| **v8_a** | **825,200 (+204)** | est. **~21,500** |

Backtest is essentially identical (+204) because halving the limit roughly halves both the losses (when bad) and gains (when good), and the halved losses from the restored products cancel out. The live improvement is structural: instead of 0 PnL on 6 profitable products, we capture ~half of what v7_best would have made.

Also explored v8_b (trend_v2 at limit=5 for volatile products instead of naive_mm): backtest 822,315 (−2,681 vs baseline), discarded.

## Files

- Config: `MEMBER_OVERRIDES["tibo_r5_v8_a"]` in `prosperity/config.py`
- Backtest wrapper: `submissions/tibo_r5_v8_a.py`
- IMC submission: `artifacts/submissions/round_5/tibo/tibo_r5_v8_a_round5_submission.py` (56,687 bytes, all checks passed, 47 products)

---

# Iteration 6 — best_v12_A3 live-v10 loss diagnosis (3rd analyst)

## Context

Started from `best_v10`, re-read prior research, re-checked the advisor notes in `round_5_wiki.txt`, then used the live `v10` logs as the primary source of truth instead of blindly trusting the backtest.

Live-v10 diagnosis:

- the worst live cluster remained the MM-heavy names where we accumulated inventory and then got marked down late
- but only some of those names were safe to touch, because several of them still had strong backtest edge and lost badly when we added late flattening
- `ROBOT_LAUNDRY` was a different failure mode: the coint idea looked fine, but the passive overlay was too large relative to the useful taker signal

## What I tested

### 1. Naive MM carry names

Tested one-product late-flatten probes on:

- `PANEL_2X2`
- `PANEL_1X4`
- `GALAXY_SOUNDS_DARK_MATTER`
- `OXYGEN_SHAKE_MORNING_BREATH`
- `OXYGEN_SHAKE_EVENING_BREATH`

Result:

- `PANEL_1X4`, `GALAXY_SOUNDS_DARK_MATTER`, `OXYGEN_SHAKE_MORNING_BREATH`, `OXYGEN_SHAKE_EVENING_BREATH` all failed badly in backtest even though the live logs showed carry pain
- `PANEL_2X2` was the only safe MM candidate: the product had the same live carry pattern, but unlike the others it had very little historical edge to destroy

Then I tested `PANEL_2X2` variants:

- `late_flatten size=5`: slight improvement on day 4, but poor on `2/3/4`
- `naive_mm size=4`: effectively no change
- `naive_mm size=3`: best result
- `late_flatten size=3`: bad

Kept conclusion:

- do **not** use late flatten on `PANEL_2X2`
- simply reduce `maker_size` from `5` to `3`

Why this works:

- the live loss was caused by being too long into the close
- unlike other MM names, `PANEL_2X2` did not need the full size to keep its edge
- smaller size reduces carry risk all day without introducing forced late-session churn

### 2. ROBOT_LAUNDRY coint diagnosis

The live logs suggested:

- short-horizon markouts were not terrible
- final inventory still hurt
- the strategy likely had too much passive inventory riding on top of a decent coint signal

Tested:

- `coint_mm_closeout_A3`: new closeout-aware coint strategy, rejected
- `coint_mm_v1 passive_size=1`: strong improvement
- `coint_mm_v1 passive_size=0`: great on day 4, but worse on `2/3/4`

Kept conclusion:

- keep the existing coint structure
- reduce only `ROBOT_LAUNDRY` passive overlay from `3` to `1`

Why this works:

- it preserves the signal-driven taker entries/exits
- it removes most of the passive inventory accumulation that was polluting the book
- full passive removal over-corrects and throws away too much earlier-day edge

## Final keep: best_v12_A3

Final changes relative to `best_v10`:

- `PANEL_2X2`: `naive_tight_mm maker_size 5 -> 3`
- `ROBOT_LAUNDRY`: `coint_mm_v1 passive_size 3 -> 1`

Backtest results:

| Config | Day 4 | Days 2/3/4 |
|--------|------:|------------:|
| `best_v10` | 365,376 | 848,106 |
| `best_v12_A3` | **368,311** | **851,678** |

Delta vs `best_v10`:

- day 4: **+2,935**
- days `2/3/4`: **+3,572**

Per-product contribution of the kept changes:

- `PANEL_2X2`: `7,142 -> 8,353` on `2/3/4` (`+1,211`)
- `ROBOT_LAUNDRY`: `12,197 -> 14,558` on `2/3/4` (`+2,361`)

## Files kept

- Config: `MEMBER_OVERRIDES["best_v12_A3"]` in `prosperity/config.py`
- Backtest wrapper: `submissions/best_v12_A3.py`
- IMC submission wrapper: `artifacts/submissions/round_5/best_v12_A3_round5_submission.py`

All temporary A3 probe configs and wrappers were removed after consolidation.


# ANALYST 1 (A1) RESEARCH — 2026-04-29

## Overview
Analyzed v10 live log (day 4, total profit 22,791) vs 3-day backtest (848,106). Investigated root causes of live losses and tested 8 config variants. Final config: `best_v12_A1` = `best_v10` + minor size upgrade.

## Live Log Analysis (v10 day 4)

**Total live profit: 22,791** (vs expected ~283k/day from backtest)

### Products losing in live (sorted worst to best):
| Product | Live PnL | Strategy | Backtest 3-day |
|---------|---------|---------|----------------|
| GALAXY_SOUNDS_PLANETARY_RINGS | -7,335 | naive_mm size=3 | +18,604 |
| GALAXY_SOUNDS_DARK_MATTER | -3,834 | naive_mm size=5 | +7,558 |
| OXYGEN_SHAKE_MORNING_BREATH | -3,372 | naive_mm size=5 | +13,710 |
| PANEL_2X2 | -2,806 | naive_mm size=5 | +7,142 |
| PANEL_1X4 | -2,395 | naive_mm size=5 | +29,686 |
| ROBOT_LAUNDRY | -2,368 | coint_mm_v1 | +12,197 |
| OXYGEN_SHAKE_MINT | -2,183 | naive_mm size=3 | -36 |
| SLEEP_POD_NYLON | -899 | trend_v2 | +19,734 |
| SNACKPACK_RASPBERRY | -871 | naive_mm size=5 | +15,397 |

### Root Cause Analysis

**Naive_mm products (top 5 losers + SNACKPACK_RASPBERRY):** Price fell throughout live session. Naive_mm accumulates long inventory as price falls (posting bid at best_bid+1 repeatedly). At session end, pos=+7 with prices down 200-800 ticks → pure MTM loss. Example: GALAXY_SOUNDS_PLANETARY_RINGS pos=+7, price dropped -778 ticks → expected MTM loss ≈ 5,446 ticks.

**ROBOT_LAUNDRY (coint_mm_v1):** The LAUNDRY-VACUUMING spread trended from +889 to +138 throughout the session (spread contracted -751 ticks). The rolling mean (z_win=2000) lagged behind the trend and repeatedly signaled the wrong direction. Resulted in LONG LAUNDRY position (+7 final pos) as price fell -524 ticks.

**SLEEP_POD_NYLON (trend_v2):** Price went UP +168.5 in live but strategy ended with neg PnL. Trend follower likely went in wrong direction early and couldn't recover.

## Strategies Tested

### test1: Aggressive late_flatten on 6 biggest live losers
**Result: 757,756 (-90,350 vs v10) — REJECTED**
Parameters: passive unwind at ts=96000, taker at ts=99000, pos_gate=4.
Failed because late_flatten fundamentally changes fill efficiency (0.580→0.190) even in the pre-late period. The backtest's price oscillations reward the strategy that keeps buying/selling passively at all times.

### test2: trend_v2 for UV_VISOR_RED + GALAXY_SOUNDS_BLACK_HOLES
**Result: 820,542 (-27,564 vs v10) — REJECTED**
UV_VISOR_RED: up +842/+182/+698 in backtest; GALAXY_SOUNDS_BLACK_HOLES: up +1446/+688/+1320. Both consistent UP trends. But trend_v2 uses taker orders and misses oscillation profits that naive_mm captures. For moderate trends (day3 UV_VISOR_RED only +182 net), naive_mm gets much more from oscillations than trend_v2 gets from holding direction.

### test4: Mild late_flatten on 6 live losers (ts=99500 start)
**Result: 760,954 (-87,152 vs v10) — REJECTED**
Even extremely mild late_flatten (only last 5 ticks) caused same magnitude damage as aggressive version (-87k vs -90k). The fill efficiency impact is structural, not timing-related.

### test5: trend_v2 for UV_VISOR_RED only
**Result: 831,332 (-16,774 vs v10) — REJECTED**
UV_VISOR_RED confirmed UP in live (+593) and backtest, but trend_v2 still worse than naive_mm in 3-day backtest.

### test6: Upgrade 7 default naive_mm products from size=3 to size=5
**Result: 848,202 (+96 vs v10) — KEPT**
Products: GALAXY_SOUNDS_BLACK_HOLES, GALAXY_SOUNDS_PLANETARY_RINGS, GALAXY_SOUNDS_SOLAR_WINDS, SLEEP_POD_SUEDE, MICROCHIP_CIRCLE, TRANSLATOR_ASTRO_BLACK, TRANSLATOR_ECLIPSE_CHARCOAL. These were the only products NOT explicitly overridden in best_v10 (using base ROUND_5 size=3). Upgrade to size=5 is safe and consistent with all other similar products.

### test7: ROBOT_LAUNDRY + VACUUMING → naive_mm
**Result: 825,180 (-22,926 vs v10) — REJECTED**
Coint_mm is +26k better than naive_mm in 3-day backtest. The live failure was one bad session; keep coint.

### test8: MICROCHIP_RECT → naive_mm + OXYGEN_SHAKE_EVENING_BREATH → AR1 mean-rev
**Result: 763,856 (-84,250 vs v10) — REJECTED**
OXYGEN_SHAKE_EVENING_BREATH has strong AR1=-0.115 consistently, but the oscillations (~20 ticks) are too small for a 20-tick entry threshold. AR1 strategy got nearly zero fills. MICROCHIP_RECT naive_mm also worse than coint (+4,676 vs +10,696).

## New Alpha Investigated

### Product group conservation laws
Checked GALAXY_SOUNDS (sum CV=1.89%), SLEEP_POD (0.30%), MICROCHIP (1.55%), SNACKPACK (0.11%), UV_VISOR (0.41%), ROBOT (0.21%), OXYGEN (0.20%), PANEL (0.42%), TRANSLATOR (0.29%).
**Finding:** PEBBLES has sum CV=0.01% (essentially perfect conservation). All other groups have CV 10-150× higher. Only PEBBLES conservation is tight enough to generate arb signals. SNACKPACK pairs trading was already tested by A1 iter1 and confirmed 44× worse than naive_mm.

### AR1 systematic scan
Checked all 50 products for AR1 autocorrelation:
- ROBOT_IRONING: AR1=-0.118 (strongest consistent, all 3 days) but already on trend_v2 (+17,460)
- OXYGEN_SHAKE_EVENING_BREATH: AR1=-0.115 (consistent) but oscillations too small for threshold=20
- OXYGEN_SHAKE_CHOCOLATE: AR1=-0.080 (moderate)
- ROBOT_DISHES: AR1=-0.098 average (only -0.290 on day 4, near-zero on days 2/3) — already exploited
Only ROBOT_DISHES has AR1 signal strong enough to profit from. The AR1 on ROBOT_IRONING is tick-level noise while the product has a strong directional daily trend.

### Cross-product correlations
All within-group return correlations are < 0.015. Products are essentially independent even within the same product family. No lead-lag relationships. This confirms the earlier finding from A1 iter1.

## Final Config: best_v12_A1

**Backtest PnL (3-day realistic): 848,202 (+96 vs best_v10)**

Changes vs best_v10:
- 7 products upgraded from default naive_mm size=3 → size=5:
  GALAXY_SOUNDS_BLACK_HOLES, GALAXY_SOUNDS_PLANETARY_RINGS, GALAXY_SOUNDS_SOLAR_WINDS,
  SLEEP_POD_SUEDE, MICROCHIP_CIRCLE, TRANSLATOR_ASTRO_BLACK, TRANSLATOR_ECLIPSE_CHARCOAL

All other strategies identical to best_v10.

### Live robustness note
The live losses in v10 (total -19k from 9 losing products vs backtest expectation) are NOT fixable without accepting large backtest PnL sacrifice. The losses stem from naive_mm carrying inventory in a session that trended down, which is unpredictable. The late_flatten approach that would help in live costs -90k in backtest — not an acceptable tradeoff for competition scoring.

## Files Created

- Config: `MEMBER_OVERRIDES["best_v12_A1"]` in `prosperity/config.py`
- Backtest wrapper: `submissions/best_v12_A1.py` (superseded by best_v12_A1_A3, deleted)
- IMC submission: `artifacts/submissions/round_5/best_v12_A1_round5_submission.py`
- Test configs cleaned up (test1–test8 removed from config.py and submissions/)

---

# ITERATION 6: A1+A3 merge → best_v12_A1_A3 = 851,678 PnL

A3's two genuine changes vs best_v10 (PANEL_2X2 size 5→3, ROBOT_LAUNDRY passive_size 3→1) together give +3,572. A1's change (+96) touches different products — no conflicts.

`best_v12_A1_A3` = `best_v10` + A3's two changes. A1's size upgrades were NOT applied (user decision — kept for a future iteration). Built via inheritance from best_v10 rather than A3's self-contained dump, which had accumulated config bugs (wrong sizes on 9 products, PEBBLES_XL missing M from partners) that caused a −24k regression.

| Config | Backtest PnL |
|--------|-------------|
| best_v10 | 848,106 |
| best_v12_A3 (self-contained dump, buggy) | 823,564 |
| **best_v12_A1_A3** | **851,678** |

Config: `MEMBER_OVERRIDES["best_v12_A1_A3"]` in `prosperity/config.py`
Wrapper: `submissions/best_v12_A1_A3.py`


# ITERATION 7 — A1 SNACKPACK Cross-Product MM Research (2026-04-29)

## Goal
Explore whether the strong pairwise correlations in SNACKPACK products can be exploited to improve on naive_tight_mm.

## Key findings from data analysis

### Pairwise same-tick (lag-0) correlations
| Pair | Return corr | Notes |
|------|------------|-------|
| CHOCOLATE ↔ VANILLA | **-0.916** | Strongest negative pair |
| STRAWBERRY ↔ RASPBERRY | **-0.924** | Even stronger negative |
| PISTACHIO ↔ STRAWBERRY | **+0.913** | Positive, same direction |
| PISTACHIO ↔ RASPBERRY | **-0.831** | Implied by above two |

### No lag-1 predictive power
All lag-1 cross-correlations ≈ 0.001–0.02. CHOCOLATE does NOT lead VANILLA by 1 tick. The relationship is purely simultaneous — no exploitable signal from one product predicting the other's next tick.

### Sum mean-reversion (key finding)
- **AR1(CHOC+VANI sum returns) = -0.34** — consistent across all 3 days
- **AR1(STRAW+RASP sum returns) = -0.27**
- Individual products: AR1 ≈ -0.03 (much weaker)
- Interpretation: when CHOCOLATE goes up without VANILLA going down proportionally (sum deviates), the sum reverts by ~34% on the next tick

### Strategy tested: SnackpackCrossMMV1_A1
**File**: `prosperity/strategies/round_5/tibo/snackpack_cross_mm_A1.py`

Tracks CHOC+VANI sum vs its EWMA (z_window-tick half-life). When z > 0 (sum high = products elevated), shifts VANILLA quotes DOWN by `shift_per_z × z` ticks. When z < 0, shifts UP.

### Critical finding: asymmetric benefit
- **VANILLA only** with partner=CHOCOLATE: **+16,742 improvement** (consistent across all z_window)
- CHOCOLATE with partner=VANILLA: **-20,006** (hurts badly)
- STRAWBERRY with partner=RASPBERRY: **-10,172** (hurts)
- RASPBERRY with partner=STRAWBERRY: **-2,677** (hurts)

**Why VANILLA benefits but others don't**:
- VANILLA has a mixed-to-upward daily trend. The signal (when CHOC spikes, shift VANI quotes down) lets us buy VANI at temporarily depressed prices during CHOC spikes, then VANI recovers. Net: better average entry price.
- CHOCOLATE trends DOWN. Shifting CHOC quotes down when sum is high reduces fill efficiency (bids below market) on a product where every fill should earn the spread. Net: missed fills dominate.
- STRAWBERRY trends UP consistently. Shifting quotes DOWN misses uptrend fills.

### Parameter sweep for VANILLA (z_window, shift_per_z=1.0)
| z_window | VANI improvement | Total improvement | VANI std/day |
|----------|-----------------|-------------------|--------------|
| 100 | +4,308 | +4,307 | high |
| 500 | +11,506 | +11,505 | moderate |
| 1000 | +14,964 | +14,963 | 2,852 |
| 1500 | +17,171 | +17,170 | 1,831 |
| 1600 | +17,789 | +17,789 | 1,660 |
| 1700 | +17,539 | +17,539 | 1,675 |
| **1800** | **+17,360** | **+17,360** | **1,594** |
| **1900** | **+16,742** | **+16,742** | **843** ← most stable |
| 2000 | +16,225 | +16,225 | 902 |
| 2500 | +13,592 | +13,592 | 239 |
| 3000 | +13,305 | +13,305 | 814 |

**Chosen: z_window=1900** — plateau stability over pure total maximization. Per-day VANI improvements: +4,403/+6,012/+6,328 (std=843, all 3 days positive, day3≈day4 which suggests no overfitting to day 4 trend).

## Final config: best_v12_snackpack_A1

| Config | Backtest PnL |
|--------|-------------|
| best_v12_A1_A3 (baseline) | 851,678 |
| **best_v12_snackpack_A1** | **868,420** |

Changes vs best_v12_A1_A3:
- SNACKPACK_VANILLA: `snackpack_cross_mm_v1_A1` (partner=CHOCOLATE, z_window=1900, shift_per_z=1.0)
- All other products: identical to best_v12_A1_A3

Config: `MEMBER_OVERRIDES["best_v12_snackpack_A1"]` in `prosperity/config.py` — self-contained, no inheritance.
Strategy file: `prosperity/strategies/round_5/tibo/snackpack_cross_mm_A1.py`
Submission wrapper: `submissions/best_v12_snackpack_A1.py`

## What didn't work
- CHOC/STRAW/RASP/PISTA with cross_mm: all hurt (see above)
- STRAW+RASP sum z-score on both products: -12,850 vs baseline
- Momentum cross (VANI vs STRAW cumulative return crossover): 85% "momentum" on days 2/3 but only 59% on day 4 — not exploitable (it's just STRAW's daily trend, not a signal)
- PISTACHIO-STRAWBERRY momentum: tick correlation +0.91 but they diverge directionally (STRAW up, PISTA down) — no arb, just a structural level divergence


# ANALYST 2 (A2) RESEARCH — 2026-04-29: Cross-Group Trend Strategy

## Overview

Explored cross-group correlations between SLEEP_POD (SP), GALAXY_SOUNDS (GS), and ROBOT (RB) groups, built a `cross_group_trend_A2` strategy, and achieved **+35,634 PnL improvement** over best_v12_A1_A3.

Final config: **best_v13_A2 = 887,312 PnL** (+35,634 vs baseline 851,678)

## Cross-Group Correlation Analysis

### Confirmed correlations (overall 3-day level data)

| Pair | Correlation |
|------|------------|
| SP avg vs GS avg | +86% |
| SP avg vs RB avg | −75% |
| GS avg vs RB avg | −58% |

### Critical finding: correlations are mostly between-day, not within-day

| Day | SP vs GS | SP vs RB | GS vs RB |
|-----|----------|----------|----------|
| 2 | 0.84 | +0.15 (!) | +0.28 |
| 3 | 0.70 | −0.56 | −0.68 |
| 4 | 0.21 | −0.20 | −0.40 |

Tick-level return correlations are essentially zero (~0.01-0.04) — no predictive signal tick-by-tick. The high overall correlations are driven by between-day regime differences (some days all products up, others all down).

### PCA results: unstable within groups

PCA on each group per day shows unstable structure:
- SLEEP_POD: PC1 explains 58-67% but loadings flip signs between days (NYLON goes UP on Day4 while group average goes DOWN)
- GALAXY_SOUNDS: Very unstable PC structure, no consistent dominant product
- ROBOT: DISHES always separate; MOPPING/IRONING/LAUNDRY/VACUUMING form a sub-group

**Conclusion**: No stable PCA structure to exploit directly. Cannot use individual product PCA loadings as cross-group signals reliably.

### Actionable signal: group AVERAGE EMA vs session start

Despite individual product instability, the group AVERAGE provides a more robust daily direction indicator:

| Day | SP avg move | GS avg move | RB avg move | SP-GS aligned? |
|-----|-------------|-------------|-------------|----------------|
| 2 | +654 | +808 | −86 | YES |
| 3 | +893 | +358 | −329 | YES |
| 4 | −200 | −277 | +59 | YES (all 3 days!) |

SP group average perfectly predicts GS direction across all 3 days. Best targets: DARK_MATTER and BLACK_HOLES.

## Strategy Design: cross_group_trend_A2

File: `prosperity/strategies/round_5/tibo/cross_group_trend_A2.py`

**Signal**: EMA of SP group average deviation from session start:
- `sp_ema = EMA(mean(SP_product_mids) - session_start_SP_avg, hl=100)`

**Optional second signal (inverted)**: EMA of RB group average:
- `rb_ema = EMA(mean(RB_product_mids) - session_start_RB_avg, hl=100)`
- Used as CONFIRMATION (RB down when SP up): combined signal = SP > thr AND RB < -rb_thr

**Signal regimes**:
- BULL: sp_ema > signal_threshold (AND rb_ema < -signal2_threshold if used)
- BEAR: sp_ema < -signal_threshold (AND rb_ema > signal2_threshold)
- NEUTRAL: neither

**Trading logic**:
- BULL: post passive bid only + taker buy on entry (position==0)
- BEAR: post passive ask only + taker sell on entry (position==0)
- NEUTRAL: post both bids and asks (naive_mm behavior)
- Exit: when EMA crosses back through exit threshold

## Backtest Results

### Parameter search (simulation)

| Product | Config | Simulated | Naive_mm baseline |
|---------|--------|-----------|------------------|
| DARK_MATTER | sp_thr=300 | +18,615 | +7,558 |
| BLACK_HOLES | sp=80 + rb=30 | +34,065 | +15,419 |
| DARK_MATTER | rb_thr=50 | +19,370 | +7,558 |
| BLACK_HOLES | sp_thr=150 (sp only) | +30,045 | +15,419 |

### Actual backtest results (realistic fill mode, days 2/3/4)

| Config | 3-day PnL | Delta vs baseline |
|--------|-----------|-------------------|
| best_v12_A1_A3 (baseline) | 851,678 | — |
| test_cgA2_dark_matter | 861,024 | +9,346 |
| test_cgA2_black_holes | 877,966 | +26,288 |
| test_cgA2_both (→ best_v13_A2) | **887,312** | **+35,634** |
| test_cgA2_bh_sponly (sp=150 only) | 868,862 | +17,184 |

### Per-product results for best_v13_A2

| Product | Strategy | 3-day PnL | vs naive_mm |
|---------|----------|-----------|-------------|
| GALAXY_SOUNDS_BLACK_HOLES | cross_group_trend_A2 (sp=80, rb=30) | +41,708 | +26,288 |
| GALAXY_SOUNDS_DARK_MATTER | cross_group_trend_A2 (sp=300 only) | +16,904 | +9,346 |

### GS products NOT changed (cross-group signal doesn't help):

- **GALAXY_SOUNDS_PLANETARY_RINGS**: cross-group strategy WORSE than naive_mm in simulation (threshold instability on Day 3 which only moves +158). Keep naive_mm.
- **GALAXY_SOUNDS_SOLAR_WINDS**: Day 2 misalignment (SP up +654, SOLAR_WINDS DOWN −416). Too risky.
- **GALAXY_SOUNDS_SOLAR_FLAMES**: No consistent GS-SP alignment (Day 3 inversion: SP up +893, SOLAR_FLAMES DOWN −694). Skip.

## Why cross-group beats naive_mm for BLACK_HOLES and DARK_MATTER

Naive_mm fails on "downtrend days" (Day 4: SP −200, GS −277): it accumulates long inventory at declining prices, taking MTM losses. In live v10, DARK_MATTER: −3,834 and BLACK_HOLES: −5,223.

Cross-group strategy detects the regime using the SP group average EMA crossing −80 to −300 (depending on product) and goes SHORT instead. On Day 4, this flips a loss into a gain.

The combined SP+RB signal (requiring BOTH SP > 80 AND RB < −30) is better than SP alone for BLACK_HOLES because it filters false positives where SP is momentarily positive but overall direction is uncertain.

## Key learnings (A2)

1. **Cross-day level correlations ≠ intra-day predictive signal**: The 86% SP-GS correlation is mostly between-day. Within days, tick-level correlations are <0.04. Use the cross-group signal as a daily regime indicator (EMA vs session start), not a tick-level signal.

2. **Group average is more robust than individual product**: PCA structure is unstable (loadings flip each day). Group average EMA smooths out the within-group divergences (e.g., NYLON diverging from other SPs on Day 2).

3. **Combined signal (SP + inverted RB) > SP alone for BLACK_HOLES**: +26,288 (combined) vs +17,184 (SP only). The RB signal adds confirmation that reduces false entries when SP is weakly positive but GS is not following.

4. **Cross-group signal only helps products that CHANGE DIRECTION**: BLACK_HOLES always goes UP but the cross-group signal handles the edge case where SP goes DOWN (Day 4: SP −200 → signal is neutral/bearish, but BLACK_HOLES goes UP +1,320). The threshold=80 means the signal doesn't fire strongly negative on Day 4 (SP only down −200, EMA lags to ~−100), so the strategy remains neutral/passive for BLACK_HOLES on Day 4 rather than going short.

## Files (A2 work)

- Strategy: `prosperity/strategies/round_5/tibo/cross_group_trend_A2.py`
- Config: `MEMBER_OVERRIDES["best_v13_A2"]` in `prosperity/config.py`
- Helpers: `_v13_cg_A2()`, `_sc_mm()`, `_sc_trend()` in `prosperity/config.py`
- Submission: `artifacts/submissions/round_5/best_v13_A2_round5_submission.py`
- Backtest wrapper: `submissions/best_v13_A2.py`
- All test configs (test_cgA2_*) cleaned up



# ITERATION 7: ANALYST 2 (A2): merged work from theo and version best_v13_A2

## Theo v12 Strategy Analysis: Live vs Backtest
Core mechanism (how it actually works)
Theo's strategy is pure directional betting, not market making:

Every product has a hardcoded target_position: ±10 derived from training days 2/3/4
The strategy takes its maximum position in 1-6 trades at day start and holds until end of day
inv = 0.935 average — virtually all time at full position, zero risk management
Variants: R5TrendFollower (immediate full entry), R5TrendFollowV2 (EMA gate before entry), R5MomentumFollower (EMA crossover gate before entry)
The numbers explained
Metric	Value
Backtest (3 days)	765,013
Backtest per day avg	255,004
Live PnL (1 day)	52,899
Ratio	14.5x (yours: 30x)
Why his ratio is 14x vs your 30x:

Two failure modes completely explain the gap:

1. Reversals — 17 products went positive in backtest but NEGATIVE live
The live day trended opposite to training for these products. They lost -30,512 live while earning +168,620 in backtest:


SLEEP_POD_LAMB_WOOL        BT= +8,018   Live= -5,954  ← went long, price FELL
GALAXY_SOUNDS_DARK_MATTER  BT= +3,155   Live= -4,568  ← went long, price FELL
UV_VISOR_ORANGE            BT= +6,605   Live= -4,538  ← went short, price ROSE
TRANSLATOR_ASTRO_BLACK     BT=+10,453   Live= -3,560  ← went short, price ROSE
MICROCHIP_TRIANGLE         BT=+20,664   Live= -2,807  ← went short, price ROSE
ROBOT_VACUUMING            BT=+18,068   Live=   -791
ROBOT_DISHES               BT=+21,064   Live=   -177
UV_VISOR_MAGENTA           BT=+17,725   Live=    -67
... (17 total)              Total -30,512 live
2. No-entries — 6 products had 0 live trades, missing 117,270 backtest PnL
The EMA/momentum gate was tuned to specific training-day patterns and never fired on the live day:


MICROCHIP_SQUARE       BT= 44,753  Live= 0  (TFv2: EMA threshold never crossed)
ROBOT_IRONING          BT= 28,187  Live= 0  (TFv2 gate blocked)
PANEL_4X4              BT= 13,271  Live= 0
TRANSLATOR_GRAPHITE_MIST BT=12,749 Live= 0
MICROCHIP_CIRCLE       BT= 11,655  Live= 0
UV_VISOR_YELLOW        BT=  6,655  Live= 0
Overfitting signals — product by product
Critical overfitting: hardcoded directions from 3 training days

The direction (+10 or -10) is fixed and derived by looking at which direction was profitable on days 2/3/4. But many products are NOT consistently trending the same direction — they just happened to trend right on those 3 specific days:

Product	Day2	Day3	Day4	Consistency	Live outcome
PANEL_1X4	-10,690	+23,669	-5,016	1/3 days positive	Went SHORT, +3,943 live (lucky)
OXYGEN_SHAKE_MORNING_BREATH	-10,055	+14,600	-245	1/3 days positive	Went SHORT, +2,124 live (lucky)
PANEL_1X2	+15,625	-4,305	-8,520	1/3 positive	Went SHORT, +3,514 live
GALAXY_SOUNDS_SOLAR_WINDS	-4,225	+11,690	-5,155	1/3 positive	Went LONG, -463 live
PEBBLES_XL	+36,685	-15,615	+40,060	2/3 with huge Day3 loss	+9,561 live (lucky, right day)
HIGH_VAR products with fragile backtest PnL — these show huge day-to-day swings, meaning the total backtest PnL is dominated by 1 lucky day, not a robust edge.

TFv2 thresholds overfitted to training timing — MICROCHIP_SQUARE made 31,546 on day 3 (a big trend day) and the entry_threshold=125, ema_half_life=150 was set precisely to enter on that type of day. On a different live day, the EMA never hit the threshold → 0 PnL.

Momentum parameters tuned to 3 days only — fast_alpha=0.03, slow_alpha=0.003, threshold=3.0 was selected via grid search on the training set. Many products (ROBOT_DISHES, ROBOT_MOPPING, UV_VISOR_MAGENTA) reversed on live despite all 3 training days being positive in backtest.

What genuinely works in Theo's approach
Only 2 products were consistently positive across all 3 backtest days AND performed well live:

UV_VISOR_RED: BT +17,015 / Live +5,856 — a real edge
PEBBLES_S: BT +19,365 / Live +5,534 — a real edge
Products that overperformed live (live > BT/3) are mostly concentrated SHORT positions that happened to capture a large down-move on that specific live day — not systematic alpha, just day-regime luck.

What IS sound from Theo's framework:

The EMA-crossover momentum gate is better than raw buy-and-hold (prevents dumb entry on flat days)
Using IMC logs as holdout validation to filter parameter choices is methodologically correct
Category-level momentum is a real signal direction to explore (but needs adaptive direction, not hardcoded)
Recommendations for what to adopt from Theo
From Theo, take:

UV_VISOR_RED and PEBBLES_S have robust directional edges worth keeping — consider adding them to our strategy as fixed-direction entries
The concept of using an EMA vs session-start gate before entering is sound — we already use this in trend_follow_v2
Do NOT adopt:

Any hardcoded direction for products with 1/3 or 2/3 day consistency — they will reverse on live
The TFv2/Momentum thresholds as-is — they're overfitted to training day timing
Products with HIGH_VAR flag: PEBBLES_XL, PEBBLES_M, PEBBLES_L, PANEL_1X4, OXYGEN_SHAKE_CHOCOLATE, OXYGEN_SHAKE_MORNING_BREATH — backtest PnL is concentrated in 1 lucky day
The fundamental asymmetry: Our best_v13_A2 makes thousands of trades (24,492 over 3 days) and earns via market-making spreads + verified signals. Theo makes ~200 trades total. Market-making PnL is much more robust to unseen days. His ratio of 14x vs our 30x exactly reflects this — one bad direction day costs him nearly everything, while our MM approach is directional-neutral by default.

sub-iteration:
- integration of theo's good parts
- Key fix that made this work: added direction param to trend_follow_v2.py (+1 = long-only, -1 = short-only, 0 = bidirectional default). Without it, MICROCHIP products were entering LONG before the main downtrend, causing massive losses. new: best_v14_A2_round5_submission.py.
- issues found... Fix applied: reference_update_interval=800 — while flat, after 800 ticks reset the reference to the current EMA. This means the signal measures deviation from "where price was recently" rather than always from session open. When the counter-move happens first, the reference chases it; when the actual trend starts, the signal fires cleanly from the updated base. In backtest, the strategy enters position before tick 800, so the reference never updates — zero disruption to backtest behavior. Root cause summary: The EMA vs session_start signal fails when price counter-moves before trending. Two specific live failures:
- new set of issue found: Core diagnosis
The three regressions share the same root cause: the Theo-informed directional features (SHORT-only direction + faster EMA + trail_stop) create a false-entry → trail-stop-loss → miss-real-trend cycle on days with a counter-move before the main trend. The products where this fails (OVAL, PEBBLES_XS) happen to have an early counter-move in the live session that the faster EMA catches but shouldn't. MICROCHIP_TRIANGLE is a different failure: the live direction was opposite to training, so direction=-1 misses the MM income entirely.

Naive_mm is more robust than directional TFv2 for MICROCHIP products because it captures spread regardless of direction. The backtest gain from TFv2 was overfitted to 3 training days of consistent DOWN trends.

Proposed fixes
MICROCHIP_OVAL → revert to naive_mm (size=5 like v13 baseline): always profitable regardless of direction, avoids the early-dip entry problem entirely.

MICROCHIP_TRIANGLE → revert to naive_mm (size=3 like v13 baseline): same reasoning; lost 3,036 live by going directional on an UP day.

PEBBLES_XS → revert to v14 params (direction=-1, ema_hl=150, thr=100, no trail, no ref_update): slow EMA with high threshold never fires on brief dips → 0 live (safe), 32,160 backtest (better than v13 baseline 25,450).

OXYGEN_SHAKE_GARLIC → keep v17 params (ref_update=800, dir=+1, ema_hl=50, thr=80). This is a genuine fix that now works live.

ROBOT_IRONING → keep v17 params (thr=50). Improvement confirmed live.

Expected backtest: ~913k (lower than v17's 933k due to MICROCHIP reverting, but better than v13 baseline 887k). Expected live: ~31-32k (better than both v13's 28k and v17's 26k by fixing the three regressions while keeping the two improvements).

final integrated version: best_v18_A2, it works well in live and still enhanced the backtest pnl

# ITERATION 8: A1 + A2 merge → best_v19 = 929,866 PnL

No conflicts: A1 touches SNACKPACK_VANILLA only, A2 touches GALAXY_SOUNDS/MICROCHIP/PEBBLES_XS/OXYGEN_SHAKE_GARLIC/ROBOT_IRONING. Improvements are fully additive.

| Config | PnL | Delta |
|--------|-----|-------|
| best_v12_A1_A3 (baseline) | 851,678 | — |
| best_v18_A2 (A2 alone) | ~913,000 | +61,322 |
| best_v12_snackpack_A1 (A1 alone) | 868,420 | +16,742 |
| **best_v19 (merged)** | **929,866** | **+78,188** |

Config: `MEMBER_OVERRIDES["best_v19"]` — self-contained, no inheritance.
Wrapper: `submissions/best_v19.py`


