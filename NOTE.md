## IMC Queue / FIFO Reality

## V8 Direction

- Keep the V1 / V6 top-of-book pricing rule and protect queue priority.
- Build V8 around only three levers:
- Smart sizing: cut the side that worsens inventory and slightly boost the unwind side.
- Toxicity filter: use short-horizon flow and one-tick jumps to shrink the adverse side.
- Selective take: keep the opportunistic take layer and lean a bit harder into takes that reduce inventory.
- For research, prefer tiny manual batches and one-day checks before any wider sweep.
- First V8 sanity check on day `-2`:
- `queue`: `39766.0`
- `worse`: `15018.5`
- Interpretation: the first V8 draft is much more defensive than the current V7 config. It keeps the conservative score close to the current baseline, but loses too much volume / optimistic spread capture.

## Framework Status

- Quote logging is now standardized for quoting strategies, so official logs can surface our own bid/ask in the dashboard when lambda logs are present.
- The backtester now exports robustness metrics in JSON summaries:
- `max_drawdown`
- `fill_efficiency`
- `avg_abs_position_ratio`
- `near_limit_tick_ratio`
- `aggressive_qty` vs `passive_qty`
- `passive_adverse_rate`
- `passive_post_fill_edge`
- `bid_fill_efficiency` / `ask_fill_efficiency`
- quote diagnostics: `avg_quote_age_ticks`, refresh count, stale quote exposure
- inventory episode diagnostics: one-sided time, sign flips, unwind duration
- markout means on `+1`, `+2`, `+5`, `+10` ticks for all/passive/aggressive fills
- pnl attribution proxies: `spread_capture`, `inventory_drift`, `make_edge`, `take_edge`, `adverse_selection_1`
- observation / conversion traces are now exported in backtest JSON when data exists
- `compare` and `grid_search` can now rank by robustness, not only by pnl.
- `dashboard` and `tooling.logs` now try a best-effort auto-discovery of a matching backtest JSON in `artifacts/`, then run reconciliation automatically if a confident match is found.
- `tooling.logs` now computes participant-aware official summaries: counterparty volume and post-trade markout by horizon.
- The dashboard now surfaces:
- backtest diagnostics cards per symbol
- IMC participant / markout diagnostics per symbol
- live vs backtest headline comparisons per symbol (`fills`, side fill-rate proxy, quoted spread, markout)
- live vs backtest overlay chart for `position`, cumulative fills, and quoted spread
- IMC trade-flow panel with signed market flow vs our own signed submission flow
- observation / conversion panels in backtest view when present

## Missing Metrics / Next Gaps

- We still do not calibrate backtest markouts against official logs by product, side, and horizon.
- We still do not estimate queue reach / fill probability from official logs, only heuristic age / stale diagnostics.
- We still do not have a full additive pnl attribution with realized spread, carry, inventory drift, and conversion pnl separated perfectly.
- We still do not visualize markout curves directly as dedicated dashboard plots; for now they are shown as summary metrics.
- We still do not have round-aware observation loaders for every possible future CSV schema; current handling is generic / best-effort.
- We still do not classify official fills into passive vs aggressive with certainty; the participant analysis is side-aware and markout-aware, not a perfect aggressor classifier.

- In live IMC, a passive quote that is not traded can remain visible during the iteration, but if no bot trades against it, it is cancelled at the end of the iteration.
- That means being behind only 10 to 15 lots at best can still produce zero fills: the queue in front is small, but the quote lifetime is also short.
- This is the likely explanation for V7: `qty_join_threshold=15` often joined the best price instead of improving by one tick, so we sat behind the displayed top size and were rarely reached before cancellation or book refresh.
- Exact FIFO cannot be reconstructed from the public historical data we have. We only see aggregated book snapshots by price, not individual resting orders with arrival times.
- The trade CSV also does not reveal the full matching path inside a tick, so we do not know which fraction of a same-price trade should be assigned to the queue ahead of us versus to us.
- What we can implement is a conservative queue heuristic, not true FIFO:
- If we improve inside the spread, assume queue ahead is zero at our price.
- If we join an existing best level, initialize queue ahead with the displayed size already resting there.
- Fill our passive order only after same-tick traded volume at that price exceeds that queue ahead, optionally with a safety margin.
- Cancel any remaining passive quantity at the end of the iteration, to mirror IMC's documented quote lifetime.
- Until this heuristic exists, `match-trades=none` is the safest lower bound and `match-trades=worse` is a more conservative middle ground than `all`.

-essayer Monte Carlo
-avoir à l'idée que tout est possible, par exemple IMC
peut nous mettre une paire qui sert à rien et qui
ne possède pas d'alpha 
-on peut avoir des positions négatives
-le mid price est impacté par nos ordres ? Non 
-Est ce que inter day l'inventaire est remis à 0 ? J'ai vu dans le dashboard on a des positions qui passe > limit à cause de ça car on reset pas inter day (entre jour 1 et 2 par exemple) -> problème reglé 
# Market Making — Du fondamental au complexe
## Guide de préparation Prosperity IMC

---

## 1. LES FONDAMENTAUX

**Qu'est-ce qu'un market maker ?**
Un market maker affiche en permanence un prix d'achat (bid) et un prix de vente (ask). Il gagne le spread entre les deux. Son ennemi numéro un : l'inventaire. S'il accumule trop d'un actif dans un sens, il est exposé au risque de prix.

**La logique centrale :**
Spread capturé = revenus. Position nette non nulle = risque. L'objectif est de capturer le spread en maintenant un inventaire aussi proche de zéro que possible

---

## 2. STRATÉGIES DE BASE

**2.1 Spread fixe symétrique**
Tu postes bid et ask à équidistance du mid-price.
```
Mid = 100
Bid = 99 | Ask = 101 | Spread = 2
```
Simple mais naïf. Tu ignores la direction du marché et tu accumules de l'inventaire si le prix dérive.

**2.2 Ajustement par l'inventaire (Avellaneda-Stoikov)**
La référence académique du market making. Le prix de réservation (reservation price) est ajusté en fonction de l'inventaire accumulé :

```
r = s - q × γ × σ² × (T - t)
```
Où :
- s = mid-price
- q = inventaire actuel
- γ = aversion au risque
- σ = volatilité
- T-t = temps restant

Si tu es long, tu baisses ton bid et ton ask pour inciter à la vente. Si tu es short, tu les montes. L'inventaire pilote le quote.

**2.3 Spread optimal**
Le spread optimal dans Avellaneda-Stoikov :
```
δ* = γ × σ² × (T - t) + (2/γ) × ln(1 + γ/k)
```
Où k est la sensibilité de l'order flow à tes prix. Plus k est faible (les gens sont sensibles au prix), plus tu serres le spread pour générer du volume.

---

## 3. STRATÉGIES INTERMÉDIAIRES

**3.1 Skewing dynamique**
Au lieu d'ajuster le mid, tu skew asymétriquement bid et ask selon l'inventaire.

```
Si inventaire = +10 (trop long) :
Bid = mid - 1.5  (moins agressif à l'achat)
Ask = mid + 0.5  (plus agressif à la vente)
```

Tu continues à fournir de la liquidité des deux côtés mais tu te penches vers la réduction de position.

**3.2 Quote sizing dynamique**
Tu ne postes pas la même quantité des deux côtés.

```
Si inventaire = +10 :
Bid size = 2  (petit, tu ne veux pas en acheter plus)
Ask size = 8  (grand, tu veux vendre)
```

Le sizing est aussi un outil de gestion d'inventaire, pas seulement le prix.

**3.3 Prise en compte du momentum**
Si le prix monte rapidement, tu anticipes une adverse selection : les gens qui te tapent en bid savent quelque chose que tu ne sais pas. Tu peux :
- Widener le spread quand la volatilité court terme augmente
- Reculer tes quotes (plus loin du mid) pendant les mouvements forts
- Stopper temporairement de quoter d'un côté

**3.4 Cancellation agressive**
En compétition, le timing de cancel/replace est critique. Tu postes, quelqu'un est sur le point de te taper sur un mouvement défavorable, tu cancel avant. Nécessite de détecter la direction du marché en temps réel.

---

## 4. GESTION DE L'ADVERSE SELECTION

C'est le problème central du market maker. Quand quelqu'un te prend ta liquidité, est-ce un bruit (noise trader) ou un informed trader qui sait que le prix va bouger ?

**4.1 Modèle de Kyle (Lambda)**
Tu estimes la proportion d'informed traders dans le flow. Plus λ est élevé, plus tu widenes ton spread pour te protéger.

```
Prix post-trade = mid + λ × (order flow)
```

**4.2 Détection du flow toxique**
Signaux à surveiller en compétition :
- Les trades arrivent en rafale dans un sens : signe d'information
- Volume anormalement élevé : quelqu'un sait quelque chose
- Sequence de fills tous du même côté : abandon temporaire du quoting côté concerné

**4.3 Fill rate asymétrique**
Si ton bid se fait exécuter beaucoup plus souvent que ton ask, c'est un signal que le marché descend. Ajuste immédiatement.

---

## 5. STRATÉGIES AVANCÉES

**5.1 Market making multi-actifs avec corrélations**
Dans Prosperity, plusieurs actifs sont souvent corrélés. Si A monte, B tend à monter. Tu peux :
- Utiliser la position dans A comme signal pour quoter B
- Hedger ton inventaire dans A en tradant B
- Exploiter les divergences temporaires de corrélation

**5.2 Arbitrage statistique intégré**
Tu combines market making et stat arb. Exemple :
- Tu estimes le fair value de l'actif via régression sur d'autres actifs
- Tu skew tes quotes vers le fair value
- Quand le prix s'en écarte, tes quotes sont automatiquement positionnés pour profiter du retour

**5.3 Imbalance de carnet d'ordres (Order Book Imbalance)**
```
OBI = (Volume bid - Volume ask) / (Volume bid + Volume ask)
```
Un OBI positif fort (plus de bids que d'asks) prédit une hausse. Tu ajustes ton mid avant que le prix ne bouge. C'est du market making avec signal prédictif intégré.

**5.4 Optimal execution avec contraintes d'inventaire**
Tu définis un inventaire cible et un inventaire maximum. La stratégie optimise le spread capturé sous contrainte de ne jamais dépasser les limites.

```
Max: E[Spread capturé]
Sous contrainte: |inventaire| ≤ Q_max
```

Quand tu approches de Q_max, tu agrandis massivement le spread ou tu t'arrêtes de quoter d'un côté.

---

## 6. CE QUI COMPTE SPÉCIFIQUEMENT DANS PROSPERITY

**6.1 Microstructure de la compétition**
- Les autres bots sont des participants. Certains sont directionnels, certains sont market makers comme toi. Identifier qui est qui change ta stratégie.
- Les noise traders génèrent du profit. Les informed traders te saignent.
- Il n't'a pas de carnet d'ordre infini : la liquidité disponible pour hedger est limitée.

**6.2 Position limits**
La compétition impose des limites de position. Gérer l'inventaire n'est pas optionnel, c'est une contrainte dure. Ton algo doit :
- Ne jamais approcher la limite sans plan de sortie
- Avoir un mode "urgence" qui sacrifie le spread pour réduire l'inventaire
- Eviter les situations où tu es bloqué d'un côté du marché

**6.3 Prioriser la robustesse sur l'optimisation**
Un modèle simple et robuste bat un modèle complexe et fragile. Une stratégie Avellaneda-Stoikov bien calibrée avec une gestion d'inventaire stricte est souvent plus efficace qu'une approche ML complexe mal réglée.

---

## 7. CHECKLIST DE STRATÉGIE

Avant de coder, réponds à ces questions :

**Quoting :**
Quel est mon spread de base ? Comment le fais-je varier avec la volatilité ? Comment skew-je en fonction de l'inventaire ?

**Inventaire :**
Quel est mon inventaire cible ? Mon inventaire max ? Qu'est-ce que je fais en urgence si je l'atteins ?

**Signal :**
Est-ce que j'intègre un signal directionnel ? OBI ? Momentum ? Corrélation inter-actifs ?

**Adverse selection :**
Comment je détecte un flow toxique ? Est-ce que je pause le quoting en cas de mouvement fort ?

**Risque :**
Quel est mon drawdown max toléré ? Est-ce que mon algo peut perdre en boucle sur un actif et ignorer les autres ?

---

## 8. RECAP EN UNE PAGE

| Niveau | Stratégie | Complexité | Risque principal |
|---|---|---|---|
| Débutant | Spread fixe symétrique | Faible | Accumulation inventaire |
| Intermédiaire | Avellaneda-Stoikov | Moyen | Calibration γ et σ |
| Intermédiaire | Skewing + sizing | Moyen | Over-fitting sur signal |
| Avancé | OBI + momentum | Elevé | Latence, faux signaux |
| Avancé | Multi-actifs corrélés | Elevé | Corrélations instables |
| Expert | Stat arb intégré | Très élevé | Modélisation erreur |

---

**Le principe à retenir :** un market maker ne prédit pas les prix. Il gère un flux et un inventaire. Plus ta gestion d'inventaire est propre, plus tu peux serrer le spread, plus tu génères de volume et de profit. La direction du marché est ton ennemi. La vitesse de rotation de l'inventaire est ton meilleur ami.
