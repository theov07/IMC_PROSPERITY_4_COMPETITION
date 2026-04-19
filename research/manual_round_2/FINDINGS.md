# Manual Round 2 — "Invest & Expand" — Findings & Démarche

Date : 2026-04-19
Budget : 50,000 XIRECs, allouer entre 3 piliers (Research / Scale / Speed).

---

## 🏆 RECOMMANDATION FINALE (level-k adjusted)

### **Research = 12%  ·  Scale = 35%  ·  Speed = 53%**

- Research = 6,000 XIRECs → score **110,790**
- Scale    = 17,500 XIRECs → multiplicateur **×2.45**
- Speed    = 26,500 XIRECs → multiplicateur **~×0.78** (rank top ~15-20%)
- **Expected PnL ≈ +170,000 XIRECs**

**Pourquoi z=53 et pas z=50 ?**

Le raisonnement level-k (cognitive hierarchy) :
- **L1** (stratèges qui font notre analyse) → convergent vers z=50
- **L2** (anticipent que L1 converge sur 50) → vont à z=51-52
- **L3** (anticipent L2) → z=53+
- **z=53 = markup anti-focal 50 (+6%) + au-dessus du cluster L2 hypothétique à 52**
- Analogue au bid MAF à 2173 (markup +8.6% sur focal 2000)

**Coût du markup** : 1,500 XIRECs vs z=50 (= 0.9% de PnL)
**Gain potentiel** : si ~10-20% du field est L2+ à z=51-52, gain +20-40k

### Alternatives proches

| Profil | (x, y, z) | PnL | Quand choisir |
|---|---|---|---|
| **Reco (level-k aware)** | **(12, 35, 53)** | **+170k** | **Par défaut** |
| Reco L1 (base) | (13, 37, 50) | +171k | Si pas de level-k concern |
| Alternative R×S plus riche | (15, 45, 40) | +166k | Si field moins sophistiqué |
| Ultra-safe | (11, 29, 60) | +125k | Si field très sophistiqué |

---

## 📐 MÉTHODE & TECHNIQUES (détaillé)

### Techniques mathématiques utilisées

| Technique | Où utilisée | Pour quoi |
|---|---|---|
| **Conditions du premier ordre (KKT)** | scripts 01, 02 | Optimum analytique R/S : `(100-x)/(1+x) = ln(1+x)` → x≈23, y≈77 |
| **Grid search intégral** | scripts 02, 03, 08 | Exploration exhaustive sur `x ∈ [0, 100]`, `y ∈ [0, 100-x]`, `z ∈ [0, 100-x-y]` |
| **Monte Carlo sampling** | scripts 03, 04, 07 | Génération de fields synthétiques avec distributions variées |
| **Rank-based tournament model** | core.py | Modèle de speed avec ties partageant le rank (wiki-spec compliant) |
| **Error propagation / variance** | script 08 | Stabilité du best response sur 10 seeds (std ±750 PnL) |
| **Sensitivity analysis** | scripts 04, 08 | Variation des priors, n_teams, sophistication du field |
| **Cognitive hierarchy (Camerer-Ho-Chong)** | script 09 | Level-k reasoning : L0 naïf → L1 best response → L2 anticipate L1 → spiral |
| **Focal point theory (Schelling)** | script 05 | Identification des nombres ronds (25, 30, 33, 40, 50) comme points de coordination |
| **Iterated best response** | script 09 | Simulation L1→L2→L3 avec ajustement du field à chaque niveau |

### Pipeline en 8 étapes

**Étape 1 — Vérification formules (script 01)**
Technique : comparaison numérique wiki vs UI.
Confirme : `Research(40) = 160,944 ≈ UI 160,931`, `Scale(25) = ×1.75 ≈ UI ×1.8`.

**Étape 2 — Optimum analytique R/S (script 02)**
Technique : conditions du premier ordre sur `R(x) × S(y) × m − cost`. À m fixé et B_xy=100, l'équation `(100-x)/(1+x) = ln(1+x)` donne x≈23, y≈77.
Généralisation : même ratio R/S ≈ 0.35 pour tout B_xy.

**Étape 3 — Quantifier Speed impact**
Technique : calcul de `max PnL` sous m fixé.
Résultat : m=0.1 → PnL 24k vs m=0.9 → PnL 618k (facteur 25× !).

**Étape 4 — Tournament best response (script 03)**
Technique : pour chaque distribution adverse (10 tested), grid search sur z, calcul de rank, m, PnL.
Résultat : best z varie de 0 (all coord) à 58 (competitive N(50,15)).

**Étape 5 — Ensemble sous priors (script 04)**
Technique : Monte Carlo sur 6 scénarios avec poids subjectifs, moyenne pondérée du PnL attendu.
Résultat : ensemble-optimal z=37, PnL 221k (MAIS priors inventés).

**Étape 6 — Focal matching (script 05)**
Technique : cluster scenarios (20-40% à chaque focal), best response par cluster.
Observation : plateau PnL plat autour du focal, marge d'erreur faible.

**Étape 7 — Data-driven field (script 07)**
Technique : sophistication tiers basés sur leaderboard R1 global + France + R2 aggregate.
Chaque tier (TOP/UPPER_MID/MID/LOWER_MID/BOTTOM) a sa distribution Speed.
Résultat field : mean=40.3, median=40, p25/p75=30/50.

**Étape 8 — Level-k reasoning (script 09)**
Technique : cognitive hierarchy simulation.
Iteration L0→L1→L2→L3 avec injection de stratèges au z optimal du niveau précédent.
Résultat : L1 converge à z=50, L2 stable à 50, L3 → z=51-52, spiral borné par self-limit.

---

## 📖 Lexique — termes techniques utilisés

| Terme | Explication |
|---|---|
| **Fonction de coût** | `PnL = R(x) × S(y) × Speed(rank) − Budget_Used`. C'est ce qu'on cherche à maximiser. |
| **Pillar formulas** | Fonctions mathématiques des 3 piliers (log pour R, linéaire pour S, rank-based pour Speed). |
| **Focal point** | Nombre "naturel" sur lequel beaucoup de gens convergent sans concertation (25, 30, 33, 40, 50). Vient de la théorie des jeux (Schelling). |
| **Rank-based tournament** | Jeu où ton score dépend de ta position relative, pas absolue. Ici Speed = rang dans le pool des submitters. |
| **Tie (égalité)** | Si plusieurs teams investissent le même montant, elles partagent le même rank → même multiplicateur Speed. |
| **Best response** | Meilleure action face à un comportement supposé des autres (ici : meilleur z face à une distribution adverse donnée). |
| **Nash equilibrium** | Configuration où personne ne peut améliorer unilatéralement. `z=0 pour tous` est Nash mais fragile. |
| **Ensemble-optimal** | Action qui maximise l'espérance PnL sous une distribution de probabilités sur plusieurs scénarios. |
| **Sophistication tier** | Modélisation qui regroupe les teams par niveau stratégique (TOP/UPPER_MID/MID/LOWER_MID/BOTTOM) pour prédire leur allocation Speed. |
| **Data-driven** | Calibré à partir des données réelles (leaderboards R1+R2), par opposition à "guesses". |
| **Scale-invariant** | Le résultat ne dépend pas de la taille du denominator (3k ou 10k). |

---

## 🧭 Démarche en 8 étapes

### Étape 1 — Vérifier les formules du wiki (script 01)

Vérification que les formules correspondent à l'UI du jeu :
- `Research(40)` = 160,944 vs UI = 160,931 ✓
- `Scale(25)` = ×1.75 vs UI = ×1.8 (rounded) ✓
- `Speed` = linear interpolation entre 0.9 (top rank) et 0.1 (bottom rank)

### Étape 2 — Trouver le ratio optimal Research/Scale (script 02)

Grid search sur (x, y) avec Speed multiplicateur fixé : **x:y = 23:77 à budget plein**.

Intuition : Research est log-concave (saturant), Scale est linéaire. Quand on a plus de budget à donner, on le donne à Scale (marginal constant) plutôt qu'à Research (marginal décroissant).

### Étape 3 — Comprendre que Speed domine tout (script 02 + 03)

Avec (x, y) optimal et budget plein :
- m = 0.1 (bottom rank) → PnL = +24k
- m = 0.5 (middle rank) → PnL = +321k
- m = 0.9 (top rank) → PnL = +618k

→ **Facteur 25× entre bottom et top rank.** Speed = décision dominante.

### Étape 4 — Modéliser Speed comme un tournoi (script 03)

Pour chaque distribution adverse plausible, trouver notre best response :
- `all_zero` → best z=0 (PnL 618k, Nash coop)
- `uniform(0, 100)` → best z=39 (PnL 114k)
- `normal(30, σ=10)` → best z=40 (PnL 250k)
- `mostly_low (exp 15)` → best z=21 (PnL 341k)
- `normal(50, σ=15)` → best z=58 (PnL 111k)

Conclusion : le best z est **très sensible à la distribution supposée**.

### Étape 5 — Premier essai : ensemble-optimal sous priors (script 04)

Mix de priors arbitraires : 25% mostly_low + 30% normal(30) + 20% focal 33 + etc.
Résultat : ensemble-optimal z=37, PnL ~221k.

**Problème identifié** : ces priors sont des guesses non fondés sur la data.

### Étape 6 — Focal points matter (script 05)

Scan de clusters à 20, 25, 30, 33, 40, 50 avec fractions 20-40% :
- Matcher le plus gros focal = tie au même rank = même m sans surpayer
- Si 30% cluster à 33 : best response = 33 (tie) ou 34 (juste au-dessus)
- Le landscape PnL est très plat dans la zone focal-33 à focal-40 (plateau)

### Étape 7 — Rebuild data-driven avec leaderboards (script 07)

**Critique reçue : mes distributions étaient inventées.** Rebuild avec :
- R1 global leaderboard (600 teams de `round_2_MAF/data/leaderboard_r1_global_merged.csv`)
- R1 France (207 teams)
- R2 backtest (3,065 submitters de `r2_backtest_leaderboard_aggregate.json`)

Modèle de sophistication par tier (TOP 5% / UPPER_MID 5-30% / MID 30-60% / LOWER_MID 60-85% / BOTTOM 15%), chaque tier ayant une distribution de Speed distincte.

Field empirique résultat : **mean 40.3, median 40, p25/p75 = 30/50**.

### Étape 8 — Best response data-driven final (script 08)

Face à ce field plus sophistiqué, best z glisse vers **50** (plutôt que 33 ou 40 comme suggéré initialement). Vérifications :

- **Scale-invariance** : n=1k / 3k / 5k / 10k → toujours z=50
- **Sophistication sensitivity** :
  - naive_dominated : z=40, PnL=169k
  - default (data-driven) : **z=50, PnL=171k**
  - sophisticated_dominated : z=50, PnL=185k

---

## 📊 Scénarios testés (quantifiés)

### Scénarios distributions adverses simples (script 03/04)

| # | Scénario | Distribution | Best z | PnL |
|---|---|---|---|---|
| 1 | all_zero | tous = 0 | 0 | +618k |
| 2 | all_ten | tous = 10 | 10 | +532k |
| 3 | all_thirty | tous = 30 | 30 | +368k |
| 4 | mostly_low | exp(μ=15) | 21 | +341k |
| 5 | normal_30 | N(30, σ=10) | 40 | +250k |
| 6 | normal_50 | N(50, σ=15) | 58 | +111k |
| 7 | uniform_0_100 | U(0, 100) | 39 | +114k |
| 8 | bimodal | 50% low 50% high | 14 | +255k |
| 9 | competitive_heavy | N(50, σ=15) | 53 | +110k |

### Scénarios focal points (script 05)

Teste ce qui arrive si X% du field cluster à un round number :

| Focal | Frac cluster | Best response | PnL |
|---|---|---|---|
| 30 | 20%, 30%, 40% | 30-40 | 273-287k |
| 33 | 20%, 30%, 40% | 33-38 | 275-282k |
| 40 | 20%, 30%, 40% | 40 (match) | 267-274k |
| 50 | 20%, 30%, 40% | 50 (match) | 216k |

### Scénarios data-driven (scripts 07-08)

| Field sophistication | Mean field | Best z | PnL |
|---|---|---|---|
| naive_dominated (LOWER_MID + BOTTOM) | 39.3 | 40 | +169k |
| **data-driven (tiers from leaderboard)** | **40.3** | **50** | **+171k** |
| sophisticated_dominated (TOP + UPPER_MID) | 39.4 | 50 | +185k |

**Robustesse sur 10 seeds** : best z reste stable à 40-50 selon le seed et la sophistication.

---

## ⚙️ Architecture du code

### `core.py` — fonction de coût centralisée
```python
research(x)           # 200,000 × ln(1+x)/ln(101)
scale(y)              # 7 × y/100
speed_mult_from_rank(rank, N)   # 0.9 - 0.8×(rank-1)/(N-1)
compute_rank(my_z, others)       # ties share rank
compute_pnl_vs_field(my_z, others)   # full pipeline
find_best_response(others)           # grid search z ∈ [0, 100]
```

### Scripts
- `01_pillar_formulas.py` — vérification formules
- `02_optimal_allocation_fixed_speed.py` — grid (x,y,z) pour m exogène
- `03_speed_tournament.py` — best response vs adversary distributions
- `04_robust_bid_under_uncertainty.py` — ensemble sous priors (inventés)
- `05_focal_point_matching.py` — clustering aux focals
- `06_final_recommendation.py` — rapport consolidé version 1 (obsolète, basé sur mes guesses)
- `07_data_driven_field.py` — field construit avec leaderboard R1/R2
- `08_final_recalibrated.py` — rapport consolidé version 2 (data-driven, final)

### Data externe réutilisée (depuis `research/round_2_MAF/data/`)
- `leaderboard_r1_global_merged.csv` (600 teams R1 global)
- `leaderboard_r1_france.csv` (207 teams FR)
- `r2_backtest_leaderboard_aggregate.json` (stats 3,065 R2 submitters)

---

## 🎯 Verdict & raisonnement final

### Pourquoi **z=50** (et pas 33 comme d'abord proposé)

1. **Field plus sophistiqué que mon premier modèle naïf le pensait**
   - Data-driven : median 40 (pas 30-33)
   - Tiers UPPER_MID et TOP tirent le field vers le haut
2. **Matcher ou battre la médiane du field est la priorité** (pour ne pas être en bottom-half speed)
3. **Plateau PnL très plat dans la zone 40-50** → marge d'erreur correcte
4. **z=50 = focal naturel** (moitié du budget)
5. **Robuste à la sophistication** : seul le scénario "naive_dominated" pousse légèrement vers z=40

### Pourquoi pas **z=0** (Nash coopératif)

Pareto-optimum (tous à 0 → tous m=0.9 → tous 618k) mais **fragile** :
- 3,000+ teams sans coordination
- Dès qu'un team défecte à 1, les autres tombent à m=0.1
- Dominant de défecter → l'équilibre ne tient pas

### Pourquoi pas **z=60+** (ultra-safe)

- Research × Scale trop réduits
- z=60 → PnL 125k (moins que z=50 à 171k)
- z=70 → PnL 82k
- z=100 → PnL −50k

Overbid Speed est presque aussi coûteux que underbid.

---

## ⚠️ Caveats

1. **Modèle de sophistication par tier est une abstraction** — aucune data directe sur les intentions Speed des teams, seulement proxy via rang R1.
2. **Le default UI n'existe pas** (confirmé par Léo) — notre premier modèle avait un biais vers 35 qui a été corrigé.
3. **Variance attendue** : rank exact ± 150 → m ± 0.05 → PnL ± 15-20k.
4. **Speed multiplier "infinite precision"** (wiki FAQ) : les multiplicateurs réels peuvent légèrement différer des valeurs arrondies qu'on voit dans l'UI.
5. **Manual submitters ≠ trader.py submitters** : on assume 3,065 (même ordre de grandeur) mais pourrait être différent. Scale-invariance confirme que ça ne change pas la reco.

---

## 🔁 Alternatives documentées

| Profil | (x, y, z) | PnL attendu | Quand choisir |
|---|---|---|---|
| **Principal** | **(13, 37, 50)** | **+171k** | Reco data-driven, plus robuste |
| Alternative EV proche | (15, 45, 40) | +166k | Si tu penses field moins sophistiqué |
| Focal 33 | (17, 50, 33) | +147k | Si tu crois forte coordination sur 33 |
| Conservateur | (11, 29, 60) | +125k | Si field ultra sophistiqué (pas nécessaire) |
| Pari Nash coop | (23, 77, 0) | +618k ou +24k | Trop risqué sans coordination |

---

## 📝 Format submission

Dans l'interface du jeu :
```
Research : 13
Scale    : 37
Speed    : 50
(Total 100%)
```
