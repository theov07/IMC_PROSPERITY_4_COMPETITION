# Round 3 live alpha campaign analysis

Generated from IMC logs 00A, 00B, 00C, 01..17.

Market-data hashes: 1 unique.
All logs share the same visible order-book path, so run-to-run comparisons are clean.

## Key interpretation

- Own trades checked: `3720`; outside-market volume: `0`.
- No named participant signal appears in these official logs.
- Far option quotes did not reveal an off-market fill edge; run `10` got zero fills.
- Best clean live package is `03/04/05` at about `+1,134` PnL. The three variants had identical fills, so this validates the package but not a follow-vs-fade sign.
- HYDRO passive/anchor is clean live: about `+490` PnL, `markout_5=+6.16`, adverse rate `5.7%`.
- VELVET passive MM is clean, but VELVET flow-follow/taker variants are toxic on short-horizon markout.
- VEV_4000 has two regimes: tiny passive skew is strong, while aggressive gap/flow trading is catastrophically adverse.
- VEV_4500 is the strongest new option leg; VEV_5000/5100/5200 are acceptable only in small conservative dynamic mode.
- VEV_5400+ should be disabled for live-scoring candidates unless a new signal proves otherwise.
- Combining the clean HYDRO leg with `03/04/05` would be about `+1,624` on this path. A `14` variant with VEV_5400 disabled plus HYDRO would be about `+1,727`, but with much higher VELVET inventory risk.

## Run ranking
| run | strategy | profit | trade_count | volume |
| --- | --- | --- | --- | --- |
| 04 | dyn_skew_follow | 1134.21 | 82 | 366 |
| 05 | dyn_skew_fade | 1134.21 | 82 | 366 |
| 03 | dyn_skew_auto | 1134.21 | 82 | 366 |
| 14 | iv_momentum_conservative | 1023.44 | 292 | 1396 |
| 06 | old_options_alpha | 916.44 | 87 | 348 |
| 01 | passive_skew_signal | 775.74 | 58 | 291 |
| 00A | basket_all_far_quotes | 759.99 | 127 | 211 |
| 09 | hydro_far_quotes | 489.82 | 20 | 35 |
| 07 | velvet_far_quotes | 312.15 | 65 | 134 |
| 08 | velvet_flow_follow | 74.53 | 389 | 823 |
| 16 | vol_harvest_unhedged | 50.74 | 98 | 588 |
| 10 | options_far_quotes | 0.00 | 0 | 0 |
| 17 | participant_adverse_diagnostic | -29.99 | 30 | 30 |
| 13 | options_flow_fade | -317.85 | 35 | 35 |
| 12 | options_flow_follow | -409.15 | 35 | 35 |
| 00C | basket_all_options_flow_fade | -586.67 | 207 | 207 |
| 02 | skew_taker_toxicity | -652.41 | 184 | 1125 |
| 11 | options_gap_sweep | -2380.97 | 300 | 300 |
| 15 | iv_momentum_aggro | -3126.15 | 472 | 3217 |
| 00B | basket_all_gap_flow_follow | -3275.56 | 1075 | 1165 |

## Final PnL by product
| run | strategy | HYDROGEL_PACK | VELVETFRUIT_EXTRACT | VEV_4000 | VEV_4500 | VEV_5000 | VEV_5100 | VEV_5200 | VEV_5300 | VEV_5400 | VEV_5500 | VEV_6000 | VEV_6500 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 00A | basket_all_far_quotes | 489.82 | 312.15 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | -20.98 | -21.00 |
| 00B | basket_all_gap_flow_follow | 489.82 | -1004.08 | -2833.92 | 9.92 | 10.00 | 23.87 | 0.00 | 31.62 | 13.29 | -16.07 | -0.02 | -0.00 |
| 00C | basket_all_options_flow_fade | 0.00 | 0.00 | -317.85 | 0.00 | 0.00 | 0.00 | 0.00 | -109.62 | -68.29 | -30.93 | -29.98 | -30.00 |
| 01 | passive_skew_signal | 0.00 | 641.77 | 134.23 | 0.00 | 0.20 | -0.02 | -0.45 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 02 | skew_taker_toxicity | 0.00 | 641.77 | 134.23 | 25.39 | -162.79 | -786.26 | -504.75 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 03 | dyn_skew_auto | 0.00 | 641.77 | 134.23 | 248.56 | 64.85 | 25.81 | 18.99 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 04 | dyn_skew_follow | 0.00 | 641.77 | 134.23 | 248.56 | 64.85 | 25.81 | 18.99 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 05 | dyn_skew_fade | 0.00 | 641.77 | 134.23 | 248.56 | 64.85 | 25.81 | 18.99 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 06 | old_options_alpha | 0.00 | 641.77 | 134.23 | 99.23 | 24.61 | 11.94 | 4.66 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 07 | velvet_far_quotes | 0.00 | 312.15 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 08 | velvet_flow_follow | 0.00 | 74.53 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 09 | hydro_far_quotes | 489.82 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 10 | options_far_quotes | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 11 | options_gap_sweep | 0.00 | 0.00 | -2424.77 | 9.92 | 10.00 | 23.87 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 12 | options_flow_follow | 0.00 | 0.00 | -409.15 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 13 | options_flow_fade | 0.00 | 0.00 | -317.85 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 14 | iv_momentum_conservative | 0.00 | 749.88 | 134.23 | 243.48 | 64.65 | 25.83 | 19.43 | 0.00 | -214.06 | 0.00 | 0.00 | 0.00 |
| 15 | iv_momentum_aggro | 0.00 | 749.88 | 134.23 | 243.48 | -1717.35 | -1331.90 | -953.42 | 0.00 | -251.08 | 0.00 | 0.00 | 0.00 |
| 16 | vol_harvest_unhedged | 0.00 | 641.77 | 134.23 | 0.00 | -201.83 | -175.05 | -100.29 | -145.26 | -76.96 | -25.87 | 0.00 | 0.00 |
| 17 | participant_adverse_diagnostic | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | -14.99 | -15.00 |

## Largest traded product/run buckets
| run | strategy | product | trade_count | volume | outside_volume | taker_like_volume | avg_fill_mid_edge | markout_5 | adverse_rate_5 | markout_10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 14 | iv_momentum_conservative | VELVETFRUIT_EXTRACT | 252 | 1227 | 0 | 1060 | -1.938 | -1.768 | 0.751 | -2.451 |
| 15 | iv_momentum_aggro | VELVETFRUIT_EXTRACT | 252 | 1227 | 0 | 1060 | -1.938 | -1.768 | 0.751 | -2.451 |
| 08 | velvet_flow_follow | VELVETFRUIT_EXTRACT | 389 | 823 | 0 | 698 | -1.889 | -1.876 | 0.761 | -1.787 |
| 00B | basket_all_gap_flow_follow | VELVETFRUIT_EXTRACT | 548 | 623 | 0 | 516 | -1.846 | -1.945 | 0.788 | -1.931 |
| 15 | iv_momentum_aggro | VEV_5100 | 68 | 616 | 0 | 608 | -2.170 | -2.577 | 0.781 | -2.991 |
| 15 | iv_momentum_aggro | VEV_5000 | 61 | 610 | 0 | 604 | -3.039 | -3.346 | 0.859 | -3.525 |
| 15 | iv_momentum_aggro | VEV_5200 | 59 | 604 | 0 | 601 | -1.469 | -1.744 | 0.848 | -2.194 |
| 02 | skew_taker_toxicity | VEV_5100 | 57 | 382 | 0 | 377 | -2.134 | -1.993 | 0.785 | -1.488 |
| 02 | skew_taker_toxicity | VEV_5200 | 57 | 380 | 0 | 375 | -1.439 | -1.250 | 0.779 | -0.874 |
| 00B | basket_all_gap_flow_follow | VEV_4000 | 288 | 288 | 0 | 288 | -10.064 | -9.524 | 0.951 | -9.561 |
| 01 | passive_skew_signal | VELVETFRUIT_EXTRACT | 47 | 273 | 0 | 0 | 1.544 | 1.245 | 0.198 | 1.119 |
| 05 | dyn_skew_fade | VELVETFRUIT_EXTRACT | 47 | 273 | 0 | 0 | 1.544 | 1.245 | 0.198 | 1.119 |
| 06 | old_options_alpha | VELVETFRUIT_EXTRACT | 47 | 273 | 0 | 0 | 1.544 | 1.245 | 0.198 | 1.119 |
| 03 | dyn_skew_auto | VELVETFRUIT_EXTRACT | 47 | 273 | 0 | 0 | 1.544 | 1.245 | 0.198 | 1.119 |
| 02 | skew_taker_toxicity | VELVETFRUIT_EXTRACT | 47 | 273 | 0 | 0 | 1.544 | 1.245 | 0.198 | 1.119 |
| 16 | vol_harvest_unhedged | VELVETFRUIT_EXTRACT | 47 | 273 | 0 | 0 | 1.544 | 1.245 | 0.198 | 1.119 |
| 04 | dyn_skew_follow | VELVETFRUIT_EXTRACT | 47 | 273 | 0 | 0 | 1.544 | 1.245 | 0.198 | 1.119 |
| 11 | options_gap_sweep | VEV_4000 | 253 | 253 | 0 | 253 | -10.020 | -9.547 | 0.949 | -9.470 |
| 07 | velvet_far_quotes | VELVETFRUIT_EXTRACT | 65 | 134 | 0 | 21 | 1.086 | 0.668 | 0.351 | 0.838 |
| 00A | basket_all_far_quotes | VELVETFRUIT_EXTRACT | 65 | 134 | 0 | 21 | 1.086 | 0.668 | 0.351 | 0.838 |
| 15 | iv_momentum_aggro | VEV_5400 | 11 | 100 | 0 | 100 | -0.725 | -0.850 | 0.750 | -0.835 |
| 14 | iv_momentum_conservative | VEV_5400 | 9 | 80 | 0 | 80 | -0.688 | -0.588 | 0.662 | -0.650 |
| 02 | skew_taker_toxicity | VEV_5000 | 14 | 70 | 0 | 65 | -2.471 | -2.407 | 0.800 | -0.464 |
| 16 | vol_harvest_unhedged | VEV_5500 | 7 | 50 | 0 | 50 | -0.500 | -0.500 | 1.000 | -0.500 |
| 16 | vol_harvest_unhedged | VEV_5100 | 7 | 50 | 0 | 50 | -2.210 | -4.270 | 1.000 | -3.990 |
| 16 | vol_harvest_unhedged | VEV_5400 | 7 | 50 | 0 | 50 | -0.820 | -1.140 | 1.000 | -1.140 |
| 16 | vol_harvest_unhedged | VEV_5200 | 7 | 50 | 0 | 50 | -1.640 | -3.300 | 1.000 | -3.180 |
| 16 | vol_harvest_unhedged | VEV_5300 | 8 | 50 | 0 | 50 | -1.080 | -1.960 | 1.000 | -1.610 |
| 16 | vol_harvest_unhedged | VEV_5000 | 7 | 50 | 0 | 50 | -2.960 | -5.160 | 1.000 | -4.720 |
| 03 | dyn_skew_auto | VEV_4500 | 14 | 46 | 0 | 37 | -1.739 | 2.076 | 0.152 | 1.804 |
| 05 | dyn_skew_fade | VEV_4500 | 14 | 46 | 0 | 37 | -1.739 | 2.076 | 0.152 | 1.804 |
| 04 | dyn_skew_follow | VEV_4500 | 14 | 46 | 0 | 37 | -1.739 | 2.076 | 0.152 | 1.804 |
| 15 | iv_momentum_aggro | VEV_4500 | 13 | 45 | 0 | 37 | -1.933 | 2.011 | 0.156 | 1.733 |
| 14 | iv_momentum_conservative | VEV_4500 | 13 | 45 | 0 | 37 | -1.933 | 2.011 | 0.156 | 1.733 |
| 00B | basket_all_gap_flow_follow | VEV_5500 | 39 | 39 | 0 | 39 | -0.603 | -0.658 | 0.921 | -0.658 |
| 00C | basket_all_options_flow_fade | VEV_5500 | 39 | 39 | 0 | 39 | -0.603 | -0.553 | 0.842 | -0.553 |
| 00B | basket_all_gap_flow_follow | VEV_5400 | 37 | 37 | 0 | 37 | -0.743 | -0.581 | 0.784 | -0.608 |
| 00C | basket_all_options_flow_fade | VEV_5400 | 37 | 37 | 0 | 37 | -0.743 | -0.905 | 0.811 | -0.878 |
| 00B | basket_all_gap_flow_follow | VEV_5300 | 36 | 36 | 0 | 36 | -1.083 | -1.167 | 0.778 | -1.181 |
| 00C | basket_all_options_flow_fade | VEV_5300 | 36 | 36 | 0 | 36 | -1.083 | -1.000 | 0.778 | -0.986 |

## Outside-market fills
No outside-market fills detected.

## Probe feature summary sample
| run | strategy | product | quote_rows | sum_far_probe | max_far_probe | sum_gap_sweep | max_gap_sweep | sum_flow_probe | max_flow_probe | last_flow_score | sum_n_far_probes | max_n_far_probes | sum_fills_tracked | max_fills_tracked | sum_adverse_count | max_adverse_count | sum_named_market_trades | max_named_market_trades | last_adverse_rate | last_avg_signed_mtm | last_session_phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 00A | basket_all_far_quotes | VEV_5200 | 1000 | 7.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00A | basket_all_far_quotes | VEV_5400 | 960 | 6.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00A | basket_all_far_quotes | VEV_5500 | 30 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00B | basket_all_gap_flow_follow | VEV_5200 | 980 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00B | basket_all_gap_flow_follow | VEV_5300 | 20 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | -0.880 |  |  |  |  |  |  |  |  |  |  |  |
| 00B | basket_all_gap_flow_follow | VEV_5400 | 730 | 0.000 | 0.000 | 0.000 | 0.000 | 26.000 | 1.000 | -1.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00B | basket_all_gap_flow_follow | VEV_5500 | 150 | 0.000 | 0.000 | 0.000 | 0.000 | 8.000 | 1.000 | -1.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00B | basket_all_gap_flow_follow | VEV_6000 | 20 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | -1.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00B | basket_all_gap_flow_follow | VEV_6500 | 40 | 0.000 | 0.000 | 0.000 | 0.000 | 2.000 | 1.000 | -1.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00C | basket_all_options_flow_fade | VEV_5200 | 980 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00C | basket_all_options_flow_fade | VEV_5300 | 20 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | -1.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00C | basket_all_options_flow_fade | VEV_5400 | 740 | 0.000 | 0.000 | 0.000 | 0.000 | 26.000 | 1.000 | -1.000 |  |  |  |  |  |  |  |  |  |  |  |
| 00C | basket_all_options_flow_fade | VEV_5500 | 200 | 0.000 | 0.000 | 0.000 | 0.000 | 10.000 | 1.000 | 0.549 |  |  |  |  |  |  |  |  |  |  |  |
| 00C | basket_all_options_flow_fade | VEV_6500 | 20 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | -1.000 |  |  |  |  |  |  |  |  |  |  |  |
| 07 | velvet_far_quotes | VELVETFRUIT_EXTRACT | 1000 |  |  |  |  |  |  | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 08 | velvet_flow_follow | VELVETFRUIT_EXTRACT | 1000 |  |  |  |  |  |  | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 09 | hydro_far_quotes | HYDROGEL_PACK | 1000 |  |  |  |  |  |  | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 10 | options_far_quotes | VEV_4500 | 1000 | 7.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 10 | options_far_quotes | VEV_5100 | 970 | 7.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 10 | options_far_quotes | VEV_5200 | 30 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 11 | options_gap_sweep | VEV_4000 | 1000 | 0.000 | 0.000 | 200.000 | 1.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 11 | options_gap_sweep | VEV_4500 | 1000 | 0.000 | 0.000 | 21.000 | 1.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 11 | options_gap_sweep | VEV_5200 | 120 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 12 | options_flow_follow | VEV_4000 | 1000 | 0.000 | 0.000 | 0.000 | 0.000 | 35.000 | 1.000 | 0.875 |  |  |  |  |  |  |  |  |  |  |  |
| 12 | options_flow_follow | VEV_4500 | 1000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 12 | options_flow_follow | VEV_5200 | 710 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 13 | options_flow_fade | VEV_4000 | 1000 | 0.000 | 0.000 | 0.000 | 0.000 | 35.000 | 1.000 | 0.875 |  |  |  |  |  |  |  |  |  |  |  |
| 13 | options_flow_fade | VEV_4500 | 1000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 13 | options_flow_fade | VEV_5200 | 810 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |  |  |  |  |  |  |  |  |  |  |
| 17 | participant_adverse_diagnostic | VEV_5300 | 10 |  |  |  |  |  |  |  | 10.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 17 | participant_adverse_diagnostic | VEV_5400 | 990 |  |  |  |  |  |  |  | 2990.000 | 5.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 2.000 |
| 17 | participant_adverse_diagnostic | VEV_5500 | 10 |  |  |  |  |  |  |  | 10.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 17 | participant_adverse_diagnostic | VEV_6000 | 890 |  |  |  |  |  |  |  | 2860.000 | 5.000 | 8535.000 | 15.000 | 8535.000 | 15.000 | 0.000 | 0.000 | 1.000 | -0.500 | 2.000 |
