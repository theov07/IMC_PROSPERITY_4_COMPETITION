# 🚀 R5 SUBMISSION GUIDE — Quick Decision

## Mon top pick : `r5_v200_optimal_p50_round5_submission.py`

**Pourquoi** : 
- bt 370k | live extrapolated 1.69M | EV (50/50) = **1,031k**
- Mathématiquement optimal au P=0.5 (drop product i iff P > bt_i/(bt_i-live_i))
- Drops les 11 produits avec break-even probability < 0.5
- Higher EV than v72 (1,024k) AND higher floor too (370k vs 342k)

**Risk profile** :
- Worst case (P=0): 370k (vs v25's 546k = -176k worse)
- Best case (P=1): 1,691k (vs v25's 738k = +953k better)
- DD 3-day: 34k (~9.6% of PnL)

**Drop set** (11 products with bt+live < 0):
PLANETARY_RINGS, ROBOT_DISHES, DARK_MATTER, MORNING_BREATH, PANEL_2X2,
ROBOT_LAUNDRY, MICROCHIP_RECTANGLE, UV_VISOR_AMBER, PANEL_1X4, SNACKPACK_RASPBERRY, PEBBLES_XL

## Si tu préfères jouer safe : `r5_v25_thresh125_round5_submission.py`

**Pourquoi** : 546k bt = backtest record. Aucun bet sur le régime.

## Si tu préfères un compromis : `r5_v50_thresh125_drop_flipped_round5_submission.py`

bt 491k, EV 899k. Pareto-improved over v28.

## Décision à prendre

À P (regime continues) :
- < 0.30 → v25 (no defensive)
- 0.30-0.40 → v50 ou v60
- > 0.40 → v72 ou v61

Donné évidence live, **P >= 0.5** est raisonnable. **=> v72 ou v61**.

## Quick reference

| Submission | bt | live_3d | EV(P=0.5) | n_active |
|---|---:|---:|---:|---:|
| **v200_optimal_p50** ★★ | 370k | 1,691k | **1,031k** | 27 |
| v203_optimal_p60 | 363k | 1,698k | 1,030k | 26 |
| v300_v200_keep_pebbles_xl | 410k | 1,642k | 1,026k | 28 |
| v72_consistent_only | 342k | 1,708k | 1,024k | 25 |
| v61_drop_broad_thresh125 | 376k | 1,612k | 994k | 28 |
| v60_drop_extra | 478k | 1,463k | 971k | 32 |
| v50_thresh125_drop_flipped | 491k | 1,307k | 899k | 34 |
| v28_drop_flipped | 479k | 1,307k | 893k | 34 |
| **v25_thresh125** ★ | 546k | 738k | 642k | 38 |
| v14b_pair_skip_curated | 534k | 738k | 636k | 38 |
| v2_winners_only | 515k | 738k | -- | 38 |
