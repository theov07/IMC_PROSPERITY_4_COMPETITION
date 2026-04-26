# HYDRO Best Risk-Adjusted Lock

Locked on 2026-04-26.

## Pick

`r3_hydrogel_smart_round3_submission.py`

## Why This One

This is the best HYDRO-only risk-adjusted candidate among the clean,
non-oracle strategies currently locked, using:

`DD% = max_drawdown / 3-day PnL`

| Strategy | 3-day HYDRO PnL | Max DD | DD/PnL | Read |
| --- | ---: | ---: | ---: | --- |
| `r3_hydrogel_smart` | +28,856 | 2,652 | **9.2%** | Best risk-adjusted / robust |
| `r3_hydrogel_theo_only` | +28,340 | 3,391 | 12.0% | Theo baseline |
| `r3_hydrogel_theo_drift_only` | +28,262 | 3,391 | 12.0% | Live-validated Theo-ish |
| `r3_hydro_guarded_theo` | +29,094 | 3,790 | 13.0% | Slightly more PnL, worse relative DD |
| `r3_hydro_anchor_max3d` | +86,838 | 18,976 | 21.9% | Best clean max-PnL, not best relative DD |

## Backtest Artifact

`artifacts/analysis/round_3/smart_FULL_3days.json`

## Caveat

This is not the max-PnL pick. The clean max-PnL HYDRO lock remains:
`artifacts/submissions/round_3/locked/hydro/best_non_overfit/r3_hydro_anchor_max3d_round3_submission.py`
