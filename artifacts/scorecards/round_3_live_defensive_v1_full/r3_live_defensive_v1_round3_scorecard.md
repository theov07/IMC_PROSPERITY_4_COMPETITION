# Round 3 Scorecard - r3_live_defensive_v1

Days: `0, 1, 2`  |  execution rule: `realistic`

## Headline
| Metric | Value |
| --- | --- |
| Total PnL | 32,946 |
| Delta-1 PnL | 19,759 |
| Options PnL | 13,186 |
| Max drawdown | 5,374 |
| Fill efficiency | 0.001 |
| Avg abs net delta | 25.0 |
| Max abs net delta | 104.4 |
| Avg abs net vega | 548,814.6 |
| Max gross option pos | 294 |

## Product PnL
| Product | PnL | Trades | Max Pos | Fill Eff | Inv | Adverse | M1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | 18,056 | 882 | 71 | 0.003 | 0.166 | 0.015 | 6.93 |
| VELVETFRUIT_EXTRACT | 1,703 | 1,216 | 72 | 0.005 | 0.206 | 0.194 | 1.06 |
| VEV_4000 | 8,810 | 464 | 44 | 0.001 | 0.037 | 0.001 | 9.45 |
| VEV_4500 | -34 | 1 | 1 | 0.000 | 0.001 | 1.000 | -5.00 |
| VEV_5000 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |
| VEV_5100 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |
| VEV_5200 | 1,314 | 17 | 26 | 0.000 | 0.029 | 0.339 | 0.11 |
| VEV_5300 | 2,787 | 116 | 150 | 0.000 | 0.231 | 0.322 | -0.20 |
| VEV_5400 | 330 | 62 | 77 | 0.000 | 0.123 | 0.310 | -0.13 |
| VEV_5500 | -20 | 28 | 30 | 0.000 | 0.059 | 0.369 | -0.14 |
| VEV_6000 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |
| VEV_6500 | 0 | 0 | 0 | 0.000 | 0.000 | n/a | n/a |

## Smile Residuals
| Strike | Mean Edge | Mean Abs Edge | Fair > Mkt | Max Abs Edge | Samples |
| --- | --- | --- | --- | --- | --- |
| 4000 | 0.019 | 0.039 | 0.962 | 1.24 | 529 |
| 4500 | -0.235 | 0.238 | 0.619 | 3.25 | 409 |
| 5000 | -1.138 | 1.534 | 0.273 | 3.78 | 600 |
| 5100 | -1.936 | 2.747 | 0.227 | 6.28 | 600 |
| 5200 | -1.868 | 3.131 | 0.233 | 8.29 | 600 |
| 5300 | 0.091 | 1.937 | 0.395 | 7.83 | 600 |
| 5400 | 5.546 | 5.558 | 0.992 | 10.41 | 600 |
| 5500 | 3.020 | 3.043 | 0.975 | 6.41 | 600 |
| 6000 | 0.077 | 0.123 | 0.753 | 0.36 | 600 |
| 6500 | -0.112 | 0.130 | 0.125 | 0.28 | 600 |

## Notes
- TTE in strategy backtests now uses historical day metadata: day 0 = 8d, day 1 = 7d, day 2 = 6d.
- Live R3 still defaults to TTE = 5d when no backtest metadata is present.
- Smile residuals compare market mids to a same-timestamp quadratic smile fit; they are a triage signal, not a standalone trading rule.
