# Backtest Round 0 (ITS / OOTS)

Ce fichier décrit le framework de backtest `backtest.py` basé sur les classes de `datamodel.py`.

## Objectif

- Rejouer les `OrderDepth` et `Trade` à partir des CSV Round 0
- Exécuter un `Trader` et simuler des fills simples au best bid/ask
- Comparer **In-The-Sample (ITS)** et **Out-Of-The-Sample (OOTS)**

## Lancer un backtest

```bash
.venv/bin/python backtest.py --strategy test_leo --its-days -2 --oots-days -1
```

### Paramètres

- `--strategy` : module Python qui expose une classe `Trader`
- `--its-days` : liste des jours ITS (ex: `-2`)
- `--oots-days` : liste des jours OOTS (ex: `-1`)

Si aucun split n’est fourni, le script coupe automatiquement la liste des jours en deux.

## Notes

- Simulation **simplifiée** : fills uniquement sur le best bid/ask (aggressive).
- La PnL est marquée au mid en fin de journée.
- L’engine utilise `TradingState`, `OrderDepth`, `Trade`, `Listing`.
