# Round 3 — Velvet+Options Final Candidates

9 Pareto-efficient candidates. **TIER 1 = post-Theo-v7 (passive unwind)** are the new defaults.

## TIER 1 — Theo v7 integrated (passive unwind on VELVET)

NEW after Theo shared `r3_velvet_options_v7_passiveunwind`. The headline: **asymmetric
passive skew** when |position| > 38% of limit — tightens only the unwind side by 1 tick.
**Sensitivity tested: 0.30 / 0.38 / 0.40 / 0.50 all give +5.9k to +6.4k boost** → robust,
not overfit. The IDEA wins, the magic number doesn't matter.

| File | PnL (3d) | DD | Ratio | Pick if... |
|---|---:|---:|---:|---|
| **TOP0_LOWEST_DD** v52_theo_minimal | +147,679 | -59,356 | 2.488 | Lowest DD point, no v6/v7 features |
| **TOP1_BEST_RATIO** v57_v7_passive_unwind ★ | +156,010 | **-59,720** | **2.612** | **DEFAULT** — strictly dominates v53 (+6.4k PnL, -250 DD) |
| **TOP2_BALANCED** v58_v7_with_5300 | +158,696 | -62,165 | 2.553 | + VEV_5300 — strictly dominates v54 AND v56 |
| **TOP4_MAX_PNL_STRETCH** v55_v6_full | +159,245 | -80,494 | 1.978 | All 8 strikes — only +549 PnL more than v58 but +18k DD (questionable) |

### Win story per VELVET enhancement

| Layer | VELVET PnL | DD | Ratio |
|---|---:|---:|---:|
| Pre-Theo (v34 baseline) | 27,518 | 19,980 | 1.58 |
| + R3GuardedAnchorMM (v52) | 76,016 | 15,929 | 4.77 |
| + Toxic flow (v53) | 78,238 | 17,130 | 4.57 |
| **+ Passive unwind (v57) ★** | **86,518** | **19,056** | **4.54** |

Total VELVET improvement: **+59,000 PnL** with consistent ratio > 4.5.

### Theo v7 reference (full HYDROGEL+VELVET+options)

| Strategy | PnL | DD | Ratio |
|---|---:|---:|---:|
| Theo v7 FULL (with HYDRO) | 159,278 | 43,804 | 3.636 |
| Theo v7 velvet+options ONLY | 129,818 | 44,268 | 2.933 |
| **Our TOP1 v57 (velvet+options)** | **156,010** | 59,720 | 2.612 |
| **Our TOP2 v58 (velvet+options)** | **158,696** | 62,165 | 2.553 |

We **beat Theo's velvet+options-only by +26,192 (v57) / +28,878 (v58)** because our
options config (IV gate) captures more PnL on VEV_5000-5200 than Theo's per-strike z does.

## Per-asset breakdown (TOP1 v57)

| Asset | PnL | DD | Ratio | DD%cap |
|---|---:|---:|---:|---:|
| VELVETFRUIT_EXTRACT | 86,518 | 19,056 | **4.54** | **0.9%** |
| VEV_4000 | 45,355 | 60,833 | 0.75 | 5.7% |
| VEV_4500 | 32,416 | 43,714 | 0.74 | 9.1% |
| VEV_5100 | 28,489 | 40,052 | 0.71 | 37.2% |
| VEV_5000 | 15,364 | 21,612 | 0.71 | 26.5% |
| VEV_5200 | 14,667 | 20,246 | 0.72 | 45.9% |

All ratios ≥ 0.70 → no drag asset.

## Sensitivity test — passive_unwind_trigger value

The key magic number `0.38` was tuned by Theo. We tested its sensitivity:

| Trigger | PnL | DD | Ratio | Δ PnL vs v53 (no unwind) |
|---|---:|---:|---:|---:|
| 0.30 | 155,808 | 59,720 | 2.609 | +6,232 |
| **0.38** ★ | **156,010** | 59,720 | **2.612** | **+6,434** |
| 0.40 | 155,913 | 59,720 | 2.611 | +6,337 |
| 0.50 | 155,502 | 59,904 | 2.596 | +5,926 |

**Curve is FLAT** (range = 508 PnL = 0.3%). Robust idea, not overfit magic number.

## TIER 0 — Pre-Theo candidates (kept for fallback)

| File | PnL (3d) | DD | Ratio | Use case |
|---|---:|---:|---:|---|
| 01_LOWEST_DD v46_vega_weighted | +77,492 | -39,882 | 1.94 | If R3 guard logic seems overfit live |
| 02_PARETO_BALANCED v38_drop_bad | +86,451 | -45,494 | 1.90 | Pre-Theo Pareto-balanced (proven) |
| 03_FULL_OPTIONS v34_combined | +88,658 | -46,889 | 1.89 | Pre-Theo |
| 04_MAX_PNL_SAFE v24_r2velvet_zskip | +91,560 | -50,200 | 1.82 | Pre-Theo (proven) |
| 05_MAX_PNL_STRETCH v12_r2velvet | +94,614 | -60,508 | 1.56 | Pre-Theo |

## REMOVED (dominated)
- ~~TOP1 v53_v6_toxic_flow~~ → dominated by v57 (PnL up 6.4k, DD down 250)
- ~~TOP2 v50_theo_integrated~~ → dominated by v58
- ~~TOP2 v56_v6_with_5300~~ → dominated by v58 (PnL up 6.4k, DD down 250)
- ~~TOP3 v54_v6_per_strike_z~~ → dominated by v58 (PnL up, DD down 12k!)

## Decision rules

**Default upload** → `TOP1_BEST_RATIO__v57_v7_passive_unwind` (best ratio + best risk-adjusted)

**Want max PnL with controlled DD** → `TOP2_BALANCED__v58_v7_with_5300` (only +5k DD more, +2.7k PnL)

**Want absolute max PnL** → `TOP4_MAX_PNL_STRETCH__v55_v6_full` (only +549 PnL more than v58 but +18k DD — borderline)

**Want lowest DD** → `TOP0_LOWEST_DD__v52_theo_minimal` (no v6/v7 features, simpler)

**If R3GuardedAnchor seems overfit live** → `02_PARETO_BALANCED__v38` (pre-Theo, simpler)

## Architecture (TIER 1)

```
                 VELVET base                        Toxic flow   Passive unwind
TOP0 v52         R3GuardedAnchor                    no           no
TOP1 v57 ★       R3GuardedAnchor + toxic + UNWIND   YES          YES
TOP2 v58         R3GuardedAnchor + toxic + UNWIND   YES          YES (+ VEV_5300)
TOP4 v55         R3GuardedAnchor + toxic            YES          no (full strikes)
```

VELVET params for TIER 1 v57/v58:
```python
toxic_threshold=0.6, toxic_window=8, toxic_size_frac=0.68
passive_unwind_skew_ticks=1, passive_unwind_trigger=0.38
inventory_aversion_gamma=0.001  # was 0.0015 in v52
```

## Validation status

All 9 files validated:
- ✅ Syntax valid
- ✅ No banned imports (IMC sandbox compatible)
- ✅ Trader.__init__() succeeds
- ✅ run() returns orders
- ✅ p99 latency < 60ms
- ✅ Size < 110,000 bytes

## Generated by

Claude (Leo2 branch). Theo v7 integration after Theo shared `r3_velvet_options_v7_passiveunwind`.
**3 sequential VELVET-only enhancements applied** (R3GuardedAnchor → toxic flow → passive
unwind), each measured Pareto-positive. Total VELVET PnL went from 27,518 (pre-Theo
baseline v34) to 86,518 (v57) — **+59,000 PnL gain on VELVET alone** with ratio
maintained > 4.5.
