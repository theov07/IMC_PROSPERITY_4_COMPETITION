# Round 4 Baseline — `r3_combined_best`

Starting point for Round 4 development. Combines our best per-product strategies from Round 3.

## Backtest performance (Round 3, 3-day, realistic fill)

| Metric | Value |
|---|---:|
| **PnL** | **265,486** |
| **DD** | **73,666** |
| **Ratio** | **3.604** |
| **CV%** | **27.8%** |
| File size | 93,905 bytes (< 100KB ✓) |

## vs Round 3 final_sub (uploaded)

| | final_sub_v100 (uploaded) | r3_combined_best (this) | Δ |
|---|---:|---:|---:|
| PnL | 240,918 | **265,486** | **+24,568** ★ |
| DD | 56,858 | 73,666 | +16,808 |
| Ratio | 4.237 | 3.604 | -0.633 |

## What changed vs final_sub

| Product | final_sub | r3_combined | Δ | Reason |
|---|---:|---:|---:|---|
| **VEV_5100** | 0 ❌ | **19,564** ✅ | **+19,564** | Our `gamma_scalp_zgated` + IV gate trades it (vs Tibo's class blocked it) |
| **VEV_5000** | 490 | 9,536 | +9,046 | Same IV gate fix |
| VEV_4500 | 18,802 | 16,062 | -2,740 | Theo's z=2.0 was slightly better |
| HYDROGEL | 100,470 | 99,541 | -929 | identical strategy, noise |
| Other | identical | identical | 0 | (VELVET, VEV_5200/5300/5400) |

**Net win: +24,568 PnL** because our strategy class unblocks VEV_5000 + VEV_5100 fills.

## Strategy mix

| Product | Strategy | Notes |
|---|---|---|
| HYDROGEL_PACK | `r3_guarded_anchor_mm` (v7b_guarded_loose) | guard threshold 3.0 + toxic flow + passive unwind |
| VELVETFRUIT_EXTRACT | `r3_guarded_anchor_mm` (v57) | guard 7.5 + toxic + unwind (Theo v7) |
| VEV_4000 | `gamma_scalp_zgated` z=0.5 | |
| VEV_4500/5000/5100 | `gamma_scalp_zgated` + IV gate z=0.5 | **KEY: IV gate enables VEV_5100/5000** |
| VEV_5200, 5400 | `vev_option_mm_v3` (Tibo's 2-sided MM) | bid 20 / ask 5 wide |
| VEV_5300 | `gamma_scalp_zgated` + IV gate z=0.8 | |
| VEV_5500/6000/6500 | disabled | drag in BT |

## Round 4 considerations

- Position limits same as R3: HYDRO/VELVET=200, VEV=300
- TTE: live ≈ 4 days for VEV (vs 5 in R3) → may need adjustment
- **NEW**: counterparty info (`buyer`/`seller` = "Mark" variants) → opportunity to identify market participants
- Manual challenge: AETHER_CRYSTAL exotics (separate from algo)

## Member config

`MEMBER_OVERRIDES["r3_combined_best"]` in `prosperity/config.py`.
