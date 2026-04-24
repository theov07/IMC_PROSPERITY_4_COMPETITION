# MAF — Findings & Break-even Bid

Date : 2026-04-19
Strategy : `champion_19april_am` (v4_F5 OSM + Theo v4 IPR shift=85)

---

## TL;DR

⚠️ **Attention aux unités** : live PnL = simu-test XIRECs, bid MAF = simu-finale XIRECs
(scaling ×8.9 empirique R1 : 12k test → 107k finale)

### Valuation (V) mesurée
- **Gain MAF en simu-test : +1,258 ± 338 XIRECs_test (+12.4% du PnL live)**
- **Gain MAF en simu-finale : +11,194 ± 3,007 XIRECs_finale**
- **Break-even bid (finale, là où on paie) : 11,194 XIRECs**
- **100% du gain vient d'OSM** — IPR (Theo v4 far-quote) profite pas du +25% de flow

### 🎯 BID FINAL RETENU : **2,173 XIRECs finale**
- Hedge tournament-regret contre top competitors (mean estimé 2,800, médiane 2,000)
- Markup anti-focal sur 2,000 (+173, prime number, évite clusters stratèges)
- Capture 80% de la valeur MAF si accepté (net +9,021 XIRECs)
- Reste à 19% de notre V → 81% marge sécurité vs break-even

---

## Méthodologie (reproductible)

**Insight clé (Léo)** : Le live IMC sample ~80% du vrai order book à chaque tick.
Le MAF donne +25% de quotes de plus → 80% × 1.25 = 100% (= conditions backtest).

Donc : `uplift_MAF = PnL_backtest(100%) / PnL_backtest(80% subsampled)`
Puis : `MAF_gain_live = PnL_live × (uplift − 1)`

### Pipeline (4 scripts)

| # | Script | Rôle |
|---|---|---|
| 05 | `05_subsample_80pct.py` | Thinning binomial des volumes à p=0.8 (book + trades) |
| 06 | `06_estimate_maf_live_gain.py` | Backtest 100% vs 80%, ratios uplift par produit |
| 07 | `07_parse_live_logs.py` | Parse logs IMC R2 → PnL final par run par produit |
| 08 | `08_maf_breakeven_report.py` | Consolide : logs + uplift → gain MAF + break-even |

### Commandes pour reproduire

```bash
# 1. Générer 3 seeds de data subsamplée à 80%
python research/round_2_MAF/05_subsample_80pct.py --seed 100 --n_seeds 3 --p_keep 0.8

# 2. Mesurer les ratios uplift 100%/80%
python research/round_2_MAF/06_estimate_maf_live_gain.py \
    --strategy champion_19april_am --subsample-seeds 100,101,102 \
    --live-pnl-osm 4000 --live-pnl-ipr 8800

# 3. Parser les logs live IMC
python research/round_2_MAF/07_parse_live_logs.py \
    --logs "Downloads/log_2_champion_combine/308318.log" \
           "Downloads/log_champion_combine/308278.log" \
           ... \
    --save-json research/round_2_MAF/live_logs_summary.json

# 4. Rapport final break-even
python research/round_2_MAF/08_maf_breakeven_report.py \
    --logs-json research/round_2_MAF/live_logs_summary.json \
    --uplift-osm 1.488 --uplift-osm-std 0.025 \
    --uplift-ipr 1.0004 --uplift-ipr-std 0.0004
```

---

## Résultats détaillés

### 1. Uplift ratios (backtest realistic, 3 seeds subsample)

| Produit | PnL 100% | PnL 80% (mean) | Ratio | Uplift % |
|---|---|---|---|---|
| OSM | 63,420 | ~42,636 | ×1.488 | **+48.8%** |
| IPR | 238,268 | ~238,175 | ×1.0004 | +0.04% |
| TOTAL | 301,688 | ~280,810 | ×1.074 | +7.4% |

- Std très tight sur OSM (±0.025) et quasi-nul sur IPR → mesure fiable
- IPR plat car Theo v4 fille sur empty-book events, pas sur le volume disponible

### 2. Distribution live (8 logs R2)

| Produit | n runs | Mean | Std | Min | Max |
|---|---|---|---|---|---|
| OSM | 6 | 2,571 | 680 | 1,885 | 3,621 |
| IPR | 4 | 7,677 | 298 | 7,367 | 7,972 |
| Combined (obs.) | 2 | 10,155 | 333 | 9,919 | 10,391 |

### 3. MAF gain live (propagation d'erreur)

Formule : `Var[PnL×(u−1)] = (u−1)²·Var[PnL] + E[PnL]²·Var[u]`

| Produit | Gain MAF | σ | % du live |
|---|---|---|---|
| OSM | +1,255 | ±338 | +48.80% |
| IPR | +3 | ±3 | +0.04% |
| **TOTAL** | **+1,258** | **±338** | **+12.39%** |

### 4. Break-even

| Scénario | simu-test | **simu-FINALE (bid paid here)** |
|---|---|---|
| **Break-even (E[net]=0)** | 1,258 | **11,194** |
| Conservateur (−1σ) | 920 | **8,186** |
| Worst live observed | 923 | 8,215 |
| Best live observed | 1,770 | 15,753 |
| 2σ bracket | [582, 1,934] | [5,179, 17,209] |

Scaling factor utilisé : ×8.9 (empirique R1 : notre 12,061 test → 107,367 finale).

---

## Interprétation (toutes valeurs en XIRECs **finale**)

**Bid < 11,194** → net positif en espérance **si auction gagnée**
**Bid > 11,194** → net négatif en espérance **si auction gagnée**

Sous first-price auction, l'optimal est plus bas que le break-even :
optimal ≈ break-even × f(adversary) — voir `03_bid_optimization.py` et `04_final_report.py`
(⚠ ces scripts utilisent une ancienne V=10,000, à re-run avec V=11,194).

La recommandation finale dépend de la distribution des bids adverses (médiane),
recherche à faire ensuite.

---

## Caveats

1. **Hypothèse p_keep = 0.8** — officiel ? À confirmer sur la doc wiki IMC. Tester avec 0.75 et 0.85.
2. **n=2 runs combined** — très peu pour la variance du total. Plus de runs = meilleur.
3. **Uplift OSM backtest realistic** — le fill model est optimiste vs live. L'uplift réel peut être plus bas (5-10% peut-être au lieu de 49%).
4. **Ancienne méthode (synthetic +25%) sous-estimait** V de 10-50× car n'enrichissait que le book, pas les trades — abandonnée, remplacée par le 80%-thinning.

---

## Fichiers produits

- `research/round_2_MAF/05_subsample_80pct.py` — générateur data 80%
- `research/round_2_MAF/06_estimate_maf_live_gain.py` — mesure uplift
- `research/round_2_MAF/07_parse_live_logs.py` — parser logs IMC
- `research/round_2_MAF/08_maf_breakeven_report.py` — rapport final
- `research/round_2_MAF/live_logs_summary.json` — PnL par run des 8 logs
- `data/round_2_subsample_p80_s{100,101,102}/` — datasets 80%-thinned

---

## Phase 2 — Médiane adverse (scripts 09-13)

Scripts produits :
- `09_leaderboard_stats.py` : analyse leaderboard R1 global (600 teams) + France (207)
- `10_r2_field_analysis.py` : analyse R2 field (3,065 teams) + V distribution
- `11_median_simulator.py` : Monte Carlo médiane, 5 scénarios paramétriques
- `12_sensitivity_grid.py` : grid `frac_no_bid × frac_wiki` + shading + V threshold
- `13_final_recommendation.py` : rapport consolidé

### Données intégrées

- R2 field : 3,065 teams de-duplicated (denominator ferme)
- Wiki ancres : `return 15` (exemple principal), secondary {10, 19, 20, 21, 34}
- V model : V_test = 12.2% × PnL_test pour PnL > 7,000 seuil
- Notre V : 11,194 finale (break-even)

### Médianes simulées par scénario (finale XIRECs)

| Scénario | Frac no-bid | Frac wiki | Médiane adverse | Bid optimal |
|---|---|---|---|---|
| optimistic | 75% | 15% | 0 | 1 |
| central | 55% | 15% | 0 | 1 |
| wiki_heavy | 40% | 40% | 15 | 50 |
| pessimistic | 30% | 10% | 594 | 2,000 |
| competitive | 15% | 5% | 5,102 | 7,000 |

### Grid sensitivity — optimal bid selon (frac_no_bid × frac_wiki)

```
frac_no_bid \ wiki   5%    10%    20%    30%
  20%              6000   5000   5000    100
  30%              5000   1500    100     25
  40%              1000    100     25     25
  50%                25     25     25     25
  60%                 1      1      1      1
  70%+                1      1      1      1
```

**Point de bascule critique : frac_no_bid ≈ 50%.**
- Au-dessus → médiane=0 → bid 1-25 suffit
- En-dessous → bid 100-7,000 selon fraction wiki

### Robust bid p75 (beats 75% des cellules) = **100 XIRECs finale**
### Expected-value optimal (prior uniforme sur scénarios) = **1,000 XIRECs finale**

## Phase 3 — Level-k / Tournament-regret (scripts 14-17)

Scripts produits :
- `14_participation_sensitivity.py` : variation n_teams → scale-invariance confirmée
- `15_level_k_reasoning.py` : cognitive hierarchy (Poisson λ) → 2 régimes (stable/spiral)
- `16_tournament_regret.py` : relative ranking vs top competitors
- `17_stress_test_2173.py` : contre-argumentation sur bid 2,173

### Raisonnement tournament-regret (clé)

Si on bid bas + top teams bid haut → on loose l'auction, eux gagnent → **on tombe
de ~V en ranking** (perte asymétrique non capturée par EV absolue).

Top 50-100 teams R2 (rang > 98%) : quasi-tous avec bid() + analyse de V →
distribution estimée mean 2,800, médiane 2,000 finale.

→ Bid > médiane top ⇒ bid ≥ 2,000.

### Focal point + anti-focal

2,000 = nombre rond focal → cluster de stratèges attendu.
Markup +173 (prime number) évite aussi les anti-focals 2,100, 2,500.

---

## 🏆 RECOMMANDATION FINALE — Bid = **2,173 XIRECs finale**

### Cheminement du raisonnement (6 étapes)

| # | Étape | Raisonnement | Bid |
|---|---|---|---|
| 1 | Break-even brut | V mesurée empiriquement | 11,194 |
| 2 | EV naïf (scénarios stables) | Monte Carlo médiane field central_eng | 500 |
| 3 | Tournament-regret | Si on loose ET top teams win → −V en classement | hedge nécessaire |
| 4 | Estimation top competitors | Top 50-100 R2 : 95% avec bid(), mean ≈ 2,800 | bid > 2,000 |
| 5 | Focal point | 2,000 = nombre rond, cluster de stratèges | markup +100 à +200 |
| 6 | Anti-focal prime | 2,173 (prime) évite clusters 2,100 / 2,500 | **2,173** |

### Economics

- **Coût si accepté** : 2,173 XIRECs
- **Gain si accepté** : V − bid = 11,194 − 2,173 = **+9,021** (80% de V captured)
- **Coût si rejeté** : 0 (first-price auction)
- **Marge au break-even** : 81% (9,021/11,194)

### Message Discord équipe (archivé)

> Break-even (V mesurée) = 11,194 finale. Bid proposé = 2,173.
> Hedge tournament-regret vs top 50-100 teams qui vont bidder ~2,000 mean.
> Markup anti-focal (+173, prime). Capture 80% de la value si accepté.

### Alternatives conservées (ne pas prendre mais documentées)

- **500** : optimal EV pur (sans effet tournoi) — mais perd relatif si top teams bident haut
- **5,000** : ultra-safe mais laisse 2,800 sur la table dans scénarios stables
- **Jamais > 11,194** : break-even absolu, au-delà = EV négatif garanti

### Implémentation

Ajouter dans `class Trader` du submission R2 :
```python
def bid(self):
    return 2173
```
