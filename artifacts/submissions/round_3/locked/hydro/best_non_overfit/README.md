# HYDRO Best Non-Overfit Lock

Locked on 2026-04-25.

## Pick

`r3_hydro_anchor_max3d_round3_submission.py`

## Why This One

This is the best HYDRO-only full-session backtest that does not use a day or
timestamp fingerprint/oracle path.

The VELVET-style z-score mean-reversion transfer was tested on HYDRO and did
not improve this anchor:

| Strategy | 3-day HYDRO PnL | Max DD | Read |
| --- | ---: | ---: | --- |
| `r3_hydro_anchor_max3d` | **+86,838** | 18,976 | Locked clean base, DD/PnL 21.9% |
| `r3_hydro_anchor_zgate_05` | +85,174 | 19,343 | Worse, DD/PnL 22.7% |
| `r3_hydro_anchor_zgate_10` | +85,784 | 19,234 | Best z-gate, still worse, DD/PnL 22.4% |
| `r3_hydro_anchor_zgate_taker_15` | +72,374 | 19,968 | Taker overlay hurts, DD/PnL 27.6% |

## Backtest

| Day | HYDRO PnL |
| --- | ---: |
| Day 0 | +20,158 |
| Day 1 | +37,306 |
| Day 2 | +29,374 |
| Total | +86,838 |

Max DD: `18,976`, so relative DD is `21.9%` of final PnL.

Backtest artifact:
`artifacts/backtest_results/round_3/r3_hydro_anchor_max3d_TUNED_3d.json`

## Caveat

This is still optimized on the three historical days, but it does not rely on a
day2 fingerprint, known timestamp replay, or oracle actions.
