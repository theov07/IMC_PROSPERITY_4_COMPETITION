# Round 5 — Findings & Strategy Map

## Le contexte
- **50 produits**, 10 groupes × 5
- **Position limit = 10 par produit** (vs 200-300 R4) → MM small-size game
- Données : Day 2 / 3 / 4 (3 × 10000 ticks = 30000 rows par produit)
- Wiki : "some groups offer more inefficiencies, strong patterns embedded"

## État actuel

| Variant | Strat | PnL 3-day | DD | Ratio | Note |
|---|---|---:|---:|---:|---|
| r5_baseline_mm | naive_tight_mm sur 50 | 401,540 | 37,326 | 10.75 | Tous |
| **r5_v2_winners_only** | naive_tight_mm sur 38 | **514,956** | **27,212** | **18.92** | 12 losers retirés ★ |
| r5_v3_size10 | tighten=1, size=10 | 514,956 | 27,212 | 18.92 | identique (cap) |
| r5_v3_size10_t2 | tighten=2 | 458,762 | 27,673 | 16.58 | -56k |
| r5_v4_pair_trading | pair_trader | 209,536 | 41,692 | 5.03 | -305k taker pays spread |
| r5_v5_mm_first | mm_first défaut | -2,004,045 | n/a | n/a | takers tuent |
| r5_v6_mm_first_passive | mm_first no takers | -25,775,568 | n/a | n/a | catastrophe |
| r5_v7_tighten=2 | tighten=2 | 458,762 | 27,673 | 16.58 | tight=1 mieux |
| r5_v8_inv_mm | inventory_aware_mm | 494,270 | 27,554 | 17.94 | -20k vs v2 |
| r5_v9_mixed | zscore_mm + inv_mm | 492,710 | 27,978 | 17.61 | -22k |
| r5_v10_per_tighten | per-product tighten | 491,832 | 27,415 | 17.94 | -23k |

**Champion R5 = r5_v2_winners_only = 514,956 PnL / DD 27k / Ratio 18.92**

## 12 Losers retirés
`OXYGEN_SHAKE_MINT, TRANSLATOR_GRAPHITE_MIST, PEBBLES_XS, ROBOT_VACUUMING, PANEL_4X4, TRANSLATOR_SPACE_GRAY, GALAXY_SOUNDS_SOLAR_FLAMES, UV_VISOR_MAGENTA, ROBOT_MOPPING, PANEL_1X2, PEBBLES_M, SLEEP_POD_LAMB_WOOL`

## DÉCOUVERTES CORRELATION

### 1. SNACKPACKS — système à 2 clusters inverses
| Métrique | Pair | Levels | Returns |
|---|---|---:|---:|
| Strongest neg | RASPBERRY ↔ STRAWBERRY | -0.752 | **-0.923** |
| Second neg | CHOCOLATE ↔ VANILLA | -0.974 | **-0.915** |
| Third neg | PISTACHIO ↔ RASPBERRY | -0.434 | -0.831 |
| Strong pos | PISTACHIO ↔ STRAWBERRY | +0.913 | +0.913 |

**Inférence : 2 sous-groupes anti-correlés**
- Cluster A : CHOCOLATE, RASPBERRY (positivement corrélés entre eux)
- Cluster B : VANILLA, STRAWBERRY, PISTACHIO (positivement corrélés entre eux)
- A ↔ B inversement corrélés (-0.83 à -0.92)

**Stable sur 3 jours** (-0.917 to -0.932) → pattern persistent.

**Tail dependence (copulas) = 0** : quand A crash, B ne crash pas → **inverse pur, pas de risque commun**.

### 2. PEBBLES — XL est l'opposé du reste
| Pair | Returns corr |
|---|---:|
| XL ↔ M | -0.506 |
| XL ↔ L | -0.493 |
| XL ↔ S | -0.483 |
| XL ↔ XS | -0.475 |

XL anti-corrélé avec TOUS les autres pebbles. Probablement signal de demande/offre dans le système.

### 3. Cross-group corrélation forte (levels seulement, pas returns)
- SLEEP_POD_POLYESTER ↔ UV_VISOR_AMBER : -0.941 (cross-group !)
- MICROCHIP_SQUARE ↔ UV_VISOR_AMBER : -0.914
- MICROCHIP_SQUARE ↔ PEBBLES_XS : -0.914

**Note** : ces corrélations LEVEL sont fortes mais corrélations RETURN faibles → ce sont des co-mouvements LENTS, pas intra-tick. Difficile à exploiter pour HFT mais utile pour position sizing.

### 4. Lead-lag — RIEN
Max |corr| = 0.051 entre returns(t) et returns(t+k) pour k=5/10/20/50. **Pas de timing arbitrage** — tout est synchrone.

## STRATEGY MAP par produit

### Mean reversion (rev_ratio > 2)
| Produit | Rev ratio | Std | Spread | Strategy idéale |
|---|---:|---:|---:|---|
| UV_VISOR_YELLOW | **9.60** | 681 | 13.9 | MM + bandes z-score |
| OXYGEN_SHAKE_MINT | 3.28 | 508 | 12.6 | MM (LOSER - exclure?) |
| TRANSLATOR_GRAPHITE_MIST | 2.41 | 499 | 8.9 | MM (LOSER) |
| GALAXY_SOUNDS_SOLAR_WINDS | 2.19 | 541 | 13.3 | MM |
| GALAXY_SOUNDS_PLANETARY_RINGS | 2.18 | 765 | 13.7 | MM |

### Trending (rev_ratio < 1)
La majorité — 38 produits. Naive MM marche bien quand le drift n'est pas trop fort. Pour les très trending : ajouter trend-follow ?

### Top wide-spread (best for MM)
| Produit | Spread | Top vol | PnL/trade est |
|---|---:|---:|---:|
| SNACKPACK_STRAWBERRY | 17.83 | 59 | 89 |
| SNACKPACK_VANILLA | 16.87 | 59 | 84 |
| SNACKPACK_RASPBERRY | 16.84 | 59 | 84 |
| PEBBLES_XL | 16.63 | 25 | 83 |
| SNACKPACK_CHOCOLATE | 16.47 | 59 | 82 |

## TODO R5 — Priorité

### HIGH (à attaquer)
1. **Per-product tighten_ticks** : products avec spread > 14 → tighten=2-3 ; spread < 8 → tighten=1
2. **Inventory skew** : ajouter pos-skew au naive_tight_mm pour les trending products
3. **SNACKPACK basket** : MM séparé sur l'index moyen Cluster A vs Cluster B
4. **PEBBLES basket** : MM sur PEBBLES_XL contre l'index des autres pebbles
5. **Mean reversion** : strategy z-score sur UV_VISOR_YELLOW (rev_ratio 9.6)

### MED
6. **Volatility-adjusted sizing** : adapter `maker_size` per product to vol
7. **Trade analysis (trader IDs)** : sur 3 days, qui sont les MM/informed/noise ?
8. **Adaptive day-3 detection** : Day 4 a-t-il un drift fort qui hurt ?

### LOW
9. **Cross-asset hedge** : sur les pairs cross-group (SLEEP_POLYESTER ↔ UV_AMBER)
10. **HF MM with adaptive spread** : dynamique selon vol récente

## Manual challenge (Ignith / Ashflow Alpha)
À traiter séparément. Budget 1M, fee = (vol/100)² × budget.

Optimal : minimiser fees → spread sur peu de produits avec haute conviction.
