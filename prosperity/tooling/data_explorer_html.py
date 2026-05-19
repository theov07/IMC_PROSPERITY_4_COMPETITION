"""Static HTML Plotly version of research/shared/visualizer/dashboard.py.

Generates a self-contained HTML report with per-product charts (mid + best
bid/ask, spread, imbalance, signed trade markers, cumulative volume) for the
selected round/products/days. No server required — opens directly in a browser.

Usage:
    python -m prosperity.tooling.data_explorer_html --round 4 \
        --products HYDROGEL_PACK VELVETFRUIT_EXTRACT \
        --out artifacts/analysis/round_4/data_explorer.html

    # all products of a round
    python -m prosperity.tooling.data_explorer_html --round 4 \
        --out artifacts/analysis/round_4/data_explorer_all.html

    # specific days only
    python -m prosperity.tooling.data_explorer_html --round 4 --days 2 3 \
        --out artifacts/analysis/round_4/data_explorer_d2d3.html
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Iterable

import pandas as pd

_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.26.0.min.js"


def _load_round(data_dir: Path, round_num: int, days: list[int] | None):
    round_dir = data_dir / f"round_{round_num}"
    if not round_dir.is_dir():
        round_dir = data_dir
    prices, trades = {}, {}
    for f in sorted(round_dir.glob(f"prices_round_{round_num}_day_*.csv")):
        d = int(f.stem.rsplit("_", 1)[-1])
        if days and d not in days:
            continue
        prices[d] = pd.read_csv(f, sep=";")
    for f in sorted(round_dir.glob(f"trades_round_{round_num}_day_*.csv")):
        d = int(f.stem.rsplit("_", 1)[-1])
        if days and d not in days:
            continue
        trades[d] = pd.read_csv(f, sep=";")
    return prices, trades


def _signed_trades(trades_df: pd.DataFrame, prices_df: pd.DataFrame, product: str):
    """Return (buy_ts, buy_px, sell_ts, sell_px) classified vs prev-tick mid."""
    sub = trades_df[trades_df["symbol"] == product].copy()
    if sub.empty:
        return [], [], [], []
    p = prices_df[prices_df["product"] == product].set_index("timestamp")["mid_price"]
    sub["mid"] = sub["timestamp"].map(p).ffill()
    buys = sub[sub["price"] >= sub["mid"]]
    sells = sub[sub["price"] < sub["mid"]]
    return (
        buys["timestamp"].tolist(),
        buys["price"].tolist(),
        sells["timestamp"].tolist(),
        sells["price"].tolist(),
    )


def _build_product_section(product: str, prices: dict, trades: dict) -> str:
    """One <section> with 1 figure per day (4 stacked subplots)."""
    chart_divs = []
    for day in sorted(prices.keys()):
        p = prices[day]
        t = trades[day]
        sub = p[p["product"] == product].sort_values("timestamp")
        if sub.empty:
            continue
        spread = sub["ask_price_1"] - sub["bid_price_1"]
        bid_vol = sub[["bid_volume_1", "bid_volume_2", "bid_volume_3"]].sum(axis=1)
        ask_vol = sub[["ask_volume_1", "ask_volume_2", "ask_volume_3"]].sum(axis=1)
        imb = (bid_vol - ask_vol) / (bid_vol + ask_vol).replace(0, 1)
        b_ts, b_px, s_ts, s_px = _signed_trades(t, p, product)

        # 4 subplots: price, spread, imbalance, trade markers (overlaid on mid)
        traces = [
            {"x": sub["timestamp"].tolist(), "y": sub["mid_price"].tolist(),
             "type": "scatter", "mode": "lines", "name": "mid", "line": {"color": "black", "width": 1}, "xaxis": "x", "yaxis": "y"},
            {"x": sub["timestamp"].tolist(), "y": sub["bid_price_1"].tolist(),
             "type": "scatter", "mode": "lines", "name": "best bid", "line": {"color": "#2ca02c", "width": 0.6}, "opacity": 0.7, "xaxis": "x", "yaxis": "y"},
            {"x": sub["timestamp"].tolist(), "y": sub["ask_price_1"].tolist(),
             "type": "scatter", "mode": "lines", "name": "best ask", "line": {"color": "#d62728", "width": 0.6}, "opacity": 0.7, "xaxis": "x", "yaxis": "y"},
            {"x": sub["timestamp"].tolist(), "y": spread.tolist(),
             "type": "scatter", "mode": "lines", "name": "spread", "line": {"color": "#9467bd", "width": 0.8}, "xaxis": "x2", "yaxis": "y2", "showlegend": False},
            {"x": sub["timestamp"].tolist(), "y": imb.tolist(),
             "type": "scatter", "mode": "lines", "name": "imbalance", "line": {"color": "#ff7f0e", "width": 0.8}, "xaxis": "x3", "yaxis": "y3", "showlegend": False},
            {"x": b_ts, "y": b_px, "type": "scatter", "mode": "markers",
             "name": "buys (price≥mid)", "marker": {"color": "#2ca02c", "size": 5, "symbol": "triangle-up"},
             "xaxis": "x4", "yaxis": "y4"},
            {"x": s_ts, "y": s_px, "type": "scatter", "mode": "markers",
             "name": "sells (price<mid)", "marker": {"color": "#d62728", "size": 5, "symbol": "triangle-down"},
             "xaxis": "x4", "yaxis": "y4"},
        ]
        layout = {
            "title": f"{product} — day {day}  (n={len(sub)}, mid range [{sub.mid_price.min():.1f}, {sub.mid_price.max():.1f}], "
                     f"avg spread {spread.mean():.2f}, trades {len(b_ts) + len(s_ts)})",
            "height": 900,
            "grid": {"rows": 4, "columns": 1, "pattern": "independent"},
            "xaxis":  {"domain": [0, 1], "anchor": "y",  "matches": "x4", "showticklabels": False},
            "xaxis2": {"domain": [0, 1], "anchor": "y2", "matches": "x4", "showticklabels": False},
            "xaxis3": {"domain": [0, 1], "anchor": "y3", "matches": "x4", "showticklabels": False},
            "xaxis4": {"domain": [0, 1], "anchor": "y4", "title": "timestamp"},
            "yaxis":  {"domain": [0.78, 1.00], "title": "price"},
            "yaxis2": {"domain": [0.55, 0.75], "title": "spread"},
            "yaxis3": {"domain": [0.32, 0.52], "title": "imbalance", "range": [-1, 1]},
            "yaxis4": {"domain": [0.00, 0.29], "title": "trades"},
            "hovermode": "x unified",
            "margin": {"t": 50, "b": 40, "l": 60, "r": 10},
            "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        }
        chart_id = f"chart_{product}_{day}".replace(" ", "_")
        chart_divs.append(f'''
<div id="{chart_id}" style="width:100%;"></div>
<script>Plotly.newPlot("{chart_id}", {json.dumps(traces)}, {json.dumps(layout)}, {{responsive: true}});</script>
''')
    if not chart_divs:
        return ""
    return f'<section><h2>{escape(product)}</h2>{"".join(chart_divs)}</section>'


def build_html(prices: dict, trades: dict, products: list[str], round_num: int) -> str:
    sections = "".join(_build_product_section(p, prices, trades) for p in products)
    return f'''<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Round {round_num} — Data Explorer</title>
<script src="{_PLOTLY_CDN}"></script>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 16px; max-width: 1600px; }}
h1 {{ border-bottom: 2px solid #444; padding-bottom: 4px; }}
h2 {{ margin-top: 32px; color: #1f3a5f; }}
section {{ margin-bottom: 40px; }}
</style>
</head><body>
<h1>Round {round_num} — Data Explorer</h1>
<p>Days: {", ".join(str(d) for d in sorted(prices.keys()))} · Products: {len(products)}</p>
{sections}
</body></html>'''


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static HTML data explorer (Plotly).")
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--data-dir", default="data", help="Root data directory (default: data)")
    parser.add_argument("--products", nargs="+", default=None, help="Subset of product symbols (default: all)")
    parser.add_argument("--days", nargs="+", type=int, default=None, help="Subset of days (default: all)")
    parser.add_argument("--out", required=True, help="Output HTML path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    prices, trades = _load_round(Path(args.data_dir), args.round, args.days)
    if not prices:
        print(f"No price data found for round {args.round}")
        return 1

    all_products = sorted({p for df in prices.values() for p in df["product"].unique()})
    products = [p for p in all_products if not args.products or p in args.products]
    if not products:
        print(f"No matching products. Available: {all_products}")
        return 1

    html = build_html(prices, trades, products, args.round)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB) — {len(products)} products × {len(prices)} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
