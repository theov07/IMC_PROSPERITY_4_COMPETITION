# Vizualizer (Round 0)

Ce dossier permet de visualiser les données Round 0 en s'appuyant au maximum sur les classes du `datamodel` (OrderDepth, Trade, TradingState, Listing).

## Ce que fait le visualizer

- Conversion des CSV `prices_*` en `OrderDepth` par timestamp
- Conversion des CSV `trades_*` en objets `Trade`
- Visualisations :
  - Mid price / best bid / best ask
  - Liquidité (volumes bid/ask) + spread
  - Trades (prix vs temps)

Les sorties sont enregistrées dans `vizualizer/output/`.

## Lancer le visualizer

```bash
.venv/bin/python vizualizer/main.py
```

## Notes

- Les données de Round 0 contiennent deux produits (`EMERALDS`, `TOMATOES`).
- Les volumes de vente sont négatifs dans le `datamodel` (convention OrderDepth).
