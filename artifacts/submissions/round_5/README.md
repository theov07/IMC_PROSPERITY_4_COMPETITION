# R5 Submissions — Quick guide

## TL;DR

Tu as **10+ submissions exportées**. Choisis selon ton appétit pour le risque :

| Risque | Submission | bt 3-day | EV (P=0.5) | Use case |
|---|---|---:|---:|---|
| 🟢 Safe | `r5_v25_thresh125_round5_submission.py` | **546k** | 642k | Si live regime ≈ backtest |
| 🟢 Safe | `r5_v14b_pair_skip_curated_round5_submission.py` | 534k | 636k | Original champion |
| 🟡 Mid | `r5_v50_thresh125_drop_flipped_round5_submission.py` | 491k | 899k | Drop 4 + thresh tuning |
| 🟡 Mid | `r5_v60_drop_extra_round5_submission.py` | 478k | 971k | Drop 6 |
| 🔴 Bold | `r5_v29_drop_broad_round5_submission.py` | 369k | 990k | Drop 10 |
| 🔴 Bold | `r5_v61_drop_broad_thresh125_round5_submission.py` | 376k | 994k | Drop 10 + thresh=1.25 |
| 🔴 Bold | `r5_v72_consistent_only_round5_submission.py` | 342k | 1024k | Keep only live winners |
| 🔴🔴 **MAX EV** | **`r5_v200_optimal_p50_round5_submission.py`** | 370k | **1031k** | ★ Math-optimal at P=0.5 |

## Math behind the choices

For each backtest variant, we computed:
- `bt`: 3-day backtest PnL (--match-trades realistic)
- `live_3d`: extrapolated PnL if live regime continues (live × 30 to scale 999 ticks → 30k ticks)
- `EV(P)`: expected value at P(regime continues), `(1-P)*bt + P*live`

**Mathematical optimum at given P**:
- Drop product i iff `P > bt_i / (bt_i - live_i)` (when bt_i > live_i)

This identified 11 products to drop at P=0.5 (v200) — but v72's "all live winners" rule
gives essentially the same result.

## Decision framework

**Step 1**: How much do you trust the live signal?

The live log (550081) shows specific products LOSING in IMC's live environment despite winning
in backtest. The aggregate live PnL is *higher* than backtest aggregate PnL (38% higher), but
the distribution shifted dramatically. Several products went from +18k bt to -7k live.

This is consistent with a regime change.

**Step 2**: Pick P based on conviction.

- P=0.3 (regime mostly reverts): use v25 (max bt)
- P=0.5 (uncertain): use v200 (mathematically optimal at this P)
- P=0.7 (regime continues): use v201 or v72 (both nearly optimal here)
- P=1.0 (full bullish on live): use v72

**Step 3**: Upload via IMC interface.

All submissions are validated by `scripts/export_submission.py` (syntax, banned imports,
latency benchmark < 900ms, run-tick-0 produces orders).

## My personal recommendation

**Submit `r5_v200_optimal_p50_round5_submission.py`** — mathematically optimal at P=0.5.

Why v200 vs v72 :
- v200 keeps 27 products (drops only 11 with negative bt+live at P=0.5)
- v72 was over-pruning (kept 25, dropped products that should have been kept)
- v200 has higher bt (370k vs 342k) AND similar live extrap (1691k vs 1708k)
- EV(P=0.5): v200 = 1031k > v72 = 1025k

Drop set in v200: PLANETARY_RINGS, ROBOT_DISHES, DARK_MATTER, MORNING_BREATH, PANEL_2X2,
ROBOT_LAUNDRY, MICROCHIP_RECTANGLE, UV_VISOR_AMBER, PANEL_1X4, SNACKPACK_RASPBERRY, PEBBLES_XL.

Backup option: `r5_v25_thresh125_round5_submission.py` if you'd rather play safe (max bt).

## See also

- `../analysis/round_5/R5_FINDINGS.md` — full findings + structural analysis
- `../analysis/round_5/R5_TODO.md` — TODO list with all ideas
- `../analysis/round_5/R5_NIGHT_REPORT.md` — what was done overnight
- `SUBMIT_THIS.md` — quick decision guide
