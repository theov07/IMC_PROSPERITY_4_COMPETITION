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