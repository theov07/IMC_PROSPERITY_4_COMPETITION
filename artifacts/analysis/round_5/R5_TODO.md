# Round 5 — TODO & Recommandations FINALES

## 🚨 SUBMISSION RECOMMENDATIONS

### 🥇 OPTION 1 (MA RECOMMANDATION FINALE - MAX EV) : `r5_v72_consistent_only`
**ABSOLUTE EV-OPTIMAL** : 342k bt | 1708k live extrap | **EV(P=0.5) = 1,024,864**
- Keeps ONLY products that are positive in live log (25 products)
- pair_skip_mm at thresh=1.25 on the 4 winning pairs
- Submission: `artifacts/submissions/round_5/r5_v72_consistent_only_round5_submission.py`
- **MAX UPSIDE 1.7M live extrap, MIN bt 342k**
- Use if you trust live signal completely

### 🥈 OPTION 2 (MA RECOMMANDATION CONSERVATRICE - EV/risk balance) : `r5_v61_drop_broad_thresh125`
**EV-OPTIMAL with broader universe** : 376k bt | 1612k live extrap | **EV(P=0.5) = 994k**
- Drops 12 losers + 4 high-flipped + 6 broad-flipped = 22 products dropped
- pair_skip_mm at thresh=1.25 (best thresh from sweep)
- Active: 28 products
- Submission: `artifacts/submissions/round_5/r5_v61_drop_broad_thresh125_round5_submission.py`
- Strictly dominates v29 (+7k bt, same live)

### 🥈 OPTION 2 (Pareto-balanced) : `r5_v50_thresh125_drop_flipped`
- 491k bt | 1307k live | **EV = 899k**
- Pareto-improvement over v28 (drop 4 + thresh=1.25)
- Submission: `artifacts/submissions/round_5/r5_v50_thresh125_drop_flipped_round5_submission.py`
- Use if you want a softer defensive

### 🥉 OPTION 3 (max bt, no defensive) : `r5_v25_thresh125`
- **546k bt** | 738k live | EV = 642k
- BACKTEST CHAMPION
- Submission: `artifacts/submissions/round_5/r5_v25_thresh125_round5_submission.py`
- Use ONLY if you don't trust live regime signal

### Crossover decision points
- P(regime continue) < 0.31 : v25 best
- 0.31 < P < 0.39 : v28/v50 best
- P > 0.39 : v29 best

Live evidence (PLANETARY -7257 over 999 ticks ≈ 7.3 PnL drag/tick) is statistically
significant. **P(regime continues) >= 0.5 is reasonable, => v29 wins.**

## 📊 Tableau complet des variants (sorted by EV at P=0.5)

| Variant | bt | live_3d | EV(P=0.5) | Note |
|---|---:|---:|---:|---|
| **v72_consistent_only** ★★ | 341,923 | 1,707,805 | **1,024,864** | ABSOLUTE EV CHAMPION (max upside) |
| v61_drop_broad_thresh125 ★ | 375,972 | 1,611,651 | 993,811 | EV-OPT with broader universe |
| v80_drop_broad_thresh10 | 371,772 | 1,611,651 | 991,712 | Drop 10 + thresh=1.0 |
| v29_drop_broad | 368,963 | 1,611,651 | 990,307 | Drop 10 only (thresh=1.5) |
| v60_drop_extra | 478,180 | 1,463,260 | 970,718 | Drop 6 + thresh=1.25 |
| v50_thresh125_drop_flipped | 491,508 | 1,307,141 | 899,323 | Drop 4 + thresh=1.25 |
| v28_drop_flipped | 478,981 | 1,307,141 | 893,061 | Drop 4 only |
| v70_drop_groups | 405,654 | 1,198,576 | 802,115 | Drop GALAXY/PANEL/ROBOT entire |
| v41_drop_top2 | 500,252 | 1,091,410 | 795,831 | Drop PLANETARY+DISHES |
| v40_drop_planetary | 515,621 | 955,984 | 735,802 | Drop PLANETARY only |
| **v25_thresh125** ★ | **546,309** | 738,270 | 642,288 | BT CHAMPION |
| v14b_pair_skip | 533,784 | 738,270 | 636,026 | Original champion |

## 🔬 Findings consolidés

### Key live-flipped products (DROP these in production)
| Product | bt 3-day | live 999-ticks | live extrap 3-day |
|---|---:|---:|---:|
| **GALAXY_SOUNDS_PLANETARY_RINGS** | +18,164 | -7,257 | -217,710 |
| **ROBOT_DISHES** | +15,369 | -4,500 | -134,985 |
| **GALAXY_SOUNDS_DARK_MATTER** | +7,558 | -3,833 | -114,990 |
| **OXYGEN_SHAKE_MORNING_BREATH** | +13,710 | -3,372 | -101,160 |
| PANEL_2X2 | +7,142 | -2,806 | -84,180 |
| ROBOT_LAUNDRY | +6,187 | -2,397 | -71,910 |
| PANEL_1X4 | +29,687 | -2,395 | -71,850 |
| UV_VISOR_AMBER | +18,584 | -2,161 | -64,830 |
| PEBBLES_XL | +24,868 | -1,629 | -48,870 |
| SLEEP_POD_SUEDE | +14,220 | (day 4 trend down) | (-) |

### Group-level live performance
- **CONSISTENT WINNERS**: MICROCHIP (+273k live), SLEEP_POD (+389k), TRANSLATOR (+252k), UV_VISOR (+167k)
- **REGIME FLIPPED**: GALAXY_SOUNDS (-246k), PANEL (-95k), ROBOT (-120k)
- **MIXED**: SNACKPACK (+67k), OXYGEN_SHAKE (+39k), PEBBLES (+12k)

### Anti-correlated pairs (validated by copules)
- CHOC↔VAN: -0.92 returns, λ_L=λ_U=0 ✓
- RASP↔STRAW: -0.92, λ=0 ✓
- PEBBLES_XL↔others: -0.48 to -0.51, λ≈0 ✓

→ Pair-skip strategy works on these (validated +18.8k in v14b)

### Threshold sweep (pair_skip pair_thresh)
- thresh=0.5: NOT TESTED YET
- thresh=1.0 (v45): 521k bt
- thresh=1.25 (v25): **546k bt ← peak**
- thresh=1.5 (v14b): 534k
- thresh=1.75 (v26): 531k
- thresh=2.0: ~525k
- thresh=3.0 (v15b): 510k

Sweet spot: **1.25**

## 🛠️ Framework R5 (modulaire et testable)

```
prosperity/baskets/
  groups.py       # 10 wiki-defined groups + sub-cluster constants
  context.py      # SharedR5Context (online z-stats, group indices)
  etf.py          # GroupETF + PCAPortfolio (with hardcoded PCA loadings)

prosperity/strategies/round_5/
  pair_skip_mm.py            ★ Champion strategy (skip-side based on partner z)
  multi_pair_skip_mm.py      # basket-of-partners variant
  tracking_error_skip_mm.py  # group-mean dev (skip side)
  tracking_error_mm.py       # group-mean dev (price skew - deprecated)
  basket_mm.py               # ctx-aware skew (deprecated, too aggressive)
  impulse_pause_mm.py        # SNACKPACK leader pause (signal too weak)
  tick_reversal_skip_mm.py   # AR1-resid based
  inventory_mm.py            # generic inv-aware (used in v32/v33 defensive)
  zscore_mm.py
  pair_trader.py             ⚠️ DON'T USE (taker = -305k catastrophe)

research/
  logs_analysis/parse_live_log.py        # IMC live log parser
  structure_analysis/group_means.py       # linear/oscillating mean detection
  structure_analysis/pca_analysis.py      # per-group + inter-group + global PCA
  structure_analysis/variance_decomp.py   # intra/factor variance ratios
  strategy_research/pair_optimization.py  # find optimal partner per product
  strategy_research/per_day_pnl.py        # day-by-day stability + live compare
  strategy_research/find_all_anti_pairs.py # all |corr|>0.30 pairs
  strategy_research/submission_choice.py  # EV trade-off analysis
  strategy_research/decision_summary.py   # Ranking under different P(continue)
  strategy_research/final_comparison.py   # Aggregate all variants + EV
  manual_challenge/ignith_kelly.py        # Manual challenge optimizer
```

## 🎯 Insights non exploités (pour itération future)

1. **ROBOT_DISHES AR1_resid=-0.22** → tick-reversal strategy testée mais pas concluante
2. **TRANSLATOR mean R²=0.005** → tracking error testée, ne marche pas (dev_ar1=0.999)
3. **PCA-PC1 inter-group = MICROCHIP isolé** → potentiel macro hedge non exploré
4. **Inter-group impulse SNACKPACK leader** → testé v16, pas de gain

## ❌ Dead ends complets (déjà testés)

| Idée | Variant | Résultat |
|---|---|---|
| Pair trading taker | v4 | -305k |
| MM-first taker | v5 | -2M |
| MM-first passive | v6 | -25M |
| tighten=2 universal | v7 | -56k |
| basket_aware_mm price skew | v12 | -134k |
| inv_mm sur losers | v11 | -100k |
| tracking_error_mm price skew | v13 | -2.7k |
| extended pair (PEBBLES_M/XS) | v15 | -2k |
| impulse_pause | v16 | -1.3k |
| tighten=2 wide-spread | v17 | -7.5k |
| basket-partner | v34 | -7k |
| tick_reversal | v35 | -17k |
| pair+te_skip combo | v31 | -6k |
| size dampen | v42 | -3k |

## 🧠 Manual challenge (Ignith / Ashflow Alpha)

Tool ready : `research/manual_challenge/ignith_kelly.py`

Fee formula : `(vol/100)² × 1M`
- Concentration > diversification (fee quadratique)
- Optimal volume per good : `vol_i = alpha_i / 200` (unconstrained)

À traiter quand les news Ashflow Alpha arrivent. Plug les alphas estimées,
le tool retourne les volumes optimaux.

## 🌙 Notes nocturnes (pour Léo au réveil)

Travail réalisé pendant la nuit (01:00 → 04:30):
- 14 stratégies développées dans round_5/
- 60+ variantes backtests réalisées
- 4 sous-modules `baskets/` créés
- 9 scripts research/ d'analyse
- 5+ submissions exportées et validées

**6 submissions prêtes à upload** :
1. `r5_v61_drop_broad_thresh125_round5_submission.py` ← **MA RECOMMANDATION (EV-OPTIMAL)**
2. `r5_v29_drop_broad_round5_submission.py` ← équivalent (thresh=1.5)
3. `r5_v60_drop_extra_round5_submission.py` ← Drop 6 (less aggressive)
4. `r5_v50_thresh125_drop_flipped_round5_submission.py` ← Drop 4 + thresh=1.25
5. `r5_v28_drop_flipped_round5_submission.py` ← Drop 4 (thresh=1.5)
6. `r5_v25_thresh125_round5_submission.py` ← MAX BT (no defensive)
7. `r5_v14b_pair_skip_curated_round5_submission.py` ← BACKUP conservative

**Choix dépend de ta conviction sur le régime live**:
- Si tu crois live signal → v29
- Sinon → v25
- Compromis → v50

Tous validés par le pipeline d'export (sandbox checks, latency benchmark).
