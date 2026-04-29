# R5 — FINAL RECOMMENDATION (post user feedback)

## 🏆 TOP PICK : `best_v1500_carry_pairs` = **853,693 PnL**

Submission: `artifacts/submissions/round_5/best_v1500_carry_pairs_round5_submission.py`

### Composition (combinaison Tibo + Léo)

**Base = best_v10 (Tibo)** :
- pebbles_arb_v1 sur PEBBLES_XL → +89k (conservation taker)
- ar1_mean_rev_v1 sur ROBOT_DISHES → +140k (mean rev z>20)
- trend_follow_v2 sur 11 produits → +97k (Tibo's tuning)
- coint_mm_v1 sur ROBOT_LAUNDRY/VAC + MICROCHIP_RECTANGLE → +35k
- 3 produits None (TRANSLATOR_SPACE_GRAY, PEBBLES_M, SLEEP_POD_LAMB_WOOL)

**+ Mes contributions** :
- **inventory_carry_mm** sur les 5 produits flipped (PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, MAGENTA, PEBBLES_L) → +4,650 vs v10
- **pair_skip_mm** thresh=1.25 sur SNACKPACK_VANILLA-CHOC + SNACKPACK_RASPBERRY-STRAW → +1,363 vs v1010

### Pourquoi c'est mieux que naive_tight_mm

Tibo's `naive_tight_mm` est juste penny-improve (best_bid+1 / best_ask-1) avec hard pause à |pos|=9.

Mes overlays ajoutent :
- **inventory_carry_mm** : pause le côté inventory-increasing quand carry adverse (long+down → no bid)
- **pair_skip_mm** : pause un côté quand z(self) + z(partner_anti_corr) extrême

Pas de timestamp-based logic (pas de late_flatten — overfit).

## 📊 Tests effectués (post-discussion)

| Variant | PnL | Delta vs v10 | Note |
|---|---:|---:|---|
| **best_v1500_carry_pairs** ★★ | 853,693 | **+6,013** | Champion |
| best_v1010_carry | 852,330 | +4,650 | carry uniquement |
| best_v3000_carry_flipped | 852,330 | +4,650 | = v1010 |
| best_v1100_panel_only | 851,609 | +3,929 | carry sur PANEL_4X4 seul |
| **best_v10** (Tibo) | 847,680 | 0 | Tibo's base |
| best_v2000_carry_snack | 840,261 | -7,419 | carry sur SNACKPACK = bad |
| best_v1000_adaptive | 839,805 | -7,875 | adaptive_regime trop aggressive |
| best_v4000_adaptive_flipped | 830,390 | -17k | adaptive sur flipped |
| best_v6000_superalgo | 810,816 | -36k | carry sur 32 audit prods |
| best_v7000_slow | 801,401 | -46k | trend_hl=300 slow |
| best_v8000_fast | 799,870 | -47k | trend_hl=100 fast |
| best_v9000_topdown | 770,560 | -77k | top_down filter |
| best_v1020_full_carry | 760,816 | -86k | carry sur tous naive |

## 🔬 Insights clés

### Carry overlay est NICHE
- Carry sur 5 produits ciblés = +4.6k
- Carry sur 32 produits = -36k
- Carry sur 31 (tous naive_mm) = -86k

→ **N'aide que les produits déjà perdants** (PANEL_4X4 -3.7k → +0.2k = +3.9k gain)

### Pair_skip est NICHE aussi
- Sur SNACKPACK_VANILLA = +1.3k (pair anti-corr -0.92, λ=0)
- Sur SNACKPACK_RASPBERRY = +85
- Sur autres SNACKPACK = neutre/marginal

### Top-down filter HURTS
- v9000 = -77k. Le throttling group-level coupe trop.

### Real MM (avec inventory skew) — testing
- v2000r/v2100r en cours. Si meilleur que naive, super-algo final.

## 💡 Réflexion sur l'overfit

User a raison sur le risque overfit avec mes drops basés sur live (v200, v72, etc.). L'approche v1500 est **purement basée sur backtest** :
- Pas de drops basés sur live
- Pas de carry timestamp-based
- Juste ajout de signaux validés (pair_skip, inventory_carry) dans v10

Les paramètres :
- pair_thresh=1.25 (sweet spot trouvé via thresh sweep 0.5-3.0)
- carry_pause_min_pos=3 (active à |pos|>=3, conservateur)
- trend_hl=200 (EMA mid pour trend detection)

Aucun param tuned sur live. Pure backtest.

## 🎯 À tester encore

- v1600 (PEBBLES_S pair_skip) — pourrait ajouter +2-5k si signal propage
- v1900 (carry sur 3 q4 losers) — ciblage live carry losers
- v3000_super (combo: v1500 + v1900 + drop magenta)
- v2000r/v2100r (real_mm avec inventory skew)
- v1700 (drop UV_VISOR_MAGENTA -3.5k loser)
