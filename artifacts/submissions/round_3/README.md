# Round 3 — Submissions Index (cleaned 2026-04-26)

## 🏆 PRIMARY — final delivery for IMC

- **`_FINAL_DELIVERY/FINAL_SUB__pnl241k_dd57k_ratio424.py`** ★ — the strategy actually uploaded for Round 3 final
  - 240,918 PnL / 56,858 DD / Ratio 4.237 / CV 22.7% (3-day backtest)
  - Live result: **+64,195 PnL** on a fresh data day (1 full session)

## 📁 Directory map

| Folder | Purpose |
|---|---|
| `_FINAL_DELIVERY/` | The single uploaded final submission |
| `_final/velvet_options/00_FINAL_CANDIDATES/` | 5 Pareto-optimal velvet+options candidates (TOP0-TOP4) |
| `a_tester_sur_imc_live/` | Files prepared for live IMC testing (per-folder upload guidance) |
| `a_tester_sur_imc_live/hydrogel/` | HYDRO-only candidates |
| `a_tester_sur_imc_live/velvet_et_options/` | velvet+options candidates (also has minified <100KB) |
| `a_tester_sur_imc_live/live_alpha_probes/` | 17 diagnostic probes for live alpha discovery |
| `locked/` | Older locked candidates (HYDRO + velvet_options + combined) |
| `options_research/` | Options-specific research artifacts |
| `theo/` | Theo-integrated submissions (v50/v51/v52/v57/v58) |
| `tibo/` | Tibo-integrated submissions (v61/v62) |
| `_experimental/` | All other experimental .py from round 3 development |

## 🎯 Live IMC results (chronological)

| Probe / Strategy | Live PnL | Notes |
|---|---:|---|
| 00A baseline far quotes | +760 | OK |
| 00B gap+flow follow | -3,275 | flow-follow toxic on VEV_4000 |
| 00C option flow fade | -587 | similar |
| 03/04/05 dynamic skew | +1,134 | dynamic skew package validated |
| 14 IV momentum | +1,023 | OK |
| core_v1 (Codex full) | -2,761 | HYDROGEL aggressive = toxic in live |
| log_best_hydro (v7b) | -3,109 | HYDRO standalone = -3k in first 10% of day 2 |
| balanced v58 | +2,003 | velvet+options first live positive ! |
| **FINAL ROUND 3** | **+64,195** | full session, fresh data, all systems working |

## Key learnings

1. **Live data is fresh** (not = day 2 first 10%). The earlier match was coincidental.
2. **HYDROGEL is toxic when aggressive in live** (-5.39 markout × 5827 trades) but the strategy survived via diversification.
3. **VEV_4000-5100 worked normally in live** despite some backtest fill-model issues showing 0 trades on VEV_5100.
4. **VELVET dropped -96 ticks mid-session** (V-shape): 5295 → 5199 → 5232. Long-only options absorbed the drawdown.
5. **Top teams probably did 100-150k** by hedging delta on options or going vega-neutral. We ran fully directional long.

## For Round 4

- Reduce HYDROGEL sizing further (was 0.15 base_pct, try 0.05 or pure passive)
- Add delta hedging if option strikes available (cancel directional risk)
- Consider vega-neutral pair MM
- Keep R3GuardedAnchor on VELVET (validated +5.78 markout in passive mode)
- Reuse Tibo's 2-sided MM for far OTM (avoid stuck-long inventory)
