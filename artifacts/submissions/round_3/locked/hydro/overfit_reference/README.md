# HYDRO Overfit Reference

Locked on 2026-04-25.

## Reference

`r3_hydro_anchor_oracle_hybrid_round3_submission.py`

## Backtest

| Metric | Value |
| --- | ---: |
| HYDRO 3-day PnL | +106,800 |
| Day 0 | +20,158 |
| Day 1 | +37,306 |
| Day 2 | +49,336 |
| Max drawdown | 28,400 |
| Size | 86,597 B |

Backtest artifact:
`artifacts/backtest_results/round_3/r3_hydro_anchor_oracle_hybrid_TUNED_3d.json`

## Caveat

This is not the clean HYDRO lock. It is intentionally day2-oracle/fingerprint
overfit and is kept only as a reference experiment.

The clean HYDRO lock is:
`artifacts/submissions/round_3/locked/hydro/best_non_overfit/r3_hydro_anchor_max3d_round3_submission.py`
with `+86,838` 3-day PnL.
