# VELVET/options live candidates

## TIER 1 — Theo v7 integrated (NEW DEFAULTS, post-toxic-flow + passive-unwind)

These dominate all earlier candidates by +50-70k PnL.

| File | 3d PnL | DD | Ratio | Profile |
|---|---:|---:|---:|---|
| `00_TOP0_LOWEST_DD__v52_theo_minimal__pnl148k_dd59k_ratio249.py` | +147,679 | -59,356 | 2.488 | Lowest DD (no toxic flow / no unwind) |
| `00_TOP1_BEST_RATIO__v57_v7_passive_unwind__pnl156k_dd60k_ratio261.py` ★ | +156,010 | -59,720 | 2.612 | **DEFAULT** — best ratio, dominates v53 |
| `00_TOP2_BALANCED__v58_v7_with_5300__pnl159k_dd62k_ratio255.py` | +158,696 | -62,165 | 2.553 | + VEV_5300, dominates v54+v56 |

### Win story per VELVET enhancement

| Layer | VELVET PnL | DD | Ratio |
|---|---:|---:|---:|
| Pre-Theo (v34 baseline) | 27,518 | 19,980 | 1.58 |
| + R3GuardedAnchorMM (v52) | 76,016 | 15,929 | 4.77 |
| + Toxic flow (v53) | 78,238 | 17,130 | 4.57 |
| **+ Passive unwind (v57) ★** | **86,518** | 19,056 | 4.54 |

Total VELVET-only gain: **+59,000 PnL**, ratio kept > 4.5.

### Sensitivity (anti-overfit on `passive_unwind_trigger`)

Tested triggers 0.30 / 0.38 / 0.40 / 0.50 → all give +5.9k to +6.4k boost (range 508 PnL = 0.3%). The IDEA is robust, the magic number doesn't matter.

## TIER 0 — Pre-Theo candidates (kept as fallback)

| File | 3d PnL | DD | Ratio | Profile |
|---|---:|---:|---:|---|
| `01_LOWEST_DD__v46_vega_weighted__pnl77k_dd40k_ratio194.py` | +77,492 | -39,882 | 1.94 | Lowest DD if R3 guard logic seems overfit live |
| `02_PARETO_BALANCED__v38_drop_bad__pnl86k_dd45k_ratio190.py` | +86,451 | -45,494 | 1.90 | Pre-Theo proven |
| `03_FULL_OPTIONS__v34_combined__pnl89k_dd47k_ratio189.py` | +88,658 | -46,889 | 1.89 | Pre-Theo |
| `04_MAX_PNL_SAFE__v24_r2velvet_zskip__pnl92k_dd50k_ratio182.py` | +91,560 | -50,200 | 1.82 | Pre-Theo (proven) |
| `05_MAX_PNL_STRETCH__v12_r2velvet__pnl95k_dd60k_ratio156.py` | +94,614 | -60,508 | 1.56 | Pre-Theo |

## Decision rules

**Default upload** → `00_TOP1_BEST_RATIO__v57_v7_passive_unwind` ★

**Want max PnL** → `00_TOP2_BALANCED__v58_v7_with_5300` (+2.7k PnL for +2.5k DD vs TOP1)

**If R3 guard logic seems overfit live** → fall back to `02_PARETO_BALANCED__v38` (no guard, no toxic flow)

## Live alpha caveat from probe runs (00A/00B/00C)

Adverse-selection analysis on first 3 live probes revealed:
- **VEV_4000 has 95-100% adverse-selection rate live in BOTH follow and fade modes** (was BT-positive +45k)
- **HYDROGEL_PACK** has +5.78 avg signed_mtm (works in live, but our scope is velvet+options only)
- No named participants visible

If VEV_4000 turns out toxic in live for our v57/v58 too, fall back to `01_LOWEST_DD v46_vega_weighted` which has VEV_4000 at smaller size.

All files validated for IMC sandbox (banned-import check + size < 110KB + tick latency).
HYDROGEL_PACK is disabled in all velvet+options files.
