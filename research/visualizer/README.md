# Visualizer

Research visualizer for round-0 order-book and trade data.

## What it does

- converts `prices_*` CSV files into `OrderDepth` snapshots
- converts `trades_*` CSV files into `Trade` objects
- plots mid price, best bid, best ask, liquidity, imbalance, volatility, trades, VWAP, and VPIN

Generated files are written to `artifacts/visualizer_output/`.

## Run

```bash
.venv\Scripts\python research\visualizer\main.py
```

Interactive dashboard:

```bash
.venv\Scripts\python research\visualizer\dashboard.py
```

Round-specific dashboard with nested data folders:

```bash
.venv\Scripts\python research\visualizer\dashboard.py --round 1
```

Optional order-book animation:

```bash
set VIZ_ANIMATE=1
.venv\Scripts\python research\visualizer\main.py
```
