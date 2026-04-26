# Live alpha probes

Diagnostic submissions for IMC live tests. These are not the default scoring
picks. They are designed around event features: book gaps, off-market fills,
skew deformation, IV residual momentum, and signed market-trade flow.

Assumption for interpretation: current IMC live appears close to the first
10 percent of day 2, but these submissions do not hard-code day/timestamp
rules. Use that similarity only to pick which event hypotheses to test first.

## Probe matrix

| File | What it tests | Risk / note |
|---|---|---|
| `00A_BASKET_ALL_PRODUCTS_FAR_QUOTES__first_live_probe.py` | Off-market/far passive fills across HYDRO, VELVET, and all VEV strikes 4000..6500 | Best first discovery run; broad coverage, no timestamp overfit |
| `00B_BASKET_ALL_PRODUCTS_GAP_FLOW_FOLLOW.py` | Thin L1/L2 gap + flow-follow across HYDRO, VELVET, and all VEV strikes | Tests gap exploit and informed flow in one run |
| `00C_BASKET_ALL_OPTIONS_FLOW_FADE.py` | Flow-fade/OA hypothesis across all VEV strikes 4000..6500 | Pair with `00B` to compare follow vs fade on options |
| `01_PASSIVE_SKEW_SIGNAL__pnl12k__probe_smile_residual.py` | Passive leave-one-out smile residual | Low-risk, low fill intensity |
| `02_SKEW_TAKER_TOXICITY_TEST__bt_minus45k__probe_adverse_selection.py` | Whether aggressive skew takers are toxic or live-only profitable | Risky, backtest about -45k |
| `03_DYN_SKEW_AUTO__v15__probe_informed_vs_oa.py` | Dynamic skew detector, auto follow/fade | Tests informed-vs-OA classifier |
| `04_DYN_SKEW_FOLLOW__v16__probe_informed_flow.py` | Treat skew deformation as informed | Isolates follow sign |
| `05_DYN_SKEW_FADE__v17__probe_uninformed_flow.py` | Treat skew deformation as uninformed/OA | Isolates fade sign |
| `06_OLD_OPTIONS_ALPHA__pnl13k__baseline_probe.py` | Early VELVET/options alpha baseline | Sanity baseline |
| `07_LIVE_VELVET_FAR_QUOTES__offmarket_fill_probe.py` | Far passive fills on VELVET, including startup depth ladder | Tests R1/R2-style off-market fills |
| `08_LIVE_VELVET_FLOW_FOLLOW__informed_trader_probe.py` | Follow signed VELVET market-trade flow | Tests informed trader hypothesis |
| `09_LIVE_HYDRO_FAR_QUOTES__offmarket_fill_probe.py` | Far passive fills on HYDRO | Optional HYDRO diagnostic |
| `10_LIVE_OPTIONS_FAR_QUOTES__offmarket_fill_probe.py` | Far passive fills on VEV_4000..5400 | Tests whether options fill away from official market |
| `11_LIVE_OPTIONS_GAP_SWEEP__thin_l1_probe.py` | Take thin L1 when L1-L2 gap is wide | Tests option gap exploit |
| `12_LIVE_OPTIONS_FLOW_FOLLOW__informed_trader_probe.py` | Follow signed option market-trade flow | Tests informed option flow |
| `13_LIVE_OPTIONS_FLOW_FADE__uninformed_oa_probe.py` | Fade signed option market-trade flow | Tests uninformed/OA flow |
| `14_LIVE_IV_MOMENTUM__v28_conservative_minified.py` | IV residual momentum on high strikes | Under 100 KB after minify |
| `15_LIVE_IV_MOMENTUM__v29_aggro_minified.py` | Aggressive IV residual momentum | Under 100 KB after minify, higher risk |
| `16_LIVE_VOL_HARVEST_UNHEDGED__realized_vs_implied.py` | Realized vol vs implied vol, unhedged | Long-vol probe, about +14.7k backtest |
| `17_DIAGNOSTIC_PARTICIPANT_AND_ADVERSE.py` | Track named buyer/seller (G1) + adverse selection 5 ticks post-fill (G2) on ALL 12 products | Built after analyzing 00A/00B/00C live logs. Logs `adverse_rate`, `avg_signed_mtm`, `last_buyer_hash`, `last_seller_hash`, `session_phase`. Trades minimally (1 lot every 200 ticks far from mid), so PnL ≈ 0; goal is signal collection, not score. |

## Findings from first live runs (00A/00B/00C — 2026-04-26)

Analysis of `tradeHistory` + 5-tick post-fill mid moves revealed these **adverse selection rates per product**:

| Product | 00A baseline | 00B follow | 00C fade | Verdict |
|---|---:|---:|---:|---|
| **HYDROGEL_PACK** | **+5.78** ✅ | +5.78 ✅ | n/a | Anchor strategy works in live, ADD to portfolio |
| VELVET | +0.50 ✅ | -2.24 ❌ | n/a | Baseline OK, flow follow toxic |
| **VEV_4000** | n/a | **-9.52 (95% adverse)** | **-11.43 (100% adverse!)** | TOXIC IN BOTH DIRECTIONS — different live structure |
| VEV_5300/5400/5500 | n/a | -0.6 to -1.2 | -0.5 to -1.0 | Far OTM = always lose half-spread |
| VEV_6000/6500 | -0.50 (all adv) | -0.50 | -0.50 | Pay full spread on every fill |

**Implications**:
- **00B losing -3,275** ← gap+flow follow on VEV_4000 is the main loss driver
- **VEV_4000 is differently structured in live** vs backtest (gamma_scalp_zgated works in BT, fails LIVE)
- **HYDROGEL is genuinely profitable in live** → should be added to default upload (not just velvet+options)
- No named participants appeared yet → G1 still useful as future-proof logging

## Recommended upload order

1. Score/default: upload `../velvet_et_options/02_PARETO_BALANCED__v38_drop_bad__pnl86k_dd45k_ratio190.py`.
2. First broad alpha probe: upload `00A_BASKET_ALL_PRODUCTS_FAR_QUOTES__first_live_probe.py`.
3. If far/off-market fills happen: upload `00B_BASKET_ALL_PRODUCTS_GAP_FLOW_FOLLOW.py`.
4. If option flow is active: compare `00B` versus `00C_BASKET_ALL_OPTIONS_FLOW_FADE.py`.
5. Use isolated probes `07`..`13` only to confirm which product family produced the signal.
6. If skew is visibly deforming: upload `03_DYN_SKEW_AUTO...`, then isolate with `04` or `05`.
7. If the live path shows persistent IV residual drift: test `14`, then `15`.
8. Use `02_SKEW_TAKER...` only as a risky toxicity check.
9. **For broad live diagnostics**: upload `17_DIAGNOSTIC_PARTICIPANT_AND_ADVERSE.py` — covers all 12 products, ~0 PnL, logs adverse selection rate per product so we can decide which products to disable in production.

## Coverage notes

- `00A` and `00B` cover every Round 3 product in one upload.
- `00C` covers all option strikes, but intentionally disables HYDRO/VELVET because it tests the option-only OA/fade sign.
- `10`..`13` were kept as narrower option-only variants if we need a cleaner attribution run.
