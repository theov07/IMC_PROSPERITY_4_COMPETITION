# HYDROGEL live candidates

## Tier 1 — POST-Theo-v7 enhancements (NEW 2026-04-26)

| File | 3d PnL | DD | Ratio | Profile |
|---|---:|---:|---:|---|
| **`01_HYDRO_BEST_CLEAN_v7__anchor_max3d_v7__pnl92k_dd19k_ratio486.py`** ★ | **+91,684** | **-18,872** | **4.858** | **NEW DEFAULT** — Theo v7 layers (toxic flow + passive unwind) added to max3d. +4,846 PnL with -104 DD vs base, all 3 days uniformly improved. Pareto win, NO overfit signs. |
| `03_HYDRO_MAX_PNL_STRETCH_v7__guarded_v7__pnl103k_dd20k_ratio523_OVERFIT_WARNING.py` | +103,145 | -19,705 | 5.234 | ⚠️ **OVERFIT WARNING**: R3GuardedAnchor regime detector. D0 explodes (+18k vs base) but D2 regresses (-4k). Pattern is non-uniform — possible regime-overfit on day 0. Only pick if confident in similar live regime. |

## Tier 0 — Previous candidates (kept)

| File | 3d PnL | DD | Profile |
|---|---:|---:|---|
| `01_HYDRO_BEST_CLEAN__anchor_max3d__pnl86k_dd19k.py` | +86,838 | -18,976 | Original clean max3d (pre-v7) — fallback |
| `02_HYDRO_RISK_ADJUSTED__hydrogel_smart__pnl29k_dd3k.py` | +28,856 | -2,652 | Lower PnL, much cleaner DD fallback |

## Decision rules

**Default upload** → `01_HYDRO_BEST_CLEAN_v7__anchor_max3d_v7` ★ (pure Pareto upgrade, no overfit signs)

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
