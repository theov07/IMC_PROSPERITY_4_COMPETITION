# Leo

Espace de travail pour les variantes Leo.

-tester la strat top of the book avec deux levels
-tester le penny jump
-tester le top of the book + join the best si best à une petite quantité
-> chercher à contourner le probleme de reset du FIFO à chaque nouveau OB 
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
