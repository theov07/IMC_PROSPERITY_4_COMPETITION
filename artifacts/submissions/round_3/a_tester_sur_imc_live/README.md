# Round 3 - a tester sur IMC live

Staging folder for live upload candidates.

Created 2026-04-26 after the HYDRO lock and Claude's latest VELVET/options Pareto pass.

## Folders

- `hydrogel/`: HYDROGEL_PACK-only candidates. No oracle/timestamp/fingerprint variant included here.
- `velvet_et_options/`: VELVETFRUIT_EXTRACT + VEV candidates. HYDRO disabled in these files.
- `live_alpha_probes/`: diagnostic VELVET/options submissions for IMC live alpha tests. Not default scoring uploads.

## Upload defaults

- HYDRO-only default: `hydrogel/01_HYDRO_BEST_CLEAN__anchor_max3d__pnl86k_dd19k.py`
- **VELVET/options default (NEW post-Theo-v7)**: `velvet_et_options/00_TOP1_BEST_RATIO__v57_v7_passive_unwind__pnl156k_dd60k_ratio261.py` ★
  - Pre-Theo fallback: `velvet_et_options/02_PARETO_BALANCED__v38_drop_bad__pnl86k_dd45k_ratio190.py` (use only if R3 guard logic seems overfit live)
- First broad live-alpha probe: `live_alpha_probes/00A_BASKET_ALL_PRODUCTS_FAR_QUOTES__first_live_probe.py`
- Second broad live-alpha probe: `live_alpha_probes/00B_BASKET_ALL_PRODUCTS_GAP_FLOW_FOLLOW.py`
- Post-baseline diagnostic: `live_alpha_probes/17_DIAGNOSTIC_PARTICIPANT_AND_ADVERSE.py` (covers all 12 products, ~0 PnL, max log signal)

Use the lower-DD variants when live looks unstable, and the max-PnL variants when live resembles the 3-day backtest regime.

For alpha discovery, upload at most one file from `live_alpha_probes/` at a time, then analyze the live log. The probes assume live is close to the first 10 percent of day 2, but they use event triggers rather than timestamp/day overfit.
