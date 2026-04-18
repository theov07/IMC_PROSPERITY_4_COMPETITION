# Leo vs Tibo — ASH_COATED_OSMIUM uniquement (Round 2)

Backtest 3 jours R2 (days -1, 0, 1), match-trades `realistic`.

---

## 0. Glossaire — termes utilisés dans la note

### Mécanique du book

- **Tick** : unité minimale de prix (ici 1 unité). Un "tick" c'est aussi une itération de la stratégie (toutes les 100ms dans IMC).
- **Bid / Ask** : meilleur prix qu'on est prêt à **payer** (bid, côté achat) / à **recevoir** (ask, côté vente). Le bid est toujours ≤ ask.
- **Spread** : `best_ask − best_bid`. Un spread de 2 = le marché fait payer 2 ticks pour croiser instantanément.
- **L1 / L2** : Level 1 = meilleure price (top of book). Level 2 = deuxième meilleur. `best_bid` est L1 côté achat.
- **Mid** : `(best_bid + best_ask) / 2`. Pseudo-juste-prix simplifié.
- **Microprice** : mid pondéré par les volumes aux meilleurs niveaux. Meilleur proxy du "fair value" quand le book est déséquilibré.

### Ordres

- **Maker / passive** : poster un ordre à un prix qui **ne croise pas** le book (bid < best_ask, ask > best_bid). On attend qu'un taker vienne nous hitter. On paye pas le spread, on le **capture**.
- **Taker / aggressive** : croiser le book (acheter à best_ask, vendre à best_bid). On paye le spread mais on est sûr de filler.
- **Penny-improve** : poster 1 tick à l'intérieur du best (bid = best_bid+1, ask = best_ask−1). Prend la place de top queue mais perd 1 tick de spread vs join.
- **Join best** : poster au même prix que le best (bid = best_bid). Garde l'edge maximal mais dernier dans la queue d'exécution.
- **Crossing prevention** : éviter que notre bid_price ≥ ask_price — sinon on shoot contre nous-même.

### Prix de référence

- **EWMA** (Exponentially Weighted Moving Average) : moyenne glissante où les ticks récents pèsent plus. Paramétrée par `half_life` (nb de ticks pour qu'un poids soit divisé par 2). `mid_smooth` chez Tibo = EWMA du mid.
- **Anchor price** : prix de référence **fixe** (ici 10,000 pour OSMIUM) qu'on pense être le centre autour duquel le produit oscille. Différent d'un EWMA qui suit le marché.
- **Fair value** (fv) : notre estimation du "juste prix" à l'instant t. Peut être mid, mid_smooth, anchor, output de régression, etc.

### Signaux

- **Mean-reversion** : pari que le prix va **revenir à la moyenne** s'il s'en écarte. Utile pour produits qui oscillent (OSMIUM).
- **Momentum / trend** : pari que le prix va **continuer dans la même direction**. Utile pour produits qui drift (IPR +1000/jour).
- **Anti-momentum** (ou contrarian) : l'inverse — on pense qu'un mouvement ponctuel va s'inverser. `ar_shift` chez moi : si le prix saute de +3 au tick t, on parie sur −3 au tick t+1.
- **Z-score** : `(mid − rolling_mean) / rolling_std`. Nombre d'écarts-types de distance. |z| > 2 = évènement rare. Chez Tibo, utilisé pour sizing tilt (boost du côté mean-rev).
- **Sigma / volatility** : écart-type des returns sur une fenêtre. Sert à ajuster take_edge (plus de vol → plus d'edge requis).

### Régression (côté IPR, pour comprendre)

- **OLS** (Ordinary Least Squares) : régression linéaire classique. `mid ≈ slope × t + intercept`.
- **Block regression** : on groupe les ticks en blocs (ex: 200 ticks) et on régresse sur les derniers blocs complets. Plus stable qu'un OLS glissant.
- **Residual / residual_z** : écart entre le prix observé et la prédiction de la régression. residual_z = résidu standardisé. Signale si le prix est cher/bon marché **par rapport au trend**.
- **Seed slope** : pente initiale injectée avant d'avoir assez de blocks pour estimer une pente fiable.

### Inventaire / position

- **Position** : nombre d'unités qu'on détient (positif = long, négatif = short). Bornée par `position_limit` (80 chez IMC).
- **Inventory ratio** : `position / limit`. Entre −1 et +1.
- **Inv_target** : la position qu'on **veut** détenir à un instant donné (driven par le signal). Different de la position actuelle.
- **Unwind** : réduire une position existante (vendre ses longs, racheter ses shorts). "Unwind_take_edge" = rendre plus facile d'agresser pour se rapprocher de inv_target.
- **Pressure** : `|position − inv_target| / limit`. Mesure à quel point on est loin de la cible. Plus c'est haut, plus on veut unwinder.
- **Aggravate** : l'inverse d'unwind. Ajouter à une position existante dans la direction où on a déjà du risque. Généralement on veut l'éviter (sauf si le signal est fort).
- **Inv_soft_ratio** : seuil de pressure au-delà duquel on commence à tordre les sizes (shrink côté aggravant, boost côté unwind).

### Flow et adverse selection

- **Adverse selection** : se faire filler par quelqu'un qui a une meilleure info que nous. Symptôme : on achète juste avant que le prix baisse, on vend juste avant qu'il monte. Coût caché du market-making.
- **Toxic flow** : flux d'ordres directionnel qui signale qu'un gros trader a de l'info. Ex: 5 trades buys consécutifs au best_ask → le prix va probablement monter → si on a un ask posté on se fait adverse-select.
- **Flow score** : métrique qui quantifie la directionalité du flow récent. `(buys − sells) / total` sur une fenêtre.
- **Jump** : saut ponctuel du best_bid ou best_ask d'un tick. Signe qu'un trader a agressé. Indicateur court terme d'adverse selection.

### Gap exploit (ton mécanisme)

- **Gap** : écart entre L1 et L2 d'un côté. Si best_bid=10,010 et bid_L2=10,000, gap = 10.
- **Thin L1** : le L1 a peu de volume (ex: 5 unités quand limit=80).
- **Gap exploit** : quand L1 est thin ET gap ≥ seuil, on **balaye L1 aggressivement** pour que le book s'aplatisse, puis on poste un passif au niveau L2±1. Capture un gros spread si quelqu'un nous hit avant que le book se reremplisse.
- **Re-anchor** : après avoir balayé L1, recalculer où poster notre passif en utilisant le **vrai** best actuel (L2), pas l'ancien best qu'on vient de bouffer.

### Autres

- **Skew** : décaler bid et ask dans la même direction pour biaiser l'exposition. Ex: skew−1 = bid−1 et ask−1 → on préfère vendre.
- **Take_edge** : edge minimum (en ticks) requis vs fair_value pour déclencher un taker. Plus haut = plus sélectif, moins de fills mais meilleurs.
- **Dynamic take_edge** : `take_edge` qui varie avec la volatilité (edge plus haut en haute vol pour pas se faire baiser).
- **Sizing** : déterminer combien d'unités poster. `base_size` modulé par inventory, z-score, toxic flow, etc.
- **Half-life** : durée (en ticks) après laquelle un poids dans un EWMA est divisé par 2. `half_life=10` avec window=50 → les 10 derniers ticks pèsent ~50% du total.

---

| Stratégie | OSMIUM PnL | Trades | Volume | Make | Take | Avg inv ratio |
|---|---|---|---|---|---|---|
| **leo_round2_v1** (`osmium_mr`) | **61,043** | 2034 | 11,185 | 6,582 | 4,603 | 0.42 |
| tibo_round2_v1 (`mm_first_v2`) | 57,992 | 1994 | 10,760 | 6,780 | 3,980 | 0.56 |
| **Δ Leo − Tibo** | **+3,051** | +40 | +425 | −198 | +623 | −0.14 |

Donc Leo **+3k sur OSMIUM** avec inventaire plus neutre (0.42 vs 0.56) et takers plus fréquents (+623 take fills).

---

## 1. Ta stratégie (`mm_first_v2`)

Market maker penny-improve modulaire. Ton `compute_orders` orchestre :

1. `_compute_quote_prices` → bid = best_bid+1, ask = best_ask−1 (L1)
2. `_compute_zscore` → rolling z-score du mid sur 50 ticks
3. `_update_volatility` → sigma EWMA
4. `_compute_sizes` → inventory-adaptive (bid_size shrink quand long)
5. `_zscore_size_factors` → tilt sizes si |z| > 1
6. `_dynamic_take_edge` → interpole take_edge entre `take_edge_lo=0.7` et `take_edge_hi=1` selon sigma
7. `_fire_takers` → agresse si `ask ≤ mid_smooth − take_edge` ou `bid ≥ mid_smooth + take_edge`
8. `_gap_exploit` → balaye L1 fin si gap L1→L2 ≥ 10 + re-anchor
9. `_passive_quotes` → post bid/ask passifs

**Référence de prix** : `mid_smooth` = EWMA(mid, half_life=10). C'est le "fair value" implicite.

**Hypothèse de base** : le mid EWMA est le juste prix. On tilt autour via z-score pour le sizing et on agresse sur les déviations ponctuelles.

---

## 2. Ma stratégie (`osmium_mr`)

Mean-reversion autour d'un **anchor fixe = 10,000** avec plusieurs couches de signal. Monolithique mais lisible.

### Couche 1 — Signal trend_shift
```python
raw_signal = anchor_price − mid               # ancre fixe 10,000
trend_shift = clip(raw_signal × 0.6, ±5)      # trend_sensitivity=0.6, max_shift=5
inv_target = clip(trend_shift × 12, ±80)      # inv_target_per_tick=12
adjusted_mid = mid + trend_shift
```
Quand mid = 10,012 → `trend_shift = −5` → `adjusted_mid = 10,007`, `inv_target = −60` (je veux être short 60).

**Différence-clé avec toi** : ta référence est `mid_smooth` (EWMA qui suit le prix). La mienne est **fixe à 10,000**. Si OSMIUM reste 500 ticks à 10,020 :
- Ton `mid_smooth` converge vers 10,020 → tu penses que 10,020 est le bon prix, tu n'agresses plus.
- Mon anchor reste à 10,000 → je continue à parier sur le retour.

### Couche 2 — AR shift (le vrai edge)
```python
ar_shift = −ar_gain × (mid_t − mid_t−1)       # ar_gain=0.6
anchor_price += ar_shift / trend_sensitivity
```
Si le mid saute de +3 ticks au tick t, l'ancre descend de ~5 au tick t+1 → je renforce le pari sur un retour.
C'est un filtre **anti-momentum court terme** : les sauts ponctuels se reversent statistiquement.

### Couche 3 — Takers asymétriques vs inventaire
```python
if position < inv_target:   buy_edge  −= unwind_take_edge × pressure   # plus agressif pour acheter
elif position > inv_target: sell_edge −= unwind_take_edge × pressure
```
Je ne prends pas juste pour capturer de l'edge — je prends **pour me rapprocher de l'inventory cible**. Tu n'as pas ça dans `_fire_takers` (ton edge est symétrique).

### Couche 4 — Tighten + crossing prevention
```python
if spread ≥ 2:
    bid = min(real_best_bid + 1, real_best_ask − 1)   # penny-improve mais cappé
    ask = max(real_best_ask − 1, real_best_bid + 1)
else:
    bid = real_best_bid      # join au spread 1
    ask = real_best_ask
```
Identique à toi sauf que j'utilise le **"real best"** (post-taker) : si j'ai balayé le L1, le real_best devient L2 → je re-anchor proprement.

### Couche 5 — Inventory sizing adaptatif
```python
pressure = |position − inv_target| / limit
if pressure > inv_soft_ratio (0.7):           # zone rouge
    scaled = (pressure − soft_ratio) / (1 − soft_ratio)
    aggravate_frac = 1 − 0.8 × scaled         # coupe la size côté aggravant
    unwind_mult    = 1 + 0.3 × scaled         # boost la size côté unwind
```
Quand je suis à position=+70 et inv_target=−60 (pressure=1.0), ma buy_size est divisée par 5 et ma sell_size est multipliée par 1.3. Ton z-score fait un truc similaire mais basé sur le mid (pas sur l'écart position vs target).

### Couche 6 — Toxic flow gate
Buffer des 6 dernières trades qui croisent le book :
```python
flow_score = Σ(signed_qty) / Σ(|qty|)
if flow_score > 0.6 and je veux vendre: sell_size ÷= 4
if flow_score < −0.6 and je veux acheter: buy_size ÷= 4
```
Si Caesar/Valentina spam des buys depuis 6 ticks, je réduis ma sell_size pour ne pas me faire adverse-select.

### Couche 7 — Jump size reduction
```python
if best_bid a sauté de +1 tick (signe d'aggressive buy):
    sell_size ÷= 2   # sauf si mon trend_shift dit que ça va continuer
```
Protège contre les whiffs momentary.

---

## 3. Ce que ton template n'a pas (et qui me rapporte +3k)

| Mécanisme | Tibo | Leo | Valeur R2 OSMIUM |
|---|---|---|---|
| Référence prix | mid_smooth EWMA | anchor fixe 10,000 | +++ |
| AR shift (anti-momentum 1-tick) | non | oui (ar_gain=0.6) | ++ |
| Takers asymétriques vs inventory | non (symétrique via take_edge) | oui (unwind_take_edge pressure) | ++ |
| Toxic flow gate (flow_history buffer) | non | oui | + |
| Jump size reduction | non | oui | + |
| Inventory sizing par écart à cible | via z-score sur mid | via écart position−inv_target | = |
| Gap exploit modulaire | **oui, très propre** | oui mais inline | ce qu'il me manque |
| Z-score skew passif | oui | non | probablement = (désactivé chez toi aussi) |

---

## 4. Diagnostic par grid search (R2 days -1, 0, 1)

J'ai tourné 5 grid searches sur `osmium_mr`, résultats :

| Grid | Plage | Optimum | OSMIUM |
|---|---|---|---|
| baseline | — | (défauts) | 61,043 |
| gs1 | take_edge × ar_gain (20 cells) | take_edge=1.5, ar_gain=0.3 | 61,858 |
| gs2 | zoom (20 cells) | confirme | 61,858 |
| gs3 | trend_sensitivity × trend_inv_target (16 cells) | défauts déjà optimaux | 61,858 |
| gs4 | inv_soft × toxic_th (20 cells) | inv_soft=0.8 | 61,880 |
| gs5 | inv_soft × aggr_min × unwind_boost (48 cells) | inv_soft=0.9, aggr_min=0.2 | **61,899** |

**Paliers** : le vrai edge sur R2 OSMIUM vient de (1) anchor fixe + AR shift, (2) inv_soft élevé (0.9 vs 0.6 par défaut), (3) ar_gain modéré (0.3 au lieu de 0.6). Take_edge peut passer de 1.75 à 1.5 pour prendre un peu plus.

**Plateau à ~61.9k** : au-delà, gains marginaux (<30 pts par tweak). Le reste du PnL OSMIUM se gagnerait en repensant l'archi (ex. reprendre ton `_gap_exploit` modulaire, ajouter skew passif sous conditions).

---

## 5. Proposition de fusion

Ton archi modulaire + mes couches = meilleur des deux :

```
MMFirstStrategy (Tibo) ────┐
   ├── _compute_quote_prices
   ├── _compute_zscore
   ├── _compute_sizes
   ├── _fire_takers          ← à enrichir (takers asymétriques via inv_target)
   ├── _gap_exploit          ← garder tel quel, excellent
   └── _passive_quotes

OsmiumMRStrategy (Leo, porté dans ton archi):
   extends MMFirstStrategy
   + _compute_anchor_signal(mid, anchor)  → (trend_shift, inv_target)
   + _apply_ar_shift(mid, memory)         → shift anchor
   + _toxic_flow_gate(memory, trades)     → size multipliers
   + _jump_size_gate(book, memory)        → size multipliers
   override _fire_takers → ajoute le bias `unwind_take_edge × pressure`
```

→ Proprement modulaire, réutilisable pour n'importe quel produit mean-reverting, et je garde mes +3k OSMIUM.

---

**TL;DR** : ton `mm_first_v2` est 95% du chemin pour OSMIUM. Les 3k qui me manquent chez toi viennent (a) **anchor fixe au lieu de mid_smooth** — critique pour un produit qui oscille autour d'un centre connu à l'avance (10,000), (b) **AR shift 1-tick** qui exploite le fait que les sauts ponctuels se reversent, (c) **takers biaisés vers inv_target** au lieu de symétriques.
