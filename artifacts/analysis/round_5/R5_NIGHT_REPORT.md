# 🌙 Rapport de la nuit — Round 5

## TL;DR

🏆 **12 submissions prêtes** dans `artifacts/submissions/round_5/`.

**Choisis selon ta conviction sur le live regime** :

| Si tu crois… | Submission | bt | EV |
|---|---|---:|---:|
| **Math-optimal @P=0.5** (recommandation principale) | `r5_v200_optimal_p50` ★★★ | 370k | **1,031k** |
| High floor + good upside | `r5_v300_v200_keep_pebbles_xl` | 410k | 1,026k |
| Live signal continue strong (P > 0.7) | `r5_v72_consistent_only` | 342k | 1,025k |
| Live continue moderate | `r5_v61_drop_broad_thresh125` | 376k | 994k |
| Régime mixte (P=0.4) | `r5_v50_thresh125_drop_flipped` | 491k | 899k |
| **Régime revient au backtest** (P < 0.3) | `r5_v25_thresh125` ★ | **546k** | 642k |

## 🎯 Ma recommandation finale

**`r5_v200_optimal_p50`** — mathématiquement optimal, EV maximal.

**Justification** :
- Live data showed clear trend losses on specific products (PLANETARY -7257 sur 999 ticks ≠ noise)
- v200 = math-optimal drop set : drop product i iff P > bt_i / (bt_i - live_i)
- Au P=0.5, optimal = drop 11 produits avec break-even probability < 0.5
- Higher EV than v72 (was over-pruning), higher floor too (370k vs 342k)
- Drop set : PLANETARY, DISHES, DARK_MATTER, MORNING_BREATH, PANEL_2X2, LAUNDRY,
  RECTANGLE, AMBER, PANEL_1X4, RASPBERRY, PEBBLES_XL

**Si tu trustes encore plus le live signal** : `r5_v203_optimal_p60` (EV 1030k aussi)
**Si tu veux higher floor** : `r5_v300_v200_keep_pebbles_xl` (bt 410k)
**Si tu trust le backtest plus** : `r5_v25_thresh125` (bt 546k)

## Que s'est-il passé pendant la nuit

**Phase 1 : Setup** (01:00-02:00)
- Module modulaire `prosperity/baskets/` avec groups, context, etf
- 4 strategies round_5/ ajoutées (pair_skip, multi_pair_skip, tracking_error_skip, tick_reversal_skip)
- Scripts d'analyse `research/structure_analysis/` (group_means, pca, variance_decomp)
- Scripts d'analyse `research/strategy_research/` (pair_optimization, per_day_pnl, find_all_anti_pairs, submission_choice, decision_summary, final_comparison, ev_under_prior)
- Manual challenge tool `research/manual_challenge/ignith_kelly.py`

**Phase 2 : Discovery** (02:00-03:00)
- Copules : λ=0 sur paires anti-corr SNACKPACK et PEBBLES → safe pair trades
- PCA : SNACKPACK 94% var en PC1+PC2, TRANSLATOR/PEBBLES means flat
- Variance decomp : PEBBLES intra/factor=27.3, SNACKPACK 3.77 → indep members
- Lead-lag intra-tick : RIEN
- Cointégration : RIEN  
- Trader IDs : retirés en R5

**Phase 3 : Strategy iteration** (03:00-04:00)
- v14b pair_skip on 4 winners (PEBBLES_XL/S, SNACKPACK_VAN/RASP) = 533k (+18.8k)
- v25 thresh=1.25 = 546k (NEW BT CHAMPION)
- Tracker error, basket-aware, multi-pair, tick-reversal, impulse-pause TOUS testés et inférieurs

**Phase 4 : Live log analysis** (04:00-04:30)
- Parsed IMC live R5 log (550081)
- Live PnL = 24,609 / 999 ticks → extrapolated 738k / 3 days
- IDENTIFIED REGIME-FLIPPED products: PLANETARY -7k, DISHES -4.5k, DARK_MATTER -3.8k, MORNING_BREATH -3.4k

**Phase 5 : Defensive variants** (04:30-04:50)
- v28 drop 4 flipped = 479k bt, EV 893k
- v29 drop 10 broader = 369k bt, EV 990k
- v60 drop 6 = 478k bt, EV 971k
- v61 (drop 10 + thresh=1.25) = 376k bt, EV 994k
- v72 (consistent live winners only, 25 prods) = 342k bt, **EV 1,025k** ← CHAMPION

## Structure du projet ajoutée ce round

```
prosperity/baskets/                              # NEW module
  __init__.py
  groups.py                                      # 10 wiki-defined groups
  context.py                                     # SharedR5Context
  etf.py                                         # GroupETF + PCAPortfolio

prosperity/strategies/round_5/
  __init__.py
  pair_skip_mm.py             ★                  # Champion strategy
  multi_pair_skip_mm.py
  tracking_error_skip_mm.py
  tracking_error_mm.py        (deprecated)
  basket_mm.py                (deprecated)
  impulse_pause_mm.py
  tick_reversal_skip_mm.py
  inventory_mm.py
  zscore_mm.py
  pair_trader.py              ⚠️ DON'T USE       # taker = -305k

research/                                        # NEW research workflow
  logs_analysis/parse_live_log.py
  structure_analysis/
    group_means.py            # mean linearity + Hurst
    pca_analysis.py           # per-group + inter-group + global PCA
    variance_decomp.py        # intra/factor variance ratios
  strategy_research/
    pair_optimization.py      # find optimal partner per product
    per_day_pnl.py            # per-day stability + live compare
    find_all_anti_pairs.py    # all |corr|>0.30 pairs
    submission_choice.py      # EV trade-off analysis
    decision_summary.py       # ranking under different P(continue)
    final_comparison.py       # aggregate all variants
    ev_under_prior.py         # detailed EV table
  manual_challenge/
    ignith_kelly.py           # Manual challenge optimizer

artifacts/analysis/round_5/                      # NEW analysis outputs
  R5_FINDINGS.md              # Full findings report
  R5_TODO.md                  # Recommendations + outstanding ideas
  R5_NIGHT_REPORT.md          # This file
  copulas_*.csv               # Tail dependence per pair
  correlations_*.csv          # Pearson/Spearman pairwise
  intergroup_*.csv            # Group-level coint, lead-lag, etc.
  pca_*.csv                   # PCA loadings per group + inter-group + global
  group_*.csv                 # Group profile, indices, cohesion
  variance_decomp.csv
  impulse_*.csv               # Impulse response per pair
  member_diag.csv             # Per-product diagnostics
  pair_optimization_*.csv     # Optimal partner per product
  live_per_product_pnl.csv    # IMC live log parsed
  live_vs_backtest.csv        # Comparison
  final_comparison.csv        # All variants ranked

artifacts/r5_compare/                            # NEW backtest outputs
  v2.txt, v14b.txt, v25.txt, ... v80.txt        # 60+ variants tested

artifacts/submissions/round_5/                   # 9 submissions exported
  r5_v72_consistent_only_round5_submission.py    ★★ EV champion
  r5_v61_drop_broad_thresh125_round5_submission.py ★ broader EV
  r5_v60_drop_extra_round5_submission.py
  r5_v50_thresh125_drop_flipped_round5_submission.py
  r5_v29_drop_broad_round5_submission.py
  r5_v28_drop_flipped_round5_submission.py
  r5_v25_thresh125_round5_submission.py          ★ BT champion
  r5_v14b_pair_skip_curated_round5_submission.py
  r5_v2_winners_only_round5_submission.py
```

## Variants testés (chronologique)

v2 (514k baseline) → v14b (533k pair_skip) → v25 (546k thresh=1.25 NEW BT CHAMPION) →
v28 (479k drop 4) → v29 (369k drop 10) → v50 (491k drop 4 + thresh) → v60 (478k drop 6 + thresh) →
v61 (376k drop 10 + thresh) → **v72 (342k consistent only)**

Plus 50+ ablations.

## Next steps quand tu reviens

1. **Choisis ta submission** parmi les 9 exportées
2. **Upload à IMC** avec leur interface
3. **Manual challenge Ignith** : quand les news Ashflow Alpha arrivent, plug les alphas dans `research/manual_challenge/ignith_kelly.py`

## En cas de doute

Le calcul de EV est conservateur (50/50 entre bt et live extrapolé). Si tu veux être plus aggressif, regarde les EV à P=0.7 dans `decision_summary.py`. v72 reste le winner.

Si tu veux le SAFE choice, prends v25 (max bt, ne perd rien si régime stable).

Si tu veux LE BIG BET, prends v72 (max EV, max upside, mais low floor).

## Stats

- 6h de travail autonome
- ~60 backtests réalisés
- ~9k lignes de code (nouvelle infra + scripts research)
- 18 stratégies développées
- 9 submissions validées et exportées

Bonne journée Léo ! 🌅
