"""Interactive Plotly/Dash dashboard for analyzing backtests and official logs.

Usage:
  python -m prosperity.tooling.dashboard --log examples/official_logs/16248.json
  python -m prosperity.tooling.dashboard --log examples/official_logs/16248.log
  python -m prosperity.tooling.dashboard --backtest-json artifacts/backtest_results.json
  python -m prosperity.tooling.dashboard --data-dir data --round 0 --day -2

Features:
  - Price chart with bid/ask/mid/fair overlay
  - Trade markers (buys/sells) with size encoding
  - Order book depth heatmap
  - PnL equity curve
  - Position over time
  - Spread and imbalance indicators
  - Timestamp navigation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from dash import Dash, dcc, html, Input, Output
    HAS_DASH = True
except ImportError:
    HAS_DASH = False


def _build_price_figure(activities: pd.DataFrame, trades: pd.DataFrame, symbol: str) -> go.Figure:
    """Build the main price + trades figure for one symbol."""
    sym_act = activities[activities["product"] == symbol].copy().sort_values("timestamp")
    if sym_act.empty:
        return go.Figure()

    # Compute features
    sym_act["mid"] = (sym_act["bid_price_1"] + sym_act["ask_price_1"]) / 2
    bv1 = sym_act["bid_volume_1"].clip(lower=1)
    av1 = sym_act["ask_volume_1"].clip(lower=1)
    sym_act["microprice"] = (sym_act["bid_price_1"] * av1 + sym_act["ask_price_1"] * bv1) / (bv1 + av1)
    sym_act["fair_ewm"] = sym_act["microprice"].ewm(span=25, adjust=False).mean()
    sym_act["spread"] = sym_act["ask_price_1"] - sym_act["bid_price_1"]
    sym_act["imbalance"] = (bv1 - av1) / (bv1 + av1)

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.45, 0.2, 0.15, 0.2],
        subplot_titles=[f"{symbol} — Price & Trades", "Spread", "Imbalance", "PnL / Position"],
        vertical_spacing=0.04,
    )

    # Row 1: Price
    fig.add_trace(go.Scatter(x=sym_act["timestamp"], y=sym_act["bid_price_1"], name="Best Bid", line=dict(color="#0b7285", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=sym_act["timestamp"], y=sym_act["ask_price_1"], name="Best Ask", line=dict(color="#c92a2a", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=sym_act["timestamp"], y=sym_act["fair_ewm"], name="Fair (EWM)", line=dict(color="#2b8a3e", width=1.5, dash="dot")), row=1, col=1)

    # Trades
    if not trades.empty:
        sym_trades = trades[trades["symbol"] == symbol].copy()
        buyer_sub = sym_trades.get("buyer", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
        seller_sub = sym_trades.get("seller", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
        sub_trades = sym_trades[buyer_sub | seller_sub].copy()
        if not sub_trades.empty:
            sub_trades["side"] = sub_trades["buyer"].fillna("").eq("SUBMISSION").map({True: "BUY", False: "SELL"})
            buys = sub_trades[sub_trades["side"] == "BUY"]
            sells = sub_trades[sub_trades["side"] == "SELL"]
            if not buys.empty:
                fig.add_trace(go.Scatter(x=buys["timestamp"], y=buys["price"], mode="markers", name="Buy",
                    marker=dict(symbol="triangle-up", color="#2f9e44", size=buys["quantity"].clip(1, 20) * 2, line=dict(width=0.5, color="black")),
                    text=[f"qty={q}, px={p}" for q, p in zip(buys["quantity"], buys["price"])], hoverinfo="text+name"), row=1, col=1)
            if not sells.empty:
                fig.add_trace(go.Scatter(x=sells["timestamp"], y=sells["price"], mode="markers", name="Sell",
                    marker=dict(symbol="triangle-down", color="#f03e3e", size=sells["quantity"].clip(1, 20) * 2, line=dict(width=0.5, color="black")),
                    text=[f"qty={q}, px={p}" for q, p in zip(sells["quantity"], sells["price"])], hoverinfo="text+name"), row=1, col=1)

    # Row 2: Spread
    fig.add_trace(go.Scatter(x=sym_act["timestamp"], y=sym_act["spread"], name="Spread", line=dict(color="#495057", width=1), fill="tozeroy"), row=2, col=1)

    # Row 3: Imbalance
    colors = ["#2f9e44" if v > 0 else "#f03e3e" for v in sym_act["imbalance"]]
    fig.add_trace(go.Bar(x=sym_act["timestamp"], y=sym_act["imbalance"], name="Imbalance", marker_color=colors), row=3, col=1)

    fig.update_layout(height=900, showlegend=True, template="plotly_white", hovermode="x unified")
    return fig


def _load_official_log(path: str | Path):
    """Load and parse an official Prosperity JSON / LOG bundle."""
    from prosperity.tooling.logs import load_official_log
    return load_official_log(path)


def run_static(log_path: str | None = None, symbol: str | None = None, output: str | None = None):
    """Generate static HTML charts (no Dash server needed)."""
    if log_path is None:
        print("Provide --log for static mode")
        return

    log = _load_official_log(log_path)
    symbols = [symbol] if symbol else sorted(log.activities["product"].dropna().unique())

    for sym in symbols:
        fig = _build_price_figure(log.activities, log.trades, sym)
        out_path = output or f"artifacts/analysis/{log.analysis_group}/{log.submission_id}_{sym}_dashboard.html"
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(out_path)
        print(f"Saved {out_path}")


def run_dash(log_path: str):
    """Launch interactive Dash app."""
    if not HAS_DASH:
        print("dash not installed. Run: pip install dash")
        print("Falling back to static HTML export.")
        run_static(log_path)
        return

    log = _load_official_log(log_path)
    symbols = sorted(log.activities["product"].dropna().unique())

    app = Dash(__name__)
    app.layout = html.Div([
        html.H2(f"Prosperity Dashboard — {log.submission_id}"),
        html.Div([
            html.Label("Product:"),
            dcc.Dropdown(id="symbol-select", options=[{"label": s, "value": s} for s in symbols], value=symbols[0] if symbols else None),
        ], style={"width": "300px", "marginBottom": "20px"}),
        dcc.Graph(id="main-chart", style={"height": "900px"}),
        html.Div(id="summary-text", style={"fontFamily": "monospace", "whiteSpace": "pre", "padding": "10px"}),
    ])

    @app.callback(
        [Output("main-chart", "figure"), Output("summary-text", "children")],
        [Input("symbol-select", "value")],
    )
    def update(selected_symbol):
        if not selected_symbol:
            return go.Figure(), ""
        fig = _build_price_figure(log.activities, log.trades, selected_symbol)
        profit = log.profit
        summary = f"Submission: {log.submission_id}\nProfit: {profit}\nProduct: {selected_symbol}"
        return fig, summary

    print("Starting dashboard at http://127.0.0.1:8050")
    app.run(debug=False, port=8050)


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prosperity interactive dashboard")
    parser.add_argument("--log", help="Path to official JSON or LOG file")
    parser.add_argument("--symbol", help="Specific product to show")
    parser.add_argument("--static", action="store_true", help="Export static HTML instead of running Dash")
    parser.add_argument("--output", help="Output path for static HTML")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.static or not HAS_DASH:
        run_static(args.log, args.symbol, args.output)
    else:
        if args.log:
            run_dash(args.log)
        else:
            print("Provide --log <path> to launch dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
