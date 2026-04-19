# MAF — Findings & Break-even Bid

Date : 2026-04-19
Strategy : `champion_19april_am` (v4_F5 OSM + Theo v4 IPR shift=85)

---

## TL;DR

⚠️ **Attention aux unités** : live PnL = simu-test XIRECs, bid MAF = simu-finale XIRECs
(scaling ×8.9 empirique R1 : 12k test → 107k finale)

- **Gain MAF en simu-test : +1,258 ± 338 XIRECs_test (+12.4% du PnL live)**
- **Gain MAF en simu-finale : +11,194 ± 3,007 XIRECs_finale**
- **Break-even bid (finale, là où on paie) : 11,194 XIRECs**
- **Conservateur (−1σ, finale) : 8,186 XIRECs**
- **100% du gain vient d'OSM** — IPR (Theo v4 far-quote) profite pas du +25% de flow

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

## Recommandation finale (en XIRECs **finale**, là où se paie le bid)

🏆 **Bid dans la zone 8,000 — 13,000 XIRECs_finale**

- **8,000** : conservateur (−1σ, couvre variance live + uplift)
- **11,194** : break-even (EV = 0 si gagné)
- **13,000** : plafond max (garde marge si uplift live < backtest)

Au-delà de 17k, EV négatif même dans le meilleur scénario observé.
En-dessous de 5k, on laisse énormément de value sur la table.

⚠ Ce break-even est **indépendant de la médiane adverse** — c'est le point où
notre EV = 0 **si on gagne l'auction**. L'optimal sous first-price doit intégrer
`P(accepté)` et sera **plus bas** (voir phase recherche médiane adverse à venir).
