# Round 4 Submissions — Final candidates

## 🏆 BEST CHAMPION v5 (2026-04-27 wave 3 final final)

**`R4_CHAMPION_v5__obi_fade_M49w08_M14_M01__pnl175k_dd67k_ratio259.py`** — **174,751 / 67,465 / 2.59**
**+17,039 PnL vs previous baseline** (was 157,712, +10.8% absolute).

### Optimal weights (after weight scan)
- Mark 49 = **-0.8** (was -1.0; lower weight = better)
- Mark 14 = -0.5
- Mark 01 = -0.2
- OBI size tilt: 1.5x boost / 0.7x reduce, threshold 0.005, L3
- threshold 1.0, max_offset 2.0, scale 0.15, window 100 ticks

### Per-day breakdown
- D1: TBD (similar to v4)
- D2: TBD (HUGE win on uptrend)
- D3: TBD (small loss vs baseline)

---

## 🏆 PREVIOUS CHAMPION v4

**`R4_CHAMPION_v4__combo_obi_fade_49_14_01__pnl173k_dd68k_ratio256.py`** — **172,771 / 67,502 / 2.56**
**+15,059 PnL vs previous baseline** (was 157,712, +9.6% absolute).

### Mechanism (combines 4 signals)

1. **Mark 49 fade** (weight -1.0): when Mark 49 net-sells over 100 ticks, bias UP. Mark 49
   is a directional seller that loses long-term (-15k 3d PnL). His sells precede rebounds.

2. **Mark 14 fade** (weight -0.5): Mark 14 is a balanced MM but his short-term net flow has
   ρ=-0.15 with future returns. Half-weight to avoid noise.

3. **Mark 01 fade** (weight -0.20): NEW — discovered Mark 01's BUY volume spikes on D3
   last 10% before the crash (+35 vs +6 D2). Small weight catches this without dominating.

4. **OBI size tilt** (1.5x boost / 0.7x reduce, threshold 0.005, L3): when bid_volume vs
   ask_volume imbalance is extreme, multiply our orders accordingly. Avoids spread cost
   from price tilt.

### Per-day breakdown
- D1: +71,354 (+2,434 vs baseline)
- D2: +85,064 (**+16,724** vs baseline — HUGE win on uptrend day)
- D3: +16,353 (-4,099 vs baseline — small loss on clear downtrend)

### Progressive wins
| Stage | PnL gain | Mechanism added |
|---|---:|---|
| baseline | 0 | — |
| fade_mark49 | +5,746 | Single Mark fade |
| fade_49_14 | +10,148 | + Mark 14 fade -0.5 |
| combo_obi_fade | +10,621 | + OBI size tilt |
| combo_obi_fade_w01 | +12,297 | + Mark 01 fade -0.3 |
| **★ combo_obi_fade_w01_w02** | **+15,059** | **Mark 01 weight tuned to -0.2** |

## Pareto frontier (R4 3-day backtest, realistic fill, HYDROGEL DISABLED)

| Tier | File | PnL 3d | DD | Ratio | Notes |
|---|---|---:|---:|---:|---|
| **🏆 BEST** | `R4_CHAMPION_v4__combo_obi_fade_49_14_01__pnl173k_dd68k_ratio256.py` | **172,771** | **67,502** | **2.56** | **DEFAULT UPLOAD** |
| v3 | `R4_CHAMPION_v3__combo_obi_fade_w01__pnl170k_dd67k_ratio253.py` | 170,009 | 67,301 | 2.53 | Mark 01 -0.3 |
| v2 | `R4_CHAMPION_v2__combo_obi_fade__pnl168k_dd70k_ratio240.py` | 168,333 | 70,090 | 2.40 | OBI + fade_49_14 |
| v1 | `R4_NEW_CHAMPION__fade_49_14__pnl168k_dd70k_ratio239.py` | 167,860 | 70,277 | 2.39 | fade_49_14 only |
| OLD baseline | `R4_BASELINE__r4_velvet_options_only__pnl158k_dd73k_ratio217.py` | 157,712 | 72,582 | 2.17 | No trader signal |
| OLD ratio | `R4_v57_best_ratio__pnl152k_dd62k_ratio246.py` | 151,596 | 61,560 | 2.46 | Lower DD pre-trader |
| OLD balanced | `R4_v58_balanced__pnl153k_dd64k_ratio239.py` | 153,132 | 64,004 | 2.39 | Backup |
| MINIMAL | `R4_v52_minimal__pnl140k_dd61k_ratio230.py` | 140,488 | 61,195 | 2.30 | No toxic/unwind |

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
