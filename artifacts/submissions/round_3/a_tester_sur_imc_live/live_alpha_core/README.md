# r3_live_alpha_core_v1

Live-evidence candidate built from IMC probes `00A..17`.

Upload file:

- `r3_live_alpha_core_v1_round3_submission_stripped_minified.py`
- Size: `73,841` bytes
- Validation: syntax OK, no banned imports, `Trader.__init__` OK, `run()` OK,
  p99 runtime about `1.35ms`

Design:

- `HYDROGEL_PACK`: clean fixed-anchor v4_F5 HYDRO base.
- `VELVETFRUIT_EXTRACT`: small passive `naive_tight_mm`; no flow-follow takers.
- `VEV_4000`: tiny passive `option_mm_bs`; no takers.
- `VEV_4500`: dynamic z/IV-gated `gamma_scalp_zgated`, capped below full size.
- `VEV_5000/5100/5200`: smaller conservative dynamic z/IV-gated legs.
- `VEV_5300+`: disabled.

Backtests, realistic:

| Window | Total PnL | JSON |
|---|---:|---|
| Day 2 | `+46,211.5` | `artifacts/backtest_results/round_3/live_alpha_core/r3_live_alpha_core_v1_day2.json` |
| 3 days | `+120,332` | `artifacts/backtest_results/round_3/live_alpha_core/r3_live_alpha_core_v1_3days.json` |

3-day product PnL:

| Product | PnL | Max pos |
|---|---:|---:|
| HYDROGEL_PACK | `+86,838` | `195` |
| VELVETFRUIT_EXTRACT | `+3,290` | `40` |
| VEV_4000 | `+8,809.5` | `44` |
| VEV_4500 | `+11,679` | `160` |
| VEV_5000 | `+3,654` | `60` |
| VEV_5100 | `+3,063` | `60` |
| VEV_5200 | `+2,998.5` | `60` |
| VEV_5300+ | `0` | `0` |

Read:

- This is not the max-backtest VELVET/options candidate. It is a live-signal
  candidate: fewer products, lower option size, and explicit removal of the
  live-toxic gap/flow/VEV_5400+ behavior.
- The weakest included leg is `VEV_5200`: backtest PnL is positive, but
  3-day short-horizon markout is slightly negative. Keep it only because live
  campaign `03/04/05` showed positive small-size behavior.
