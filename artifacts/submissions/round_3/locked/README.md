# Round 3 Locked Submissions

Created on 2026-04-25 after the HYDRO strategy lock-in pass.

**UPDATED 2026-04-26**: TIER 1 candidates added below after Theo v6 (toxic flow) and v7 (passive unwind) integrations. New default for VELVET/options is `v57_v7_passive_unwind` (PnL 156k / DD 60k / Ratio 2.612).

## Folders

| Folder | Purpose |
| --- | --- |
| `hydro/` | Four HYDRO-only candidates to keep as the locked base set. |
| `hydro/best_non_overfit/` | Clean HYDRO lock: best full-session backtest without day/timestamp fingerprint. |
| `hydro/best_risk_adjusted/` | Clean HYDRO risk-adjusted lock: best PnL/DD among non-oracle HYDRO candidates. |
| `hydro/overfit_reference/` | Day2-oracle/fingerprint reference only; not the clean HYDRO lock. |
| `velvet_options/` | VELVET + vouchers only, no HYDRO. |
| `combined/` | Combined HYDRO hybrid + VELVET/options submission. |

## Locked Files

| Strategy | File | Size | 3-day PnL | Live-window 3-day | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `r3_hydro_anchor_max3d` | `hydro/r3_hydro_anchor_max3d_round3_submission.py` | 71,338 | +86,838 | -14,348 | Best simple full-session HYDRO anchor. |
| `r3_hydro_anchor_max3d` | `hydro/best_non_overfit/r3_hydro_anchor_max3d_round3_submission.py` | 71,338 | +86,838 | -14,348 | Locked clean HYDRO pick; no day/timestamp fingerprint. |
| `r3_hydrogel_smart` | `hydro/best_risk_adjusted/r3_hydrogel_smart_round3_submission.py` | 33,953 | +28,856 | +2,968 | Locked clean HYDRO risk-adjusted pick; PnL/DD about 10.9 on full sessions. |
| `r3_hydro_day2_oracle_regime` | `hydro/r3_hydro_day2_oracle_regime_round3_submission.py` | 58,331 | +73,243 | +40,923 | Day2 fingerprint -> L1 oracle, otherwise guarded Theo. |
| `r3_hydro_anchor_oracle_hybrid` | `hydro/r3_hydro_anchor_oracle_hybrid_round3_submission.py` | 86,597 | +106,800 | +28,814 | Strongest HYDRO 3-day, but highly day2-oracle overfit. |
| `r3_hydro_anchor_oracle_hybrid` | `hydro/overfit_reference/r3_hydro_anchor_oracle_hybrid_round3_submission.py` | 86,597 | +106,800 | +28,814 | Overfit reference only. |
| `r3_hydrogel_smart` | `hydro/r3_hydrogel_smart_round3_submission.py` | 33,953 | +28,856 | +2,968 | Research/live-robust HYDRO baseline. |
| `r3_velvet_options_alpha` | `velvet_options/r3_velvet_options_alpha_round3_submission.py` | 60,393 | +13,380 | +1,739 | VELVET/options passive alpha, HYDRO disabled (legacy). |
| `r3_combined_hybrid_options` | `combined/r3_combined_hybrid_options_round3_submission_minified.py` | 95,101 | +120,180 | approx +30,553 | HYDRO hybrid + VELVET/options, minified to fit under 100 KB. |
| **`v57_v7_passive_unwind` ★** | **`velvet_options/TOP1_BEST_RATIO__v57_v7_passive_unwind__pnl156k_dd60k_ratio261.py`** | ~95k | **+156,010** | n/a | **NEW DEFAULT** — R3GuardedAnchor + toxic flow + passive unwind on VELVET. DD 59,720, Ratio 2.612. Sensitivity verified on `passive_unwind_trigger` (range 0.30-0.50 → +5.9k to +6.4k boost, robust). |
| `v58_v7_with_5300` | `velvet_options/TOP2_BALANCED__v58_v7_with_5300__pnl159k_dd62k_ratio255.py` | ~95k | +158,696 | n/a | TOP1 + VEV_5300 strike. DD 62,165, Ratio 2.553. Strictly dominates v54+v56. |

## Validation Notes

- All six locked files compile with `python -m py_compile`.
- The non-minified combined export validated through `scripts/export_submission.py`.
- The minified combined file imports and instantiates `Trader` successfully.
- Original combined export is over the IMC size limit; use the minified file in `combined/`.
