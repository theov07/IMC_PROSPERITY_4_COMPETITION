# A2 Research Notes — Round 5 Momentum/Mean-Reversion Strategy Improvements

**Analyst**: A2  
**Base config**: `best_v2810_v2640_plus_v19_laundry_A3` (1,038,574 BT)  
**Result**: `best_merged_v1_A2` (1,043,420 BT, **+4,846**)

---

## Products Investigated

### 1. ROBOT_DISHES — AR1 Mean Reversion

**Strategy in use**: `ar1_mean_rev_v1` — tick-to-tick mean reversion. On big UP tick → short (expect reversion). On big DOWN tick → long (expect reversion). Entry threshold = 20 ticks.

**Problem identified**: On down-trending days (2 and 3 in BT), the strategy repeatedly buys on each down-tick expecting reversion, accumulates max long position (10 units), but reversion never comes → marked-to-market losses. End position = 10 (long) on both days.

Days 2/3/4 baseline: -2,688 / -16,332 / +158,794 = 139,774 total.

**Approach 1 (failed): Trend-direction filter**  
Created `ar1_mean_rev_v2_A2.py` with slow trend EMA. When market trending UP, suppress new SHORT entries. When trending DOWN, suppress new LONG entries. Allow closing existing positions unconditionally.

Result: Made ALL days worse. Total 129,385–131,142 vs baseline 139,774.

Root cause of failure: The AR1 short-term reversions DO happen even on trending days — the filter was suppressing profitable round-trip mean-reversion trades, not just the final bag-building. The AR1 is designed to exploit brief counter-moves; those happen even on trending days.

**Approach 2 (winner): exit_ticks=50**  
Force-close any held position after 50 ticks via taker order. This prevents accumulating a large directional bag when a trend persists longer than the reversal horizon.

Results with exit_ticks=50: -6,193 / -16,058 / +165,633 = **143,382** (+3,608 vs baseline).
- Day 3: slightly better (-16,058 vs -16,332)
- Day 4: +6,839 boost (more frequent position recycling = more profitable round-trips on the up day)
- Day 2: slightly worse (-6,193 vs -2,688)

**Chosen**: `ar1_mean_rev_v2_A2` with `exit_ticks=50, trend_ema_hl=0, trend_threshold=0`.

---

### 2. PEBBLES_XS — Trend Following (Short-Only)

**Strategy in use**: `trend_follow_v2`, direction=-1, ema_half_life=150, threshold=100, exit_threshold=30.

**Problem identified**: In live (1000-tick session), the strategy entered short early but price went UP for 600 ticks before eventually coming down. With `reference_update_interval=0` (default), the session-start reference never resets — the EMA-vs-start signal was always calculated relative to the very first tick price.

**Feature tested**: `reference_update_interval=N` — after N consecutive flat ticks (position=0 and EMA drift within exit_threshold), reset the session reference to current EMA. This allows catching a trend that starts mid-session after an initial counter-move.

Results:
| Config | Day 2 | Day 3 | Day 4 | Total |
|---|---|---|---|---|
| baseline (ref=0) | 17,425 | 9,425 | 5,310 | **32,160** |
| ref_interval=500 | 18,105 | 9,845 | 6,400 | **34,350** |
| ref_interval=800 | 19,325 | 10,625 | 6,490 | **36,440** ✓ |

All variants fully consistent (positive all 3 days). ref_interval=800 best overall (+4,280).

**Chosen**: `trend_follow_v2` with `reference_update_interval=800`.

**Note on live relevance**: With position_limit=10 and only 1 trade per day in BT, the ref_interval rarely triggers in backtest (position is held all day). The improvement comes from better initial entry timing due to a slightly different EMA evolution path. In live where the session is shorter (1000 ticks), the ref_interval becomes more valuable.

---

### 3. MICROCHIP_SQUARE — Trend Following (Bidirectional)

**Strategy in use**: `trend_follow_v2`, direction=0 (bidirectional), ema_half_life=100, threshold=250, exit_threshold=100.

**Problem identified**: In live, EMA(100) signal only crossed -250 threshold at ticks 987-999 (last 13 ticks of a 1000-tick live session). The product has massive intraday oscillations that prevented the slow EMA from building signal. Strategy barely fired in live.

**Feature tested**: Faster EMA (hl=30, hl=50) with adjusted thresholds.

Results:
| Config | Day 2 | Day 3 | Day 4 | Total |
|---|---|---|---|---|
| baseline (hl=100) | 17,897 | 28,705 | 8,169 | **54,771** |
| hl=50, thr=220 | 20,167 | 31,650 | 797 | **52,614** |
| hl=30, thr=200 | 21,197 | 30,859 | 4,642 | **56,698** ✓ |

hl=30 wins days 2 and 3 by a significant margin (+3.3k and +2.2k) while day 4 regresses (-3.5k). Net +1.9k.

Trade-off: hl=30 risks firing too many false signals on high-volatility days (day 4 = -3.5k vs baseline). But live benefit is substantial (fires early vs too-late baseline).

**Chosen**: `trend_follow_v2` with `ema_half_life=30, threshold=200, exit_threshold=150`.

---

## Final Merged Config

`best_merged_v1_A2` = baseline + the 3 improvements above.

| Day | Merged | Baseline | Δ |
|---|---|---|---|
| Day 2 | 292,001 | 290,997 | +1,004 |
| Day 3 | 323,967 | 319,843 | +4,124 |
| Day 4 | 427,452 | 427,734 | -282 |
| **Total** | **1,043,420** | **1,038,574** | **+4,846** |

Clean improvement: days 2 and 3 meaningfully better, day 4 essentially unchanged.

---

## Key Lessons

1. **AR1 trend filter is counterproductive**: Mean-reversion strategies exploit brief counter-moves that exist EVEN on trending days. Suppressing entries based on trend direction removes profitable trades.

2. **exit_ticks is the right lever for AR1**: Force-closing stale positions prevents catastrophic bag accumulation while allowing fresh re-entry. The recycling effect actually IMPROVES day 4 performance by enabling more profitable round-trips.

3. **reference_update_interval improves TF v2 entry timing**: Even when it rarely triggers explicitly, the different EMA evolution path leads to better entry prices across all days.

4. **Faster EMA for products with high intraday oscillation**: Products like MICROCHIP_SQUARE need a faster EMA to build signal in the short live session. The BT day 4 regression is an acceptable trade-off given the live benefit.

5. **Strategy improvements are additive but not perfectly cumulative**: Expected +9.8k individual sum, actual +4.8k merged — some interactions between products or non-linear effects. Always validate the full merged config, not just per-product deltas.

---

## Files Created

- `prosperity/strategies/round_5/tibo/ar1_mean_rev_v2_A2.py` — AR1 V2 with trend filter + exit_ticks
- `artifacts/submissions/round_5/best_merged_v1_A2_round5_submission.py` — final submission
- `submissions/best_merged_v1_A2.py` — local BT wrapper

At the end i created best_merged_v2_A2 which only includes my recent progress on MICROCHIP_SQUARE and not the other because that's better in live. 

so artifacts/submissions/round_5/best_merged_v2_A2_round5_submission.py = best_v2810_v2640_plus_v19_laundry_A3_round5_submission + recent findings from best_merged_v1_A2, but only on MICROCHIP_SQUARE.