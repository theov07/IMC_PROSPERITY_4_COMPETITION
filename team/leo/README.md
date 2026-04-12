# Leo

Espace de travail pour les variantes Leo.

V8 direction:

- garder le pricing top of the book
- sizing intelligent
- filtre de toxicite
- take selectif
- petits batches de test seulement

-tester la strat top of the book avec deux levels
-tester le penny jump
-tester le top of the book + join the best si best à une petite quantité
-> chercher à contourner le probleme de reset du FIFO à chaque nouveau OB 
->faire un module de reverse engineering sur les logs d'une srtat qui achete 1 de chaque produit au début ? 
->ajouter au dashboard de data exploratory davantage de donnée genre corrélation, copule, le spread entre produit 
-> ajouter un mode mm turn off en cas de vol > seuil ? indice de toxicité ? genre carrément on débranche 
## Première stratégie

La première stratégie créée dans le nouveau framework est `naive`.

Idée:

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

Cette stratégie sert de baseline simple et lisible avant de construire des versions plus intelligentes.
