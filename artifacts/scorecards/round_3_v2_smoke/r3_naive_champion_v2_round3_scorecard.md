# Round 3 Scorecard - r3_naive_champion_v2

Days: `0`  |  execution rule: `realistic`

## Headline
| Metric | Value |
| --- | --- |
| Total PnL | 15,514 |
| Delta-1 PnL | 12,608 |
| Options PnL | 2,906 |
| Max drawdown | 10,916 |
| Fill efficiency | 0.001 |
| Avg abs net delta | 75.9 |
| Max abs net delta | 158.8 |
| Avg abs net vega | 497,155.1 |
| Max gross option pos | 226 |

## Product PnL
| Product | PnL | Trades | Max Pos | Fill Eff | Inv | Adverse | M1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | 10,126 | 324 | 113 | 0.002 | 0.279 | 0.018 | 6.67 |
| VELVETFRUIT_EXTRACT | 2,482 | 400 | 200 | 0.004 | 0.577 | 0.168 | 1.07 |
| VEV_4000 | 3,039 | 172 | 41 | 0.001 | 0.036 | 0.000 | 9.44 |
| VEV_4500 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |
| VEV_5000 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |
| VEV_5100 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |
| VEV_5200 | 82 | 3 | 15 | 0.000 | 0.020 | 0.667 | -0.50 |
| VEV_5300 | -14 | 37 | 128 | 0.000 | 0.215 | 0.281 | -0.20 |
| VEV_5400 | -180 | 22 | 71 | 0.000 | 0.110 | 0.423 | -0.16 |
| VEV_5500 | -20 | 11 | 29 | 0.000 | 0.055 | 0.345 | -0.12 |
| VEV_6000 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |
| VEV_6500 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |

## Smile Residuals
| Strike | Mean Edge | Mean Abs Edge | Fair > Mkt | Max Abs Edge | Samples |
| --- | --- | --- | --- | --- | --- |
| 4000 | 0.000 | 0.000 | 1.000 | 0.00 | 9 |
| 4500 | -0.198 | 0.198 | 0.600 | 0.50 | 5 |
| 5000 | -1.957 | 1.979 | 0.100 | 3.57 | 10 |
| 5100 | -3.841 | 3.946 | 0.200 | 5.91 | 10 |
| 5200 | -1.897 | 3.161 | 0.200 | 4.61 | 10 |
| 5300 | 1.165 | 1.476 | 0.800 | 5.81 | 10 |
| 5400 | 5.682 | 5.682 | 1.000 | 8.98 | 10 |
| 5500 | 3.545 | 3.545 | 1.000 | 5.06 | 10 |
| 6000 | 0.209 | 0.209 | 1.000 | 0.30 | 10 |
| 6500 | -0.156 | 0.156 | 0.000 | 0.26 | 10 |

## Notes
- TTE in strategy backtests now uses historical day metadata: day 0 = 8d, day 1 = 7d, day 2 = 6d.
- Live R3 still defaults to TTE = 5d when no backtest metadata is present.
- Smile residuals compare market mids to a same-timestamp quadratic smile fit; they are a triage signal, not a standalone trading rule.
