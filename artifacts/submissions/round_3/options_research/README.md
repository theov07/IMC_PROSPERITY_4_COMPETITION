# Round 3 VELVET + Options Research Exports

All files here are VELVET/options-only candidates.  HYDRO is disabled in these
configs.  Backtest JSONs live in
`artifacts/backtest_results/round_3/options_research/`.

| Export | Size | 3-day realistic PnL | Read |
| --- | ---: | ---: | --- |
| `r3_velvet_options_max3d_blend_round3_submission.py` | 57,872 B | +23,440.5 | Max-3d product-wise blend: selective 4500, gamma 5000/5100/5200, high-k 5300/5400. |
| `r3_velvet_options_gamma_unhedged_round3_submission.py` | 61,422 B | +21,090.0 | Best new PnL; long-gamma/long-call exposure, no delta hedge. |
| `r3_velvet_options_alpha_v4_high_k_round3_submission.py` | 55,691 B | +16,510.0 | Best conservative passive baseline from Claude's high-strike unlock. |
| `r3_velvet_options_vol_harvest_unhedged_round3_submission.py` | 63,743 B | +14,720.5 | Long-vol version without hedge. |
| `r3_velvet_options_alpha_v3_round3_submission.py` | 55,687 B | +13,562.5 | Conservative baseline from Claude/Codex research. |
| `r3_velvet_options_skew_signal_round3_submission.py` | 66,899 B | +12,099.5 | Leave-one-out skew signal; mostly passive/no fills. |
| `r3_velvet_options_vol_harvest_round3_submission.py` | 77,373 B | +10,793.5 | Hedged long-vol; hedge costs PnL. |
| `r3_velvet_options_bs_guarded_taker_round3_submission.py` | 55,688 B | +6,947.0 | Guarded BS takers; weaker than baseline. |
| `r3_velvet_options_gamma_scalp_round3_submission.py` | 75,050 B | +32.5 | Hedged gamma; VELVET hedge destroys gains. |

Rejected but tested:

- `r3_velvet_options_skew_taker`: `-45,734.5` over 3 days.  ATM skew takers on
  `VEV_5000/5100/5200` are toxic after execution, despite promising markout
  scans.

Recommended live probing order:

1. `r3_velvet_options_alpha_v4_high_k_round3_submission.py`: strongest
   conservative passive baseline.
2. `r3_velvet_options_max3d_blend_round3_submission.py`: current max 3-day
   backtest candidate.
3. `r3_velvet_options_vol_harvest_unhedged_round3_submission.py`: lower-PnL
   version of the same broad thesis.
