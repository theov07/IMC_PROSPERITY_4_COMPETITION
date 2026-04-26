# Round 3 Scorecard - r3_guarded_hybrid_v2

Days: `0, 1, 2`  |  execution rule: `realistic`

## Headline
| Metric | Value |
| --- | --- |
| Total PnL | 72,332 |
| Delta-1 PnL | 59,146 |
| Options PnL | 13,186 |
| Max drawdown | 12,884 |
| Fill efficiency | 0.002 |
| Avg abs net delta | 112.8 |
| Max abs net delta | 232.6 |
| Avg abs net vega | 548,814.6 |
| Max gross option pos | 294 |

## Product PnL
| Product | PnL | Trades | Max Pos | Fill Eff | Inv | Adverse | M1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | 23,282 | 1,010 | 134 | 0.002 | 0.257 | 0.013 | 6.93 |
| VELVETFRUIT_EXTRACT | 35,864 | 6,369 | 144 | 0.013 | 0.770 | 0.227 | -1.45 |
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
