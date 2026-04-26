# Round 4 Baseline — `r4_velvet_options_only` ★

**Upload-ready file**: `R4_BASELINE__r4_velvet_options_only__pnl158k_dd73k_ratio217.py` (92,529 bytes < 100KB ✓)

## Backtest performance (Round 4, 3-day, realistic fill)

| Metric | Value |
|---|---:|
| **PnL** | **157,712** |
| **DD** | **72,582** |
| **Ratio** | **2.173** |
| Day 1 | +68,920 |
| Day 2 | +68,340 |
| Day 3 | +20,452 |

## Why HYDROGEL is DISABLED in R4

Initially tested `r4_combined_best` (= our R3 best with HYDROGEL on). Result:

| Strategy | PnL | DD | Ratio | D1 | D2 | D3 |
|---|---:|---:|---:|---:|---:|---:|
| with HYDRO | 53,251 | 83,678 | 0.636 | 41,745 | 34,627 | **-23,121** ❌ |
| **without HYDRO** ★ | **157,712** | **72,582** | **2.173** | 68,920 | 68,340 | **+20,452** ✅ |

**HYDROGEL bleeds -104,461 PnL on R4 day 3** with our R3-tuned config. Our anchor-based MM
on HYDROGEL is overfit to R3 days 0/1/2. Day 3 has different microstructure (still anchored
near 10000 but the v7b_guarded_loose with threshold=3.0 over-trades and gets adversely picked).

Solution for R4: disable HYDROGEL entirely until we re-tune for R4 data.

## Strategy mix (active products)

| Product | Strategy | PnL R4 |
|---|---|---:|
| HYDROGEL_PACK | **DISABLED** | 0 |
| **VELVETFRUIT_EXTRACT** | `r3_guarded_anchor_mm` (Theo v7) | **+83,048** |
| VEV_4000 | `gamma_scalp_zgated` z=0.5 | +22,272 |
| VEV_4500 | `gamma_scalp_zgated` + IV gate z=0.5 | +14,592 |
| VEV_5000 | `gamma_scalp_zgated` + IV gate z=0.5 | +8,186 |
| VEV_5100 | `gamma_scalp_zgated` + IV gate z=0.5 | +17,963 |
| VEV_5200 | `vev_option_mm_v3` (Tibo 2-sided) | +9,831 |
| VEV_5300 | `gamma_scalp_zgated` + IV gate z=0.8 | +1,535 |
| VEV_5400 | `vev_option_mm_v3` + prevent_crossing | +286 |
| VEV_5500/6000/6500 | disabled | 0 |

## TTE adjustment for R4

Live = day 4 → TTE = 4 days. Backtest days 1/2/3 → TTE 7/6/5.

```python
tte_days_initial=4.0  (live)
historical_tte_by_day={1: 7.0, 2: 6.0, 3: 5.0}  (backtest)
```

## TODO Round 4

- **Re-tune HYDROGEL for R4** : the v7b_guarded_loose params don't generalize. Try v7b with sizing reduced, or try base v4_F5 anchor only (no guard).
- **Counterparty info** : R4 exposes `buyer`/`seller` = "Mark" variants. Identify MM vs taker vs informed → adapt sizing per counterparty.
- **Manual challenge** : AETHER_CRYSTAL exotics (separate task).
