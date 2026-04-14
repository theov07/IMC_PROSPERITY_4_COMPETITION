# Leo

Espace de travail pour les variantes Leo.

V8 direction:

- garder le pricing top of the book
- sizing intelligent
- filtre de toxicite
- take selectif
- petits batches de test seulement

Framework quick state:

- backtester: mode `realistic` propage partout
- backtester: metriques de robustesse ajoutees (`drawdown`, `fill_efficiency`, `inventory_pressure`, `passive_adverse_rate`)
- backtester: diagnostics MM ajoutes (`bid/ask fill efficiency`, `quote age`, refresh, stale exposure, inventory episodes, markouts `+1/+2/+5/+10`, attribution `spread/make/take/inventory/adverse`)
- compare / grid_search: classement possible par robustesse avec `--rank-by`
- reconcile: disponible en CLI, lance automatiquement par le dashboard et l'analyzer si un backtest local coherent est trouve
- logs officiels: analyse `participant-aware` avec markout par contrepartie
- dashboard / analyzer: auto-discovery best-effort du `backtest_json` dans `artifacts/`
- dashboard: cartes diagnostics par symbole + panneau observations / conversions quand dispo
- dashboard: compare `live vs backtest` avec overlay `position / cumulative fills / quoted spread`
- dashboard: panel IMC `trade flow`

- tester la strat top of the book avec deux levels
- tester le penny jump
- tester le top of the book + join the best si best a une petite quantite
- chercher a contourner le probleme de reset du FIFO a chaque nouveau OB
- faire un module de reverse engineering sur les logs d'une strat qui achete 1 de chaque produit au debut
- ajouter au dashboard de data exploratory davantage de donnee genre correlation, copule, le spread entre produit
- ajouter un mode mm turn off en cas de vol > seuil ? indice de toxicite ? genre carrement on debranche

## Premiere strategie

La premiere strategie creee dans le nouveau framework est `naive`.

Idee:

- ne fait pas de fair value
- ne prend pas agressivement
- quote toujours autour du meilleur bid / ask
- se resserre d'un tick si le spread le permet
- sinon rejoint le meilleur prix existant

Code principal:

- `prosperity/strategies/naive_tight_mm.py`
- `submissions/leo_naive.py`

Config round 0:

- `prosperity/config.py` avec le membre `leo_naive`

Commandes utiles:

```powershell
python backtest.py --strategy leo_naive --round 0 --days -2 -1
python scripts\export_submission.py --member leo_naive --round 0 --output artifacts\submissions\leo_naive_round0_submission.py
```

## But

Cette strategie sert de baseline simple et lisible avant de construire des versions plus intelligentes.
