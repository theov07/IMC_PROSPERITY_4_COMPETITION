# TODO restant — R4

État au commit ~0b83ff2+v16/v17. v9 champion = 176,593 PnL / 67,628 DD / ratio 2.61 / 95.2% du 100KB IMC.

---

## Variantes testées et résumé

| Idée | PnL 3-day | Δ vs v9 | Verdict |
|---|---:|---:|---|
| **v9 champion** | **176,593** | — | Locked |
| v10 lim200 (reduce options limit) | 164,062 | -12,531 | Trade-off PnL/DD, similaire ratio |
| v11 micro M55/M67 (-0.01) | 175,781 | -812 | Quasi-neutre, "live ready" |
| v12 M14 invert (follow) | 159,120 | -17,473 | LOSE — implied PnL ≠ optimal weight en MM |
| v13 cp_bias on existing options | 176,544 | -49 | Neutre — options low volume |
| **v14e HYDRO re-enable** | **223,776** | **+47,183** | 🎯 BIG WIN, séparé |
| v15 ENABLE deep OTM | 176,604 | +11 | Useless — Mark 01/22 trade direct |
| v16d 90/70/5 unwind takers | 166,498 | -10,095 | DD baisse 3k, PnL chute 10k |
| v17 passive unwind | (en cours) | — | Capture spread instead of pay |

---

## TODO restant (priorité)

### HIGH (à faire next)

#### 1. v17 passive unwind validation
Si v17 maintient PnL ET réduit DD → lock comme nouveau champion. Tests en cours.

#### 2. **2-sided MM forcé sur options** (vraie réponse à "on est trop directionnel")
Aujourd'hui `option_mm_bs` quote bid+ask autour de la fair BS. Mais quand on est long max, on continue à quoter le bid (qui ne fillera plus de toute façon).

**Solution** : quand `|pos| > 70% limit`, FORCER le quote uniquement sur le côté qui réduit. Plus de bid si long max. Plus d'ask si short max.

C'est ce que `option_mm_bs` SHOULD do via `inv_bias_per_unit` mais c'est trop faible (0.02). Il faut peut-être augmenter à 0.1 ou 0.2.

A tester : grid `inv_bias_per_unit` ∈ {0.05, 0.1, 0.2, 0.5}.

#### 3. **Cross-asset signal exploit** (le plus gros alpha non touché)
Findings du `trader_alpha_hunt.py`:
- Mark 14 flow on VELVET → VEV_5200 return : **corr = -0.106 sur 642 points** (très significatif)
- Mark 22 flow on VEV_5200 → VELVET return : corr = +0.214 sur 47 points
- Mark 14 flow on VEV_5200 → VELVET return : corr = -0.165 sur 33 points

→ Implémenter overlay `_apply_cross_asset_bias` qui trade un produit B sur la base d'un signal de produit A. Estimé +5-15k PnL si on capture juste une partie.

#### 4. **Implémenter Mark 22 deep OTM hedge**
Mark 22 vend 1105 contracts deep OTM. Si on enable VEV_5500/6000/6500 SEULEMENT pour BUY (pas MM 2-sided, juste opportunité), on récupère le côté Mark 22.

Mais nos tests v15 montrent qu'on ne gagne rien — on peut pas se mettre dans la queue. Il faudrait une stratégie aggressive : quote at best_bid (= prix Mark 22 pose) avec size 30 pour intercepter ses sells.

### MEDIUM

#### 5. **Day 3 deep dive — pourquoi on perd ?**
Day 3 PnL = 18,753 (vs Day 1 73,528, Day 2 84,312). On perd 75% du PnL day-over-day. Pourquoi ?

Hypothèses :
- Drift directionnel violent (mid baisse de X%) → fade signals deviennent counter-productifs
- Volatilité augmente → spreads se cassent
- Trader regime change : peut-être qu'un trader bullish disparaît

**Test** : per-day analyse trader behavior (qui trade Day 3 vs Day 1/2 ?). Trouver early-warning. Pourrait sauver +5-10k.

#### 6. **Reuse HYDRO comme add-on optionnel**
Le user a explicitement dit séparé. Mais on peut tester une variante de **submission distincte** `r4_v14e_with_hydro` à uploader pour des slots où HYDRO est pertinent. +47k facile.

#### 7. **Garde-fous extrêmes**
- Vol breakout : si rolling_vol > 3x normal, halve sizes
- DD limit : si intraday DD > 50% PnL, stop trading product
- Stale book : refuse if spread > 100 ticks de mid_smooth

Coût ~0 en backtest, +5-10k en tail scenarios live.

### LOW

#### 8. Repartir from zero (clean slate)
Le user a mentionné cette idée. Construire une nouvelle stratégie pure et simple sans héritage. Risque : 1-2 jours pour rien. Vaut peut-être le coup si le ratio v9 est upper bound.

#### 9. Per-trader z-thresh dans cp_bias
Actuellement zthresh est partagé pour tous les conditional traders. Pourrait être par-trader. Petit gain probable.

#### 10. Plus d'analyse trader-level
- Trader X PnL by hour-of-day ?
- Trader correlation matrix ?
- Cluster traders into MM/informed/noise ?

---

## Decision flow

Tu choisis :
- **Robustesse** → v9 + v17 passive unwind (si v17 marche) → ratio amélioré
- **PnL absolu max** → v9 tel quel, ne touche rien
- **PnL absolu max + HYDRO** → v14e (223k) — mais pas séparé du champion VELVET/options

---

## Effort estimate pour les HIGH

1. v17 validation : 1h (déjà lancé)
2. 2-sided MM forced : 30min (param tuning) + 1h (tests)
3. Cross-asset signal : 2-3h (overlay design + grid)
4. Mark 22 deep OTM hedge : 2h (custom strategy)
5. Day 3 deep dive : 1-2h analysis only

**Total budget HIGH : ~8h de travail actif**.
