# Round 5 — Day-2 Findings (FINAL post Tibo merge + adaptive overlay)

## 🏆 CHAMPION FINAL : `best_v1500_carry_pairs` = 853,693 PnL

(+6,013 vs Tibo's best_v10 847,680 = +0.71%)

Combinaison de :
- Tibo's v10 base (pebbles_arb + ar1_mean_rev + trend_v2 + coint_mm + naive)
- Mon **inventory_carry_mm** sur 5 produits flipped (PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, MAGENTA, PEBBLES_L) → +4,650 vs v10
- Mon **pair_skip_mm** thresh=1.25 sur SNACKPACK_VANILLA (avec CHOC) et SNACKPACK_RASPBERRY (avec STRAW) → +1,363 vs v1010

### Per-product gains
| Produit | v10 | v1500 | Gain |
|---|---:|---:|---:|
| PANEL_4X4 | -3,690 | +240 | +3,930 |
| GALAXY_SOUNDS_SOLAR_FLAMES | -618 | +67 | +685 |
| TRANSLATOR_GRAPHITE_MIST | +6,576 | +6,798 | +222 |
| SNACKPACK_VANILLA | +2,772 | +4,051 | +1,279 |
| SNACKPACK_RASPBERRY | +15,397 | +15,482 | +85 |
| (UV_VISOR_MAGENTA, PEBBLES_L) | -3,478, +1,317 | -3,479, +1,131 | -1, -186 |
| **TOTAL** | 847,680 | 853,693 | **+6,013** |

### Composition
- **47 active products** (3 dropped: TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL)
- **31 → 26 naive_tight_mm** + **5 inventory_carry_mm** (PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, MAGENTA, PEBBLES_L)
- **11 trend_follow_v2** (Tibo)
- **3 coint_mm_v1** (Tibo: ROBOT_LAUNDRY/VAC + RECTANGLE)
- **1 ar1_mean_rev_v1** (Tibo: ROBOT_DISHES)
- **1 pebbles_arb_v1** (Tibo: PEBBLES_XL)

### Top contributors
| Product | Strat | PnL |
|---|---|---:|
| ROBOT_DISHES | ar1_mean_rev | +139,774 |
| PEBBLES_XL | pebbles_arb | +89,243 |
| MICROCHIP_SQUARE | trend_follow_v2 | +54,771 |
| PEBBLES_S | naive | +38,672 |
| PANEL_1X4 | naive | +29,686 |
| PEBBLES_XS | trend_follow_v2 | +25,450 |
| OXYGEN_SHAKE_CHOCOLATE | naive | +23,573 |
| UV_VISOR_AMBER | trend_follow_v2 | +21,955 |

### Negative contributors (only 2)
- UV_VISOR_MAGENTA: -3,479 (carry didn't help, near-untradeable)
- OXYGEN_SHAKE_MINT: -558 (small)



## 🎯 État courant

**Champion backtest** : `best_v1010_carry` = **852,330 PnL**
**vs Tibo's best_v10** = 847,680 PnL
**Mon contribution** : +4,650 (carry overlay sur 5 produits)

## 🔄 Réorientation post-discussion

J'avais une approche overfit (drop des produits) que Tibo a déjà diagnostiquée comme erreur (iter 4: v7_2_best live=14k vs v7_best live=20k malgré +83k bt).

**Insight critique du live timing analysis** : les "losers" en live perdent dans le **dernier quartile** (ts > 75k) — c'est de l'**inventory carry**, pas du regime change permanent.
- GALAXY_DARK_MATTER : q1=+761, q2=+512, q3=-797, **final=-3834**
- PLANETARY_RINGS : q1=+367, q2=-1526, q3=-4862, **final=-7257**
- ROBOT_DISHES : q1=-284, q2=-511, q3=-2143, **final=-4500**

Tous "front_loaded=False" — perdent en fin de journée via MTM sur position accumulée.

→ Solution : **inventory_carry_mm** (pause bid quand long+down ou ask quand short+up).

## 📊 Variants testés (depuis discussion)

| Variant | bt | Note |
|---|---:|---|
| **best_v10** (Tibo) | 847,680 | Base : pebbles_arb + AR1_DISHES + trend_v2 + coint + halved-limit |
| **best_v1010_carry** ★ | **852,330** | +4.6k via inventory_carry sur 5 flipped |
| best_v3000_carry_flipped | 852,330 | =v1010 (config équivalente) |
| best_v1000_adaptive | 839,805 | Adaptive_regime trop aggressive → -7.9k |
| best_v1020_full_carry | 760,816 | Carry sur TOUS naive_mm → -86k (over-extension) |

## 🔬 Stratégies créées

```
prosperity/strategies/round_5/
  inventory_carry_mm.py     ★ +4.6k via PANEL_4X4 (-3.7k → +0.2k)
  adaptive_regime_mm.py     ✗ Trop aggressive (PnL throttle)
  top_down_filter_mm.py     # group-level regime detection
  pca_residual_mr.py        # PC1 residual MR (utilise SharedR5Context)
  zscore_mr_adaptive.py     # z-score MR + regime detect
```

## 🎓 Leçons apprises

1. **Drop ≠ optimal** : v200 EV-extrap était overfit. Tibo a démontré empiriquement (v7_2_best live -7k vs v7_best).

2. **Halved-limit ≠ optimal non plus** : Tibo's v8_a a halved limit sur 5 produits flipped. Mais carry MM (v1010) bat halved-limit (v10) de +4.6k.

3. **Carry overlay = ciblé** : carry sur 5 produits (+4.6k) bat carry sur tous (-86k). Sur produits sains, carry bloque trop de fills profitables.

4. **Live overfitting** : mon × 30 extrapolation était fragile. Le live = 999 ticks ≠ 1/30 d'un jour.

5. **Adaptive PnL throttle** = trop conservateur. Mieux : carry-only signal (sans throttle PnL).

6. **GALAXY_SOLAR_FLAMES live disaster en v1000** : adaptive a perdu -11.964 sur ce produit. inventory_carry seul ne perd que -1k. Les triggers PnL throttle créent feedback loops.

## 🏆 Submissions à uploader (par ordre de préférence)

| Submission | bt | Note |
|---|---:|---|
| **best_v1010_carry** ★ | **852,330** | Champion bt avec carry sur 5 flipped |
| best_v10 (Tibo's) | 847,680 | Tibo's original (sans mon carry) |
| best_v8_a (Tibo) | 825,200 | Halved-limit version |

## ⏳ Variants en cours de test

- v1100 (PANEL_4X4 only) — isolate the +3.9k gain
- v1110 (3 targeted: PANEL_4X4, SOLAR_FLAMES, GRAPHITE_MIST)
- v1120 (live carry losers)
- v2000 (SNACKPACKs)
- v4000 (adaptive on flipped)
- v5000 (audit-recommended subset)
- v6000-v9000 (superalgo variants)

## 📋 Framework R5 modulaire (continued)

Modules nouveaux ajoutés ce round :
```
prosperity/baskets/  (groups, context, etf - 4 fichiers)
prosperity/strategies/round_5/  (16 stratégies développées)
research/structure_analysis/  (PCA, group_means, variance_decomp)
research/strategy_research/  (10+ scripts d'analyse)
research/manual_challenge/  (Ignith Kelly tool)
research/logs_analysis/  (parse_live_log, live_timing_analysis)
```

## 🔮 Ce qu'on n'a PAS encore tenté

1. **Per-product threshold tuning** sur inventory_carry_mm (trend_hl, carry_min_pos)
2. **PCA-residual MR** sur ROBOT_DISHES alternatif (Tibo a AR1 mean rev)
3. **Top-down filter** end-to-end test (v9000)
4. **Per-product zscore_mr_adaptive** sur UV_VISOR_YELLOW alternatif

## 📌 TODO restant

- Wait for v1100/v1110/v1120/v2000-v9000 results
- If any beat v1010 (852k), use it as new champion
- Build composite super-algo
- Manual Ignith challenge
