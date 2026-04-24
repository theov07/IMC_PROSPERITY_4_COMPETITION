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
| 4000 | 0.050 | 0.050 | 1.000 | 0.77 | 18 |
| 4500 | -0.352 | 0.353 | 0.545 | 2.10 | 11 |
| 5000 | -1.459 | 2.047 | 0.250 | 3.65 | 20 |
| 5100 | -3.401 | 3.716 | 0.250 | 6.13 | 20 |
| 5200 | -1.823 | 2.740 | 0.200 | 4.70 | 20 |
| 5300 | 0.595 | 1.220 | 0.550 | 5.81 | 20 |
| 5400 | 5.161 | 5.161 | 1.000 | 8.98 | 20 |
| 5500 | 3.012 | 3.012 | 1.000 | 5.06 | 20 |
| 6000 | 0.164 | 0.191 | 0.850 | 0.30 | 20 |
| 6500 | -0.129 | 0.131 | 0.100 | 0.26 | 20 |

## Notes
- TTE in strategy backtests now uses historical day metadata: day 0 = 8d, day 1 = 7d, day 2 = 6d.
- Live R3 still defaults to TTE = 5d when no backtest metadata is present.
- Smile residuals compare market mids to a same-timestamp quadratic smile fit; they are a triage signal, not a standalone trading rule.
