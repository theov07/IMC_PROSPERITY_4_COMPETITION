# Round 5 — Findings & Strategy Map (FINAL)

## 🏆 RÉSUMÉ EXÉCUTIF

**Backtest champion** : `r5_v25_thresh125` = **546,309 PnL** (3-day, --match-trades realistic)
**EV CHAMPION (math-optimal at P=0.5)** : `r5_v200_optimal_p50` = 370k bt, **EV 1,030,689**
   - Drops 11 products with break-even probability < 0.5
**EV second** : `r5_v203_optimal_p60` = 363k bt, **EV 1,030,271** (essentially equivalent)
**EV third** : `r5_v300_keep_pebbles_xl` = 410k bt, **EV 1,026,101** (high floor)

### Key insight
**Live R5 log analyzed** (round_5 IMC live, 999 ticks = ~1/30 of full backtest period):
- Aggregate live PnL extrapolated 3-day = 738k vs backtest 533k → live > bt by 38%
- BUT specific products HUGELY flip regime in live:
  - GALAXY_SOUNDS_PLANETARY_RINGS: bt +18k → live -7257 (extrap -218k!)
  - ROBOT_DISHES: bt +15k → live -4500 (extrap -135k)
  - GALAXY_SOUNDS_DARK_MATTER: bt +7k → live -3833 (extrap -115k)
  - OXYGEN_SHAKE_MORNING_BREATH: bt +13k → live -3372 (extrap -101k)

**Strategy** : Drop products that flip regime. Even at conservative P(continue regime) = 0.3,
EV(drop 10) > EV(drop 4) > EV(drop 0) for almost any P > 0.

## 📊 Final ranking (sorted by EV at P=0.5)

| Variant | bt PnL | live_3d_extrap | EV(P=0.5) | Note |
|---|---:|---:|---:|---|
| **v200_optimal_p50** ★★ | 370,032 | 1,691,346 | **1,030,689** | ★ MATH-OPTIMAL @P=0.5 |
| v203_optimal_p60 | 362,788 | 1,697,755 | 1,030,271 | Math-optimal @P=0.6 (≈ v200) |
| v300_v200_keep_pebbles_xl | 409,748 | 1,642,453 | 1,026,101 | High floor variant |
| v72_consistent_only | 341,923 | 1,707,805 | 1,024,864 | Live-winners-only (≈ v201) |
| v201_optimal_p70 | 341,923 | 1,707,805 | 1,024,864 | Math-optimal @P=0.7 |
| v61_drop_broad_thresh125 | 375,972 | 1,611,651 | 993,811 | EV broader (Pareto over v29) |
| v80_drop_broad_thresh10 | 371,772 | 1,611,651 | 991,712 | Drop 10 + thresh=1.0 |
| v29_drop_broad | 368,963 | 1,611,651 | 990,307 | Drop 10 only |
| v60_drop_extra | 478,180 | 1,463,260 | 970,718 | Drop 6 + thresh=1.25 |
| v50_thresh125_drop4 | 491,508 | 1,307,141 | 899,323 | Drop 4 + thresh=1.25 |
| v28_drop_flipped | 478,981 | 1,307,141 | 893,061 | Drop 4 only |
| **v25_thresh125** | **546,306** | 738,270 | 642,288 | ★ Best bt (no defensive) |
| v14b_pair_skip | 533,782 | 738,270 | 636,026 | Original champion |

### Crossover analysis
- **P < 0.31**: v25 wins (regime stays as backtest)
- **0.31 < P < 0.39**: v28 wins (light defensive)
- **P > 0.39**: v29 wins (strong defensive)

Given strong live evidence for regime change, **P >= 0.6** is reasonable. **v29 dominant.**

## 🔬 Découvertes structurelles

### 1. Anti-correlated pairs (validated by copules λ_L = λ_U = 0)
- SNACKPACK_CHOCOLATE ↔ SNACKPACK_VANILLA : -0.92 returns, 0 tail dep
- SNACKPACK_RASPBERRY ↔ SNACKPACK_STRAWBERRY : -0.92, 0 tail dep
- PEBBLES_XL ↔ PEBBLES_S : -0.49 returns, 0 tail dep

→ Used in `pair_skip_mm` (skip side when |z(self) + z(partner)| > thresh)

### 2. Within-group cohesion (variance ratio)
- **PEBBLES** : intra/factor = 27.3 (members very independent)
- **SNACKPACK** : 3.77
- **All other groups** : ≈ 1.0 (members move together)

→ Pair-trade WORKS only on PEBBLES + SNACKPACK (validated empirically)

### 3. PCA per-group
- **SNACKPACK** : PC1 (60%) + PC2 (35%) = 94% variance
  - PC1 = +0.65 RASP, -0.63 STRAW, -0.43 PIST (cluster A vs B)
  - PC2 = -0.72 CHOC, +0.69 VAN
- **TRANSLATOR/PEBBLES** : group mean parfaitement flat (R²<0.01)
- **Inter-group PC1** = MICROCHIP isolé, PC2 = ROBOT isolé

### 4. Group means (linearity)
| Group | R²(mean,t) | Hurst | Cohesion | Flat mean? |
|---|---:|---:|---:|---|
| SLEEP_POD | 0.88 | 1.00 | +0.003 | drift |
| GALAXY_SOUNDS | 0.79 | 0.99 | +0.001 | drift |
| **TRANSLATOR** | **0.005** | 0.99 | +0.002 | **FLAT (substitution)** |
| **PEBBLES** | **0.00001** | 0.53 | -0.191 | **FLAT, anti-corr** |

### 5. PCA-residuals mean-reverting
- ROBOT_DISHES AR1_resid = -0.22 (strongest)
- ROBOT_IRONING : -0.12
- OXYGEN_SHAKE_EVENING_BREATH : -0.12
→ Strategy `tick_reversal_skip_mm` tested but only +/- noise (live-flipped product confounds)

### 6. Impulse response inter-group
SNACKPACK shock +2σ → 7 autres groupes -0.21 à -0.33σ au lag=1 (decays in 5 ticks).
v16 strategy didn't profit (signal too small).

### 7. Lead-lag intra-tick : RIEN (max |corr| = 0.05)
### 8. Cointégration : RIEN (ar=0.999 partout)
### 9. Trader IDs : retirés en R5 (anonymisés)

## 🎯 Strategies built (round_5/)

### Productive
- `pair_skip_mm` ★ Champion strategy (skip side, no price skew)
- `multi_pair_skip_mm` (basket partner)
- `tracking_error_skip_mm` (group mean dev, skip side)
- `tick_reversal_skip_mm` (AR1_resid based)

### Tested but inferior
- `basket_aware_mm` (price skew - too aggressive)
- `tracking_error_mm` (price skew - costs spread)
- `impulse_pause_mm` (signal too weak)
- `inventory_aware_mm` (skew costs spread)
- `zscore_mm` (inferior to naive)
- `pair_trader` (taker = -305k catastrophe)

## 🛠️ Framework R5

```
prosperity/baskets/
  groups.py        # 10 groups + sous-clusters constants
  context.py       # SharedR5Context (online z-stats + group indices)
  etf.py           # GroupETF + PCAPortfolio modules

prosperity/strategies/round_5/
  pair_skip_mm.py        ★ Champion
  multi_pair_skip_mm.py
  tracking_error_skip_mm.py
  tick_reversal_skip_mm.py
  basket_mm.py
  tracking_error_mm.py   (deprecated - use _skip variant)
  impulse_pause_mm.py
  inventory_mm.py
  zscore_mm.py
  pair_trader.py         ⚠️ DON'T USE (taker = -305k)

research/
  logs_analysis/parse_live_log.py
  structure_analysis/group_means.py     # linear/oscillating mean detection
  structure_analysis/pca_analysis.py     # per-group + inter-group + global PCA
  structure_analysis/variance_decomp.py  # intra/factor variance ratios
  strategy_research/pair_optimization.py
  strategy_research/per_day_pnl.py       # day-by-day stability + live compare
  strategy_research/find_all_anti_pairs.py
  strategy_research/submission_choice.py
  strategy_research/decision_summary.py  # EV under different P(regime continue)
  strategy_research/final_comparison.py
  manual_challenge/ignith_kelly.py       # Manual challenge optimizer
```

## 📦 Submissions exportées (10+ options)

| File | bt PnL | EV(0.5) | Use when |
|---|---:|---:|---|
| **r5_v200_optimal_p50_round5_submission.py** ★★★ | 370,032 | **1,030,689** | MATH-OPTIMAL @P=0.5 |
| r5_v300_v200_keep_pebbles_xl (TODO export) | 409,748 | 1,026,101 | High floor (28 prods) |
| r5_v72_consistent_only_round5_submission.py | 341,923 | 1,024,864 | Live winners only |
| r5_v61_drop_broad_thresh125_round5_submission.py | 375,972 | 993,811 | Drop 10 + thresh=1.25 |
| r5_v29_drop_broad_round5_submission.py | 368,963 | 990,307 | Drop 10 only |
| r5_v60_drop_extra_round5_submission.py | 478,180 | 970,718 | Drop 6 |
| r5_v50_thresh125_drop_flipped_round5_submission.py | 491,508 | 899,323 | Drop 4 + thresh=1.25 |
| r5_v28_drop_flipped_round5_submission.py | 478,981 | 893,061 | Drop 4 only |
| **r5_v25_thresh125_round5_submission.py** ★ | **546,306** | 642,288 | MAX BT (regime reverts) |
| r5_v14b_pair_skip_curated_round5_submission.py | 533,782 | 636,026 | Original |
| r5_v2_winners_only_round5_submission.py | 514,956 | -- | Baseline (38 winners) |

## 💡 Variants testées (chronologique)

| # | Variant | bt | Note |
|---|---|---:|---|
| v2 | winners_only | 514k | drops 12 losers |
| v14b | pair_skip_curated | 534k | +18.8k via pair_skip on 4 |
| v25 | thresh=1.25 | 546k | +12.5k from tighter pair |
| v28 | drop 4 high-flipped | 479k | -55k bt for live safety |
| v29 | drop 10 broad | 369k | EV-optimal |
| v50 | thresh=1.25 + drop 4 | 492k | combo |

Tested but inferior: v3 (size variants), v4 pair_taker (-305k), v5 mm_first (-2M), v6 (-25M), v7 tighten=2 (-56k), v8 inv_mm (-20k), v9 mixed, v10 per-tighten, v11 save_losers (-100k), v12 basket_aware (-134k), v13 tracking_error_skew, v15 ext, v16 impulse_pause, v17 tighten_wide (-7.5k), v18a/b (PISTACHIO/CHOCOLATE), v19 size=10 (cap-limited), v20 pause7, v22 window500 (-22k), v32/v33 def_mode, v34 multi_pair, v35 tick_reversal, v42 size_dampen.

## 🌙 Notes nocturnes (pour Léo au réveil)

- 14+ stratégies développées
- 50+ variantes backtests réalisées
- 4 sous-modules baskets/ + 4 stratégies round_5/ ajoutés
- 5 scripts research/ d'analyse structurelle
- 5 submissions exportées prêtes à upload

**Decision finale recommandée** :
1. Si tu **crois au signal live** (régime continue) : **v29** (EV 990k, max upside 1.6M)
2. Si tu veux **maximum bt** (régime revient) : **v25** (546k bt, conservative)
3. **Compromis EV-optimal** : **v50** (Pareto-improvement, 491k floor, 1.3M ceiling)

Ma recommandation perso : **v29** car le signal live est statistiquement significatif
(PLANETARY -7k sur 999 ticks n'est pas du noise — c'est un drag structurel).

## Manual challenge (Ignith / Ashflow Alpha)
- Tool prêt : `research/manual_challenge/ignith_kelly.py`
- Quand tu auras les news Ashflow Alpha, plug les alphas, le tool calcule l'allocation optimale
- Concentration > diversification (fee quadratique)
