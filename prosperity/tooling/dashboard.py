"""Interactive Plotly/Dash dashboard for analyzing backtests and official logs.

Usage:
  # IMC results only (pass either .json or .log — companion file auto-discovered)
  python -m prosperity.tooling.dashboard --log examples/official_logs/16248.json

  # Internal backtest only
  python -m prosperity.tooling.dashboard --backtest-json artifacts/backtest_results.json --data-dir data

  # Combined: IMC on top, internal backtest on bottom
  python -m prosperity.tooling.dashboard --log examples/official_logs/16248.json \
      --backtest-json artifacts/backtest_results.json --data-dir data
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


# ── Palette ────────────────────────────────────────────────────────────────
C_BID      = "#1971c2"   # blue
C_ASK      = "#c92a2a"   # red
C_FAIR     = "#2b8a3e"   # green dotted
C_BUY      = "#2f9e44"   # green triangles
C_SELL     = "#e03131"   # red triangles
C_SPREAD   = "#868e96"   # grey fill
C_POSITION = "#7048e8"   # purple
C_IMB_POS  = "#51cf66"   # light green bars
C_IMB_NEG  = "#ff6b6b"   # light red bars
C_PNL_TOTAL = "#212529"   # near-black total line

# Per-product color palette (cycled when > 6 products)
PRODUCT_COLORS = ["#339af0", "#f59f00", "#51cf66", "#ff6b6b", "#cc5de8", "#20c997"]


def _product_color_map(symbols: list[str]) -> dict[str, str]:
    return {sym: PRODUCT_COLORS[i % len(PRODUCT_COLORS)] for i, sym in enumerate(sorted(symbols))}

SUBPLOT_TITLE_STYLE = dict(font=dict(size=12, color="#495057"))
LEGEND_STYLE = dict(
    orientation="h",
    yanchor="top", y=-0.04,
    xanchor="center", x=0.5,
    bgcolor="rgba(255,255,255,0.85)",
    bordercolor="#dee2e6",
    borderwidth=1,
    font=dict(size=11),
)
LAYOUT_BASE = dict(
    template="plotly_white",
    hovermode="x unified",
    margin=dict(l=60, r=40, t=60, b=80),
    plot_bgcolor="#f8f9fa",
    paper_bgcolor="#ffffff",
    font=dict(family="Inter, sans-serif", size=12, color="#212529"),
)


# ── Shared helpers ─────────────────────────────────────────────────────────

def _trade_markers(fig, df: pd.DataFrame, row: int, prefix: str = ""):
    """Add buy/sell triangle markers to a subplot row."""
    if df.empty:
        return
    mkw = dict(line=dict(width=0.6, color="#212529"))
    buys = df[df["side"] == "BUY"]
    sells = df[df["side"] == "SELL"]
    if not buys.empty:
        fig.add_trace(go.Scatter(
            x=buys["timestamp"], y=buys["price"], mode="markers",
            name=f"{prefix}Buy",
            marker=dict(symbol="triangle-up", color=C_BUY,
                        size=(buys["quantity"].clip(1, 20) * 1.8).astype(int), **mkw),
            text=[f"qty={q}  px={p}" for q, p in zip(buys["quantity"], buys["price"])],
            hoverinfo="text+name",
        ), row=row, col=1)
    if not sells.empty:
        fig.add_trace(go.Scatter(
            x=sells["timestamp"], y=sells["price"], mode="markers",
            name=f"{prefix}Sell",
            marker=dict(symbol="triangle-down", color=C_SELL,
                        size=(sells["quantity"].clip(1, 20) * 1.8).astype(int), **mkw),
            text=[f"qty={q}  px={p}" for q, p in zip(sells["quantity"], sells["price"])],
            hoverinfo="text+name",
        ), row=row, col=1)


def _position_series(fills: pd.DataFrame | list[dict], symbol: str | None = None) -> pd.DataFrame:
    """Compute cumulative position from fills. Pass a list[dict] or a DataFrame."""
    if isinstance(fills, list):
        rows = fills if symbol is None else [f for f in fills if f["symbol"] == symbol]
        df = pd.DataFrame(rows) if rows else pd.DataFrame()
    else:
        df = fills if symbol is None else fills[fills["symbol"] == symbol].copy()

    if df.empty:
        return pd.DataFrame(columns=["timestamp", "position"])

    df = df.sort_values("timestamp").copy()
    if "signed_qty" not in df.columns:
        df["signed_qty"] = df.apply(
            lambda r: r["quantity"] if r["side"] == "BUY" else -r["quantity"], axis=1
        )
    df["position"] = df["signed_qty"].cumsum()
    return df[["timestamp", "position"]]


# ── PnL helpers ────────────────────────────────────────────────────────────

def _imc_per_product_pnl(log) -> pd.DataFrame:
    """Extract per-product profit_and_loss time series from activities log."""
    df = log.activities[["timestamp", "product", "profit_and_loss"]].copy()
    return df.rename(columns={"product": "symbol", "profit_and_loss": "pnl"}).sort_values("timestamp")


def _bt_per_product_pnl(backtest_data: dict, market_df_raw: pd.DataFrame | None) -> pd.DataFrame:
    """Compute MTM PnL per symbol over time, one day at a time, then chain.

    Each backtester day is independent (positions reset to 0). We compute
    intra-day MTM PnL from fills + mid prices, then carry the official
    end-of-day PnL (from product_summaries) as the offset for the next day.
    Timestamps are offset to be monotonically increasing across days.
    """
    rows: list[dict] = []
    ts_offset = 0
    pnl_carry: dict[str, float] = {}   # cumulative PnL from completed days, per symbol

    for day in backtest_data["days"]:
        curve = day.get("equity_curve", [])
        day_max_ts = curve[-1][0] if curve else 0
        tick = (curve[1][0] - curve[0][0]) if len(curve) >= 2 else 100

        raw_fills = day.get("fills", [])
        fills_df = pd.DataFrame(raw_fills) if raw_fills else pd.DataFrame()

        # Market data for this day only
        day_mkt: pd.DataFrame = pd.DataFrame()
        if market_df_raw is not None and not market_df_raw.empty:
            day_label = str(day["day"])
            if "day" in market_df_raw.columns:
                day_mkt = market_df_raw[market_df_raw["day"].astype(str) == day_label].copy()
            else:
                day_mkt = market_df_raw.copy()

        has_market = not day_mkt.empty and "product" in day_mkt.columns

        if not fills_df.empty:
            all_syms = sorted(fills_df["symbol"].unique())
        elif has_market:
            all_syms = sorted(day_mkt["product"].unique())
        else:
            all_syms = []

        for sym in all_syms:
            sym_fills = (fills_df[fills_df["symbol"] == sym].sort_values("timestamp").copy()
                         if not fills_df.empty else pd.DataFrame())

            if not sym_fills.empty:
                sym_fills["signed_qty"] = sym_fills.apply(
                    lambda r: r["quantity"] if r["side"] == "BUY" else -r["quantity"], axis=1
                )
                sym_fills["cash_delta"] = sym_fills.apply(
                    lambda r: -r["price"] * r["quantity"] if r["side"] == "BUY" else r["price"] * r["quantity"], axis=1
                )

            if has_market:
                sym_mkt = day_mkt[day_mkt["product"] == sym].sort_values("timestamp")
                timestamps = sorted(sym_mkt["timestamp"].unique())
            elif not sym_fills.empty:
                timestamps = sorted(sym_fills["timestamp"].unique())
            else:
                continue

            cash = 0.0
            position = 0
            fill_records = sym_fills.to_dict("records") if not sym_fills.empty else []
            fill_idx = 0
            carry = pnl_carry.get(sym, 0.0)

            for ts in timestamps:
                while fill_idx < len(fill_records) and fill_records[fill_idx]["timestamp"] <= ts:
                    cash += fill_records[fill_idx]["cash_delta"]
                    position += fill_records[fill_idx]["signed_qty"]
                    fill_idx += 1

                if has_market:
                    mkt_row = sym_mkt[sym_mkt["timestamp"] == ts]
                    if not mkt_row.empty:
                        bid = mkt_row["bid_price_1"].iloc[0]
                        ask = mkt_row["ask_price_1"].iloc[0]
                        mid = ((bid + ask) / 2.0 if pd.notna(bid) and pd.notna(ask)
                               else float(bid if pd.notna(bid) else ask if pd.notna(ask) else 0))
                    else:
                        mid = 0.0
                    intraday_pnl = cash + position * mid
                else:
                    intraday_pnl = cash  # realized only

                rows.append({"timestamp": ts + ts_offset, "symbol": sym, "pnl": carry + intraday_pnl})

        # Advance carry using official end-of-day PnL from product_summaries
        for sym, ps in day.get("product_summaries", {}).items():
            pnl_carry[sym] = pnl_carry.get(sym, 0.0) + ps["pnl"]

        ts_offset += day_max_ts + tick

    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["timestamp", "symbol", "pnl"])


def _add_pnl_traces(fig, pnl_df: pd.DataFrame, color_map: dict[str, str], row: int,
                    total_df: pd.DataFrame | None = None, total_color: str = C_PNL_TOTAL):
    """Add stacked per-product PnL areas and a total dotted line."""
    for sym in sorted(pnl_df["symbol"].unique()):
        df = pnl_df[pnl_df["symbol"] == sym].sort_values("timestamp")
        color = color_map.get(sym, "#868e96")
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["pnl"], name=f"{sym} PnL",
            line=dict(color=color, width=1.2),
            stackgroup="pnl", fillcolor=f"rgba({r},{g},{b},0.35)",
        ), row=row, col=1)
    if total_df is not None and not total_df.empty:
        fig.add_trace(go.Scatter(
            x=total_df["timestamp"], y=total_df["value"], name="Total PnL",
            line=dict(color=total_color, width=2, dash="dot"),
        ), row=row, col=1)


# ── IMC figure ─────────────────────────────────────────────────────────────

def _imc_sym_trades(trades: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    buyer_sub = trades.get("buyer", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    seller_sub = trades.get("seller", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    mask = (trades["symbol"] == symbol) & (buyer_sub | seller_sub)
    df = trades.loc[mask].copy()
    if df.empty:
        return df
    df["side"] = df["buyer"].fillna("").eq("SUBMISSION").map({True: "BUY", False: "SELL"})
    df["signed_qty"] = df["quantity"] * df["side"].map({"BUY": 1, "SELL": -1})
    return df.sort_values("timestamp")


def build_imc_figure(log, symbol: str) -> go.Figure:
    from prosperity.tooling.logs import _compute_activity_features

    act = log.activities[log.activities["product"] == symbol].copy().sort_values("timestamp")
    if act.empty:
        return go.Figure()

    act = _compute_activity_features(act)
    sym_trades = _imc_sym_trades(log.trades, symbol)
    pos_df = _position_series(sym_trades)

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.42, 0.14, 0.16, 0.28],
        subplot_titles=["Price & Trades", "Spread", "Position & Imbalance", "PnL"],
        vertical_spacing=0.07,
    )

    # Price
    fig.add_trace(go.Scatter(x=act["timestamp"], y=act["bid_price_1"], name="Best Bid",
        line=dict(color=C_BID, width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=act["timestamp"], y=act["ask_price_1"], name="Best Ask",
        line=dict(color=C_ASK, width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=act["timestamp"], y=act["fair"], name="Fair (EWM)",
        line=dict(color=C_FAIR, width=1.3, dash="dot")), row=1, col=1)
    _trade_markers(fig, sym_trades, row=1)

    # Spread
    fig.add_trace(go.Scatter(x=act["timestamp"], y=act["spread"], name="Spread",
        line=dict(color=C_SPREAD, width=1), fill="tozeroy",
        fillcolor="rgba(134,142,150,0.15)", showlegend=False), row=2, col=1)

    # Position
    if not pos_df.empty:
        fig.add_trace(go.Scatter(x=pos_df["timestamp"], y=pos_df["position"], name="Position",
            line=dict(color=C_POSITION, width=1.5), fill="tozeroy",
            fillcolor="rgba(112,72,232,0.12)"), row=3, col=1)

    # Imbalance
    bv = act["bid_volume_1"].clip(lower=1)
    av = act["ask_volume_1"].clip(lower=1)
    imb = (bv - av) / (bv + av)
    fig.add_trace(go.Bar(x=act["timestamp"], y=imb, name="Imbalance",
        marker_color=[C_IMB_POS if v > 0 else C_IMB_NEG for v in imb],
        opacity=0.6, showlegend=False), row=3, col=1)

    # PnL — per-product areas + total line
    pnl_df = _imc_per_product_pnl(log)
    symbols = sorted(pnl_df["symbol"].unique())
    color_map = _product_color_map(symbols)
    _add_pnl_traces(fig, pnl_df, color_map, row=4, total_df=log.graph if not log.graph.empty else None)

    fig.update_layout(height=820, legend=LEGEND_STYLE, **LAYOUT_BASE)
    fig.update_annotations(**SUBPLOT_TITLE_STYLE)
    return fig


# ── Backtest figure ────────────────────────────────────────────────────────

def _merge_backtest_days(backtest_data: dict, market_df_raw: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Merge all days with monotonically increasing timestamps.

    Each day's timestamps start at 0 and repeat across days, so we offset each
    day by (previous_day_max_ts + one_tick) to make them sequential. The same
    offset is applied to fills, equity curve, and market price data so all charts
    share a consistent x-axis.
    """
    all_fills: list[dict] = []
    equity_rows: list[dict] = []
    market_frames: list[pd.DataFrame] = []
    pnl_offset = 0.0
    ts_offset = 0

    for day in backtest_data["days"]:
        curve = day.get("equity_curve", [])
        fills = day.get("fills", [])

        # Determine tick size and max ts from the equity curve
        day_max_ts = curve[-1][0] if curve else 0
        tick = (curve[1][0] - curve[0][0]) if len(curve) >= 2 else 100

        # Equity curve: offset timestamps, chain PnL
        for ts, val in curve:
            equity_rows.append({"timestamp": ts + ts_offset, "value": val + pnl_offset})
        if curve:
            pnl_offset += curve[-1][1]

        # Fills: offset timestamps
        for f in fills:
            all_fills.append({**f, "timestamp": f["timestamp"] + ts_offset})

        # Market data: offset timestamps for this day
        if market_df_raw is not None and not market_df_raw.empty:
            day_label = str(day["day"])
            if "day" in market_df_raw.columns:
                day_mkt = market_df_raw[market_df_raw["day"].astype(str) == day_label].copy()
            else:
                day_mkt = market_df_raw.copy()
            if not day_mkt.empty:
                day_mkt["timestamp"] = day_mkt["timestamp"] + ts_offset
                market_frames.append(day_mkt)

        ts_offset += day_max_ts + tick

    fills_df = pd.DataFrame(all_fills) if all_fills else pd.DataFrame()
    equity_df = pd.DataFrame(equity_rows) if equity_rows else pd.DataFrame()
    market_df = pd.concat(market_frames, ignore_index=True) if market_frames else pd.DataFrame()
    return fills_df, equity_df, market_df


def build_backtest_figure(backtest_data: dict, symbol: str, market_df_raw: pd.DataFrame | None) -> go.Figure:
    fills_df, equity_df, market_df = _merge_backtest_days(backtest_data, market_df_raw)

    sym_fills = fills_df[fills_df["symbol"] == symbol].copy() if not fills_df.empty else pd.DataFrame()
    if not sym_fills.empty:
        sym_fills["side"] = sym_fills["side"].str.upper()

    has_market = not market_df.empty
    n_rows = 3 if has_market else 2
    heights = [0.45, 0.20, 0.35] if has_market else [0.35, 0.65]
    titles = (["Price & Fills", "Position", "Equity PnL"] if has_market
              else ["Position", "Equity PnL"])

    fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=heights, subplot_titles=titles, vertical_spacing=0.08)

    price_row = 1
    pos_row   = 2 if has_market else 1
    pnl_row   = 3 if has_market else 2

    # Price + fills
    if has_market:
        sym_mkt = market_df[market_df["product"] == symbol].sort_values("timestamp")
        if not sym_mkt.empty:
            fig.add_trace(go.Scatter(x=sym_mkt["timestamp"], y=sym_mkt["bid_price_1"],
                name="Best Bid", line=dict(color=C_BID, width=1)), row=price_row, col=1)
            fig.add_trace(go.Scatter(x=sym_mkt["timestamp"], y=sym_mkt["ask_price_1"],
                name="Best Ask", line=dict(color=C_ASK, width=1)), row=price_row, col=1)
        _trade_markers(fig, sym_fills, row=price_row)

    # Position
    pos_df = _position_series(sym_fills)
    if not pos_df.empty:
        fig.add_trace(go.Scatter(x=pos_df["timestamp"], y=pos_df["position"], name="Position",
            line=dict(color=C_POSITION, width=1.5), fill="tozeroy",
            fillcolor="rgba(112,72,232,0.12)"), row=pos_row, col=1)

    # Equity PnL — per-product stacked areas + total line
    per_prod_pnl = _bt_per_product_pnl(backtest_data, market_df_raw)
    if not per_prod_pnl.empty:
        bt_color_map = _product_color_map(sorted(per_prod_pnl["symbol"].unique()))
        _add_pnl_traces(fig, per_prod_pnl, bt_color_map, row=pnl_row,
                        total_df=equity_df if not equity_df.empty else None)
    elif not equity_df.empty:
        fig.add_trace(go.Scatter(x=equity_df["timestamp"], y=equity_df["value"],
            name="Total PnL", line=dict(color=C_PNL_TOTAL, width=2)), row=pnl_row, col=1)

    height = 680 if has_market else 480
    fig.update_layout(height=height, legend=LEGEND_STYLE, **LAYOUT_BASE)
    fig.update_annotations(**SUBPLOT_TITLE_STYLE)
    return fig


# ── Dash app ───────────────────────────────────────────────────────────────

_PAGE_STYLE = {
    "maxWidth": "1280px",
    "margin": "0 auto",
    "padding": "0 24px 40px",
    "fontFamily": "Inter, system-ui, sans-serif",
    "backgroundColor": "#f8f9fa",
    "minHeight": "100vh",
}

_HEADER_STYLE = {
    "padding": "20px 0 16px",
    "borderBottom": "2px solid #dee2e6",
    "marginBottom": "24px",
}

def _section_header(label, color):
    return html.Div([
        html.Span("▌", style={"color": color, "marginRight": "8px", "fontSize": "20px"}),
        html.Span(label, style={"fontSize": "16px", "fontWeight": "600", "color": "#212529"}),
    ], style={"display": "flex", "alignItems": "center", "padding": "8px 0 4px"})


def _divider():
    return html.Hr(style={"margin": "32px 0", "borderColor": "#dee2e6", "borderWidth": "1px"})


_CARD_STYLE = {
    "background": "#ffffff",
    "borderRadius": "8px",
    "boxShadow": "0 1px 3px rgba(0,0,0,0.08)",
    "padding": "4px 0 0",
    "marginBottom": "24px",
}


def run_dash(log=None, backtest_data: dict | None = None, data_dir: str | None = None):
    if not HAS_DASH:
        print("dash not installed. Run: pip install dash")
        return

    imc_symbols: list[str] = sorted(log.activities["product"].dropna().unique()) if log else []
    bt_symbols: list[str] = []
    if backtest_data:
        all_fills = [f for d in backtest_data["days"] for f in d["fills"]]
        bt_symbols = sorted({f["symbol"] for f in all_fills})

    all_symbols = sorted(set(imc_symbols) | set(bt_symbols))
    if not all_symbols:
        print("No symbols found.")
        return

    # Pre-load raw market data per day (timestamp offsetting happens inside _merge_backtest_days)
    market_df_raw: pd.DataFrame | None = None
    if data_dir and backtest_data:
        from prosperity.tooling.data import MarketDataLoader
        loader = MarketDataLoader(data_dir)
        round_num = backtest_data.get("round", 0)
        frames = []
        for day in backtest_data["days"]:
            try:
                df = loader.load_prices(f"prices_round_{round_num}_day_{day['day']}.csv")
                df["day"] = str(day["day"])
                frames.append(df)
            except Exception:
                pass
        market_df_raw = pd.concat(frames, ignore_index=True) if frames else None

    # Build subtitle
    parts = []
    if log:
        parts.append(f"IMC · {log.submission_id}  |  profit = {log.profit}")
    if backtest_data:
        total = sum(d["pnl"] for d in backtest_data["days"])
        days_str = ", ".join(str(d["day"]) for d in backtest_data["days"])
        parts.append(f"Backtest · {backtest_data.get('strategy', '')}  |  PnL = {total:+.2f}  (days {days_str})")

    app = Dash(__name__, title="Prosperity Dashboard")

    layout_children: list = [
        html.Div([
            html.H2("Prosperity Trading Dashboard",
                style={"margin": "0 0 4px", "fontSize": "22px", "color": "#1971c2", "fontWeight": "700"}),
            *[html.P(p, style={"margin": "2px 0", "color": "#495057", "fontSize": "13px"}) for p in parts],
        ], style=_HEADER_STYLE),

        html.Div([
            html.Label("Product", style={"fontWeight": "600", "fontSize": "13px", "color": "#495057",
                                          "marginRight": "10px"}),
            dcc.Dropdown(id="symbol-select",
                options=[{"label": s, "value": s} for s in all_symbols],
                value=all_symbols[0],
                clearable=False,
                style={"width": "200px", "fontSize": "13px"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "20px"}),
    ]

    _graph_config = {"displayModeBar": True, "displaylogo": False,
                     "modeBarButtonsToKeep": ["zoom2d", "pan2d", "resetScale2d", "toImage"]}

    if log:
        layout_children += [
            _section_header("IMC Official Results", "#1971c2"),
            html.Div(dcc.Graph(id="imc-chart", config=_graph_config), style=_CARD_STYLE),
        ]

    if log and backtest_data:
        layout_children.append(_divider())

    if backtest_data:
        layout_children += [
            _section_header("Internal Backtest", "#2f9e44"),
            html.Div(dcc.Graph(id="bt-chart", config=_graph_config), style=_CARD_STYLE),
        ]

    app.layout = html.Div(layout_children, style=_PAGE_STYLE)

    if log:
        @app.callback(Output("imc-chart", "figure"), Input("symbol-select", "value"))
        def update_imc(symbol):
            return build_imc_figure(log, symbol) if symbol else go.Figure()

    if backtest_data:
        @app.callback(Output("bt-chart", "figure"), Input("symbol-select", "value"))
        def update_bt(symbol):
            return build_backtest_figure(backtest_data, symbol, market_df_raw) if symbol else go.Figure()

    print(f"Dashboard → http://127.0.0.1:8050")
    app.run(debug=False, port=8050)


# ── CLI ────────────────────────────────────────────────────────────────────

def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prosperity interactive dashboard")
    parser.add_argument("--log", help="Path to official IMC JSON or LOG file")
    parser.add_argument("--backtest-json", help="Path to backtest JSON (from --json-out)")
    parser.add_argument("--data-dir", default=None,
        help="Market data directory (enables price chart in backtest view)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.log and not args.backtest_json:
        parser.error("Provide at least one of --log or --backtest-json")

    log = None
    if args.log:
        from prosperity.tooling.logs import load_official_log
        log = load_official_log(args.log)
        print(f"Loaded IMC log: {log.submission_id}  profit={log.profit}")

    backtest_data = None
    if args.backtest_json:
        backtest_data = json.loads(Path(args.backtest_json).read_text(encoding="utf-8"))
        total = sum(d["pnl"] for d in backtest_data["days"])
        print(f"Loaded backtest: strategy={backtest_data.get('strategy')}  "
              f"days={[d['day'] for d in backtest_data['days']]}  total_pnl={total:.2f}")

    run_dash(log=log, backtest_data=backtest_data, data_dir=args.data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
