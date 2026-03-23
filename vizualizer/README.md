# Vizualizer (Round 0)

Ce dossier permet de visualiser les données Round 0 en s'appuyant au maximum sur les classes du `datamodel` (OrderDepth, Trade, TradingState, Listing).

## Ce que fait le visualizer

- Conversion des CSV `prices_*` en `OrderDepth` par timestamp
- Conversion des CSV `trades_*` en objets `Trade`
- Visualisations :
  - Mid price / best bid / best ask
  - Liquidité (volumes bid/ask) + spread
  - Imbalance (order book imbalance)
  - Volatilité (rolling std des log-returns)
  - Trades (prix vs temps)
  - VWAP
  - VPIN (Volume-synchronized Probability of Informed Trading)

Les sorties sont enregistrées dans `vizualizer/output/`.

## Lancer le visualizer

```bash
.venv/bin/python vizualizer/main.py
```

### Animation de l’order book (vue dynamique)

Pour générer une animation MP4, active l’option :

```bash
VIZ_ANIMATE=1 .venv/bin/python vizualizer/main.py
```

Le fichier sera créé dans `vizualizer/output/`.

## Notes

- Les données de Round 0 contiennent deux produits (`EMERALDS`, `TOMATOES`).
- Les volumes de vente sont négatifs dans le `datamodel` (convention OrderDepth).
