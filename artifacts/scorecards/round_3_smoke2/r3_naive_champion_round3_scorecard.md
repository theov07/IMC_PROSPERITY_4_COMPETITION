# Round 3 Scorecard - r3_naive_champion

Days: `0`  |  execution rule: `realistic`

## Headline
| Metric | Value |
| --- | --- |
| Total PnL | 35,798 |
| Delta-1 PnL | 32,891 |
| Options PnL | 2,906 |
| Max drawdown | 16,946 |
| Fill efficiency | 0.004 |
| Avg abs net delta | 173.9 |
| Max abs net delta | 265.4 |
| Avg abs net vega | 551,773.4 |
| Max gross option pos | 258 |

## Product PnL
| Product | PnL | Trades | Max Pos | Fill Eff | Inv | Adverse | M1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | 18,125 | 1,389 | 196 | 0.008 | 0.848 | 0.021 | -5.93 |
| VELVETFRUIT_EXTRACT | 14,766 | 2,547 | 194 | 0.016 | 0.849 | 0.161 | -1.95 |
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
| 4000 | 0.000 | 0.000 | 1.000 | 0.00 | 4 |
| 4500 | 0.000 | 0.000 | 1.000 | 0.00 | 3 |
| 5000 | -2.759 | 2.759 | 0.000 | 3.57 | 5 |
| 5100 | -5.008 | 5.008 | 0.000 | 5.91 | 5 |
| 5200 | -3.245 | 3.245 | 0.000 | 4.61 | 5 |
| 5300 | -0.101 | 0.521 | 0.600 | 1.34 | 5 |
| 5400 | 4.990 | 4.990 | 1.000 | 6.66 | 5 |
| 5500 | 3.221 | 3.221 | 1.000 | 3.85 | 5 |
| 6000 | 0.230 | 0.230 | 1.000 | 0.30 | 5 |
| 6500 | -0.126 | 0.126 | 0.000 | 0.14 | 5 |

## Notes
- TTE in strategy backtests now uses historical day metadata: day 0 = 8d, day 1 = 7d, day 2 = 6d.
- Live R3 still defaults to TTE = 5d when no backtest metadata is present.
- Smile residuals compare market mids to a same-timestamp quadratic smile fit; they are a triage signal, not a standalone trading rule.
