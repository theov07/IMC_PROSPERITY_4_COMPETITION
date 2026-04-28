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