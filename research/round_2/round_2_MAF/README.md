# MAF Bid Optimization — Round 2

Scripts de pricing du Market Access Fee et d'optimisation du bid.

## Contexte

En R2, IMC fait une auction à l'aveugle pour +25% de volume dans le carnet :
- Top 50% des bidders acceptés → paient leur propre bid (first-price)
- Bid ignoré si négatif (→ 0)
- Teams sans trader.py ignorées, teams sans `bid()` → comptées comme 0
- Bid en unités **simu finale**, déduit du PnL R2 final

## Pipeline (4 scripts)

### `01_generate_synthetic_data.py`
Génère des datasets synthétiques avec **+25% de volume** via Monte Carlo.
- Injecte des quotes dans les gaps du carnet (entre L1-L2)
- Volumes tirés de la distribution empirique
- Plusieurs seeds pour variance

```bash
python research/round_2/round_2_MAF/01_generate_synthetic_data.py --seed 42 --n_seeds 5
# → data/round_2_synthetic_s42/, s43/, ...
```

### `02_measure_delta_pnl.py`
Mesure **V = ΔPnL(enriched − baseline)** via backtest.
- Baseline : données R2 normales
- Enriched : datasets synthetic (pour chaque seed)
- Scaling ×10 vers finale

```bash
python research/round_2/round_2_MAF/02_measure_delta_pnl.py \
    --strategy champion_19april_am \
    --seeds 42,43,44
```

### `03_bid_optimization.py` + `03b_sensitivity_analysis.py`
Modélise la distribution des bids adverses + trouve le bid optimal.
- Modèle : mixture (35% no bid, 25% wiki-copy, 15% round small, etc.)
- Sensitivity sur 7 scénarios différents
- Robust bid = 75e percentile des optima

```bash
python research/round_2/round_2_MAF/03_bid_optimization.py --V 10000
python research/round_2/round_2_MAF/03b_sensitivity_analysis.py
```

### `04_final_report.py`
Rapport consolidé combinant les 3 précédents.

```bash
python research/round_2/round_2_MAF/04_final_report.py --V 10000
```

## Résultats — Verdict

### V (valeur du MAF pour nous)

Mesuré sur champion_19april_am :
- Synthetic ratio effective : 1.37 (vs 1.25 target)
- ΔPnL simu test : **+1,277 ± 216** XIRECs
- **V scaled finale : +12,767 ± 2,159** XIRECs
- Corrigé pour ratio 1.25 exact : **V ≈ 8,600 — 12,800 finale XIRECs**

### Distribution adverse (mean over 7 scenarios)

| Scenario | Median adverse |
|---|---|
| Base (35% no-bid) | 18 |
| Many lazy (60% no-bid) | 0 |
| Few lazy (15%) | 75 |
| Wiki super sticky | 19 |
| Serious teams only | **1,800** |
| Value-anchored high | 841 |

### Optimum (V = 10,000)

| Approche | Bid |
|---|---|
| Risk-taker (trust base model) | 50 |
| **Balanced (robust 75e percentile)** | **1,226** |
| Ultra-safe | 3,000 — 5,000 |

## Recommandation finale

### 🏆 Bid = 1,200 — 1,500 XIRECs

- Beats median dans 75% des scénarios adverses
- Capture ~87% de la valeur V si accepté (V=10k: gain net ~8,800)
- Downside : max 1,500 (si on est accepté mais V sous-estimé)
- Robuste à l'incertitude sur la distribution réelle

### Variantes

- **Agressif** si confiance haute dans V (→ 500-1000)
- **Défensif** si peur teams sérieuses (→ 2,500-3,000)

## ✅ V mesurée via méthode 80% subsampling (2026-04-19)

**Insight Leo** : live IMC sample ~80% du book → MAF (+25%) ramène à ~100%
(= conditions backtest). Donc uplift MAF = `PnL(100%) / PnL(80%)`.

Pipeline reproductible (scripts 05 → 08) :

| Script | Rôle |
|---|---|
| `05_subsample_80pct.py` | Thinning binomial des volumes à p=0.8 (book + trades) |
| `06_estimate_maf_live_gain.py` | Backtest 100% vs 80%, ratios uplift par produit |
| `07_parse_live_logs.py` | Parse les logs IMC R2 → PnL final par run et par produit |
| `08_maf_breakeven_report.py` | Consolide logs + uplift → gain MAF + break-even bid |

### Résultats (champion_19april_am, 3 seeds subsample, 8 logs live)

**Uplift ratios 100%/80% (backtest realistic) :**
- OSM : ×1.488 (**+48.8%**) — std ±2.5%
- IPR : ×1.0004 (**+0.04%**) — quasi-nul (Theo v4 profite pas du +25% car far-quote sur empty-book events)
- TOTAL : ×1.074 (+7.4%) — dilué par IPR

**PnL live observé (logs IMC R2) :**
- OSM mean = 2,571 ± 680 XIRECs (n=6)
- IPR mean = 7,677 ± 298 XIRECs (n=4)
- Combined total mean = 10,155 ± 333 XIRECs (n=2)

**Gain MAF live estimé :**
- OSM : +1,255 ± 338
- IPR : +3 ± 3
- **TOTAL : +1,258 ± 338 XIRECs** (+12.4% du PnL live total)

### 🏁 Break-even bid = **1,258 XIRECs**

- bid < 1,258 → net positif en espérance (si auction gagnée)
- Conservateur (−1σ) : **920 XIRECs**
- Bracket scénarios : 923 — 1,770

**Hypothèse critique** : p_keep = 0.8 (sampling live IMC). À tester avec 0.75 / 0.85.

---

## ⚠️ Ancienne approche (script 01-04) — méthode synthétique +25%

**Script 01 enrichit uniquement le CARNET (prices CSV), PAS les TRADES.**

- MAF wiki : +25% de **flow total** (quotes passifs + trades agressifs)
- Notre synthetic : +25% book depth seulement → trades inchangés
- Backtest `realistic` fill model : fills majoritairement trades-driven
- → V mesuré (+0.27%) est **significativement sous-estimé**

**Fix needed** : modifier `01_generate_synthetic_data.py` pour dupliquer ~25% des
lignes de `trades_round_2_day_X.csv` (avec jitter timestamp, prix/vol tirés de
la distribution empirique) puis re-run script 02.

## Caveats & limitations

1. **Synthetic data accuracy (book)** : ratio 1.296 vs 1.25 target (léger overshoot)
   - Generation probabiliste en place, overshoot résiduel faible

2. **Adversary model first-principles** : pas d'accès web au leaderboard
   - Modèle basé sur fractions estimées de types d'équipes
   - Sensitivity analysis couvre 7 scénarios pour robustesse

3. **V peut varier dans le temps** :
   - Plus de volume = plus de fills MM = linéaire
   - Mais diminue les OB-empty events → dégrade alpha far-quote
   - Net effect à re-measurer sur jours différents si possible

4. **Backtest scaling** : test → finale ≈ 10×
   - Confirmé empiriquement sur R1 champion (12k test → 107k finale)
   - Mais peut varier selon les régimes de marché

## Files produits

- `data/round_2_synthetic_s{42,43,44}/` : datasets synthetic (commités ? à vérifier)
- Logs scripts 2/3/4 : stdout only, pas persistés

## Next steps (si temps)

1. Raffiner synthetic data pour atteindre exactement 1.25 ratio
2. Générer 10-20 seeds pour tighter V estimate
3. Re-grid-search strategy params sur synthetic data (la strat pourrait se comporter différemment avec +25%)
4. Split V par produit (OSM vs IPR) pour décision MAF différenciée
