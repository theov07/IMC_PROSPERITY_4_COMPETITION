# Round 3 Locked Submissions

Created on 2026-04-25 after the HYDRO strategy lock-in pass.

## Folders

| Folder | Purpose |
| --- | --- |
| `hydro/` | Four HYDRO-only candidates to keep as the locked base set. |
| `velvet_options/` | VELVET + vouchers only, no HYDRO. |
| `combined/` | Combined HYDRO hybrid + VELVET/options submission. |

## Locked Files

| Strategy | File | Size | 3-day PnL | Live-window 3-day | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `r3_hydro_anchor_max3d` | `hydro/r3_hydro_anchor_max3d_round3_submission.py` | 71,338 | +86,838 | -14,348 | Best simple full-session HYDRO anchor. |
| `r3_hydro_day2_oracle_regime` | `hydro/r3_hydro_day2_oracle_regime_round3_submission.py` | 58,331 | +73,243 | +40,923 | Day2 fingerprint -> L1 oracle, otherwise guarded Theo. |
| `r3_hydro_anchor_oracle_hybrid` | `hydro/r3_hydro_anchor_oracle_hybrid_round3_submission.py` | 86,597 | +106,800 | +28,814 | Strongest HYDRO 3-day, but highly day2-oracle overfit. |
| `r3_hydrogel_smart` | `hydro/r3_hydrogel_smart_round3_submission.py` | 33,953 | +28,856 | +2,968 | Research/live-robust HYDRO baseline. |
| `r3_velvet_options_alpha` | `velvet_options/r3_velvet_options_alpha_round3_submission.py` | 60,393 | +13,380 | +1,739 | VELVET/options passive alpha, HYDRO disabled. |
| `r3_combined_hybrid_options` | `combined/r3_combined_hybrid_options_round3_submission_minified.py` | 95,101 | +120,180 | approx +30,553 | HYDRO hybrid + VELVET/options, minified to fit under 100 KB. |

## Validation Notes

- All six locked files compile with `python -m py_compile`.
- The non-minified combined export validated through `scripts/export_submission.py`.
- The minified combined file imports and instantiates `Trader` successfully.
- Original combined export is over the IMC size limit; use the minified file in `combined/`.
