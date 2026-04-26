# HYDROGEL live candidates

## Tier 1 — POST-Theo-v7 enhancements (NEW 2026-04-26)

| File | 3d PnL | DD | Ratio | CV% | Profile |
|---|---:|---:|---:|---:|---|
| **`01_HYDRO_BEST_v7b__guarded_loose__pnl100k_dd19k_ratio523.py`** ★ | **+99,541** | **-19,030** | **5.23** | **18.2%** | **NEW DEFAULT** — guarded_v7 with PERMISSIVE guard (reversion_threshold=3.0 vs 7.5). Captures most of guarded_v7's D0 boost (+12k vs base) without losing D2 (-1.8k vs guarded_v7's -4k). MOST UNIFORM PnL distribution of all variants tested. |
| `01_HYDRO_BEST_CLEAN_v7__anchor_max3d_v7__pnl92k_dd19k_ratio486.py` | +91,684 | -18,872 | 4.86 | 29.5% | Pure microstructure (toxic+unwind, no guard). Safest fallback if guard logic seems fragile in live. |
| `03_HYDRO_MAX_PNL_STRETCH_v7__guarded_v7__pnl103k_dd20k_ratio523_OVERFIT_WARNING.py` | +103,145 | -19,705 | 5.23 | 23.0% | ⚠️ **OVERFIT WARNING**: full guarded_v7. D0 explodes (+18k vs base) but D2 regresses (-4k). Only pick if confident in similar live regime. |

## Tier 0 — Previous candidates (kept)

| File | 3d PnL | DD | Profile |
|---|---:|---:|---|
| `01_HYDRO_BEST_CLEAN__anchor_max3d__pnl86k_dd19k.py` | +86,838 | -18,976 | Original clean max3d (pre-v7) — fallback |
| `02_HYDRO_RISK_ADJUSTED__hydrogel_smart__pnl29k_dd3k.py` | +28,856 | -2,652 | Lower PnL, much cleaner DD fallback |

## Decision rules

**Default upload** → `01_HYDRO_BEST_v7b__guarded_loose` ★ (best PnL among non-overfit, lowest CV at 18.2%, +12.7k vs base, +7.9k vs max3d_v7)

**Conservative pure-microstructure fallback** → `01_HYDRO_BEST_CLEAN_v7__anchor_max3d_v7` (no guard logic at all, just toxic+unwind)

**If you want max PnL with regime risk** → `03_HYDRO_MAX_PNL_STRETCH_v7__guarded_v7` (warning: D2 regresses, fragile)

**Risk-averse fallback** → `02_HYDRO_RISK_ADJUSTED__hydrogel_smart` (29k PnL but DD only 2.6k)

## What's new in v7

Both new candidates add to `r3_hydro_anchor_max3d` base:
- `toxic_threshold=0.6, toxic_window=8, toxic_size_frac=0.68` — shrink wrong-side quote when market trades show 60%+ directional imbalance
- `passive_unwind_skew_ticks=1, passive_unwind_trigger=0.38` — tighten unwind side passive when |pos|/limit > 38%
- `inventory_aversion_gamma=0.001` (vs 0.0015) — looser fair-value shift since unwind handles inventory
- `pct_kept_for_takers=0.005` (vs 0.05) — more aggressive taker reserve

`guarded_v7` adds on top:
- `strategy=r3_guarded_anchor_mm` — only use anchor pull when (near_anchor OR reverting) AND not wrong-way inventory
- Same guard params as VELVET (alpha=0.45, threshold=7.5, inventory_dist=40, max_dist=80)

Live-evidence (from probe runs 00A/00B/00C): HYDROGEL has +5.78 avg signed_mtm in live →
the anchor strategy works in live conditions. v7 enhancements are pure microstructure
upgrades that should generalize.

Not included here: day2 oracle / timestamp / replay variants. They remain useful for
research, but this folder is for live-upload candidates.
