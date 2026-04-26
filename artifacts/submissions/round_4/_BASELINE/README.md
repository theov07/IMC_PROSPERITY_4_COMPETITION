# Round 4 Submissions — Final candidates

## Pareto frontier (R4 3-day backtest, realistic fill, HYDROGEL DISABLED)

| Tier | File | PnL 3d | DD | Ratio | CV% | Pick if... |
|---|---|---:|---:|---:|---:|---|
| **BEST RATIO** ★ | `R4_v57_best_ratio__pnl152k_dd62k_ratio246.py` | **151,596** | **61,560** | **2.46** | 47.8% | Risk-adjusted choice |
| **BALANCED** | `R4_v58_balanced__pnl153k_dd64k_ratio239.py` | 153,132 | 64,004 | 2.39 | 49.3% | + VEV_5300 (+1.5k) |
| **MAX PnL** | `R4_BASELINE__r4_velvet_options_only__pnl158k_dd73k_ratio217.py` | **157,712** | 72,582 | 2.17 | 52.9% | + Tibo MM 5200/5400 (+4.6k) |
| MINIMAL | `R4_v52_minimal__pnl140k_dd61k_ratio230.py` | 140,488 | 61,195 | 2.30 | 52.8% | No toxic/unwind (lower) |

## Per-product 3-day PnL

| Product | v52 minimal | **v57 best ratio** ★ | v58 balanced | baseline (v62) |
|---|---:|---:|---:|---:|
| **VELVETFRUIT_EXTRACT** | 71,940 | **83,048** | 83,048 | 83,048 |
| VEV_4000 | 22,272 | 22,272 | 22,272 | 22,272 |
| VEV_4500 | 14,592 | 14,592 | 14,592 | 14,592 |
| VEV_5000 | 8,186 | 8,186 | 8,186 | 8,186 |
| VEV_5100 | 17,963 | 17,963 | 17,963 | 17,963 |
| VEV_5200 | 5,536 | 5,536 | 5,536 | **9,831** (Tibo MM) |
| VEV_5300 | 0 | 0 | **1,535** | 1,535 |
| VEV_5400 | 0 | 0 | 0 | 286 |

## Daily breakdown

| Variant | D1 | D2 | D3 (R4-only data) |
|---|---:|---:|---:|
| v52_minimal | +59,070 | +63,029 | +18,389 |
| **v57_best_ratio** ★ | +65,120 | +63,835 | +22,641 |
| v58_balanced | +65,924 | +65,217 | +21,990 |
| baseline | +68,920 | +68,340 | +20,452 |

## Key learnings R3 → R4

| Idea | PnL gain (3d) | Notes |
|---|---:|---|
| Toxic flow + passive unwind on VELVET | **+11,108** | v52 → v57 (the big win) |
| Tibo's 2-sided MM on VEV_5200 | +4,295 | v57 → baseline (5200 only) |
| Enable VEV_5300 (gamma+IV gate) | +1,535 | v57 → v58 |
| Tibo's 2-sided MM on VEV_5400 | +286 | marginal, prevent_crossing helps |
| Per-strike z thresholds (v55) | NEGATIVE | VEV_5400 z=1.0 bleeds -2.9k on D3 first 10%, killed in v55 |

## Data identity (R3 vs R4)

- **R3 day 1 = R4 day 1** (bit-for-bit, mid prices 1000/1000 match)
- **R3 day 2 = R4 day 2** (bit-for-bit)
- **R4 day 3 = NEW** (only new data added for R4)

## HYDROGEL is disabled

R3 best HYDRO config (`v7b_guarded_loose`) bleeds **-104k on R4 D3** (3-day total -23,121 just from D3 collapse). Anchor-based MM at 10000 over-trades and gets adversely picked on D3. Re-tune needed for R4 — until then, HYDROGEL stays off.

## Manual challenge (separate)

AETHER_CRYSTAL exotics: chooser, binary put, knock-out put. Trade independently from algo. Geometric Brownian motion underlying, 251% annualized vol, 4-step grid per day.

## Recommendation

**Default upload**: `R4_v57_best_ratio` (151k PnL, ratio 2.46) — best risk-adjusted, lowest CV.

**Aggressive**: `R4_BASELINE__r4_velvet_options_only` (157k PnL, ratio 2.17) — max PnL but +11k DD.

Both well under 100KB ✓.

## Next iteration ideas

1. **Re-tune HYDROGEL for R4** — find why D3 bleeds, possibly pure passive small-size (live-confirmed +5.78 markout in tiny passive mode)
2. **Counterparty info ("Mark" tracker)** — R4 exposes buyer/seller names, opportunity for participant classification
3. **Faster warm-up** — gamma_scalp + zscore_window=500 = 50 ticks dead time; reduce to 100-200 for faster D3 capture
