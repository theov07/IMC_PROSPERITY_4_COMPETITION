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
from werkzeug.serving import make_server

try:
    from dash import Dash, dcc, html, Input, Output
    HAS_DASH = True
except ImportError:
    HAS_DASH = False


# ── Neon trace palette (catppuccin-mocha — works in dark and light) ────────
C_BID      = "#5b8fd4"   # darker blue for best bid
C_ASK      = "#d9556e"   # darker red for best ask
C_FAIR     = "#a6e3a1"   # green
C_BUY      = "#a6e3a1"   # green triangles
C_SELL     = "#f38ba8"   # coral triangles
C_SPREAD   = "#89dceb"   # sky cyan fill
C_POSITION = "#cba6f7"   # mauve purple
C_IMB_POS  = "#a6e3a1"   # green bars
C_IMB_NEG  = "#f38ba8"   # red bars
C_PNL_TOTAL = "#f9e2af"  # yellow total line

# Per-product color palette
PRODUCT_COLORS = ["#89b4fa", "#f9e2af", "#a6e3a1", "#f38ba8", "#cba6f7", "#89dceb"]


def _product_color_map(symbols: list[str]) -> dict[str, str]:
    return {sym: PRODUCT_COLORS[i % len(PRODUCT_COLORS)] for i, sym in enumerate(sorted(symbols))}


# ── Themes ─────────────────────────────────────────────────────────────────
THEMES: dict[str, dict] = {
    "dark": {
        "page_bg":      "#1e1e2e",
        "outer_bg":     "#13131f",   # full-page backdrop
        "card_bg":      "#181825",
        "border":       "#313244",
        "text":         "#cdd6f4",
        "text_muted":   "#a6adc8",
        "accent":       "#89b4fa",
        "section_bar":  "#cba6f7",
        "divider":      "#313244",
        "btn_bg":       "#313244",
        "btn_hover":    "#45475a",
        "plotly_tpl":   "plotly_dark",
        "paper_bg":     "#181825",
        "plot_bg":      "#1e1e2e",
        "legend_bg":    "rgba(24,24,37,0.92)",
        "legend_border":"#313244",
        "font_color":   "#cdd6f4",
        "subplot_title":"#a6adc8",
    },
    "light": {
        "page_bg":      "#f8f9fa",
        "outer_bg":     "#e9ecef",
        "card_bg":      "#ffffff",
        "border":       "#dee2e6",
        "text":         "#212529",
        "text_muted":   "#495057",
        "accent":       "#1971c2",
        "section_bar":  "#7048e8",
        "divider":      "#dee2e6",
        "btn_bg":       "#e9ecef",
        "btn_hover":    "#dee2e6",
        "plotly_tpl":   "plotly_white",
        "paper_bg":     "#ffffff",
        "plot_bg":      "#f8f9fa",
        "legend_bg":    "rgba(255,255,255,0.92)",
        "legend_border":"#dee2e6",
        "font_color":   "#212529",
        "subplot_title":"#495057",
    },
}


def _layout_base(theme: str) -> dict:
    t = THEMES[theme]
    return dict(
        template=t["plotly_tpl"],
        hovermode="x unified",
        margin=dict(l=60, r=40, t=40, b=60),
        plot_bgcolor=t["plot_bg"],
        paper_bgcolor=t["paper_bg"],
        font=dict(family="Inter, sans-serif", size=12, color=t["font_color"]),
        legend=dict(
            orientation="h",
            yanchor="top", y=-0.04,
            xanchor="center", x=0.5,
            bgcolor=t["legend_bg"],
            bordercolor=t["legend_border"],
            borderwidth=1,
            font=dict(size=11, color=t["font_color"]),
        ),
    )


def _subplot_title_style(theme: str) -> dict:
    return dict(font=dict(size=12, color=THEMES[theme]["subplot_title"]))


# ── EWMA smoothing helper ──────────────────────────────────────────────────

def _smooth(series: "pd.Series", n: int) -> "pd.Series":
    """Apply EWMA with half-life = n/3 ticks.  n=0 → raw data."""
    if n <= 0:
        return series
    half_life = n / 3.0
    alpha = 1.0 - 2.0 ** (-1.0 / half_life)
    return series.ewm(alpha=alpha, adjust=False).mean()


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


def build_imc_figure(log, symbol: str, theme: str = "dark", smooth_n: int = 0, line_shape: str = "linear") -> go.Figure:
    _mode = "lines+markers" if line_shape == "hv" else "lines"
    _marker = dict(size=3) if line_shape == "hv" else {}
    from prosperity.tooling.logs import _compute_activity_features, _parse_lambda_logs

    act = log.activities[log.activities["product"] == symbol].copy().sort_values("timestamp")
    if act.empty:
        return go.Figure()

    act = _compute_activity_features(act)
    sym_trades = _imc_sym_trades(log.trades, symbol)
    pos_df = _position_series(sym_trades)
    lambda_df = _parse_lambda_logs(log.runtime_logs)
    lambda_sym = lambda_df[lambda_df["product"] == symbol] if not lambda_df.empty else pd.DataFrame()

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.42, 0.14, 0.16, 0.28],
        subplot_titles=["Price & Trades", "Spread", "Position & Imbalance", "PnL"],
        vertical_spacing=0.07,
    )

    # Price (with optional EWMA smoothing)
    fig.add_trace(go.Scatter(x=act["timestamp"], y=_smooth(act["bid_price_1"], smooth_n),
        name="Best Bid", mode=_mode, marker=dict(**_marker, color=C_BID),
        line=dict(color=C_BID, width=1, shape=line_shape)), row=1, col=1)
    fig.add_trace(go.Scatter(x=act["timestamp"], y=_smooth(act["ask_price_1"], smooth_n),
        name="Best Ask", mode=_mode, marker=dict(**_marker, color=C_ASK),
        line=dict(color=C_ASK, width=1, shape=line_shape)), row=1, col=1)
    fig.add_trace(go.Scatter(x=act["timestamp"], y=_smooth(act["fair"], smooth_n),
        name="Fair (EWM)", mode=_mode, marker=dict(**_marker, color=C_FAIR),
        line=dict(color=C_FAIR, width=1.3, shape=line_shape)), row=1, col=1)
    _trade_markers(fig, sym_trades, row=1)

    # Strategy lambda logs: reservation price + MM quotes
    if not lambda_sym.empty:
        fig.add_trace(go.Scatter(x=lambda_sym["timestamp"], y=_smooth(lambda_sym["reservation"], smooth_n),
            name="Reservation", mode=_mode, marker=dict(**_marker, color=C_FEATURE_PALETTE[0]),
            line=dict(color=C_FEATURE_PALETTE[0], width=1.2, shape=line_shape)), row=1, col=1)
        fig.add_trace(go.Scatter(x=lambda_sym["timestamp"], y=_smooth(lambda_sym["bid_price"], smooth_n),
            name="MM Bid (log)", mode=_mode, marker=dict(**_marker, color=C_QUOTE_BID),
            line=dict(color=C_QUOTE_BID, width=1, shape=line_shape)), row=1, col=1)
        fig.add_trace(go.Scatter(x=lambda_sym["timestamp"], y=_smooth(lambda_sym["ask_price"], smooth_n),
            name="MM Ask (log)", mode=_mode, marker=dict(**_marker, color=C_QUOTE_ASK),
            line=dict(color=C_QUOTE_ASK, width=1, shape=line_shape)), row=1, col=1)

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

    fig.update_layout(height=820, uirevision=f"imc-{symbol}", **_layout_base(theme))
    fig.update_annotations(**_subplot_title_style(theme))
    return fig


# ── Backtest figure ────────────────────────────────────────────────────────

def _merge_backtest_days(backtest_data: dict, market_df_raw: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Merge all days with monotonically increasing timestamps.

    Each day's timestamps start at 0 and repeat across days, so we offset each
    day by (previous_day_max_ts + one_tick) to make them sequential. The same
    offset is applied to fills, quotes, feature_ticks, equity curve, and market
    price data so all charts share a consistent x-axis.
    """
    all_fills: list[dict] = []
    all_quotes: list[dict] = []
    all_features: list[dict] = []
    equity_rows: list[dict] = []
    market_frames: list[pd.DataFrame] = []
    pnl_offset = 0.0
    ts_offset = 0

    for day in backtest_data["days"]:
        curve = day.get("equity_curve", [])
        fills = day.get("fills", [])
        quotes = day.get("quotes", [])
        feature_ticks = day.get("feature_ticks", [])

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

        # Quotes: offset timestamps
        for q in quotes:
            all_quotes.append({**q, "timestamp": q["timestamp"] + ts_offset})

        # Feature ticks: offset timestamps (each row has timestamp + symbol + arbitrary feature cols)
        for ft in feature_ticks:
            all_features.append({**ft, "timestamp": ft["timestamp"] + ts_offset})

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
    quotes_df = pd.DataFrame(all_quotes) if all_quotes else pd.DataFrame()
    features_df = pd.DataFrame(all_features) if all_features else pd.DataFrame()
    equity_df = pd.DataFrame(equity_rows) if equity_rows else pd.DataFrame()
    market_df = pd.concat(market_frames, ignore_index=True) if market_frames else pd.DataFrame()
    return fills_df, quotes_df, features_df, equity_df, market_df


C_QUOTE_BID = "#b9d3fd"   # very light blue for MM bid quotes
C_QUOTE_ASK = "#fbbdca"   # very light red/pink for MM ask quotes


C_FEATURE_PALETTE = ["#fab387", "#cba6f7", "#94e2d5", "#f9e2af", "#89dceb"]


def build_backtest_figure(backtest_data: dict, symbol: str, market_df_raw: pd.DataFrame | None,
                          theme: str = "dark", show_quotes: bool = False,
                          smooth_n: int = 0, line_shape: str = "linear",
                          _precomputed: tuple | None = None,
                          _per_prod_pnl: pd.DataFrame | None = None) -> go.Figure:
    _mode = "lines+markers" if line_shape == "hv" else "lines"
    _marker = dict(size=3) if line_shape == "hv" else {}
    if _precomputed is not None:
        fills_df, quotes_df, features_df, equity_df, market_df = _precomputed
    else:
        fills_df, quotes_df, features_df, equity_df, market_df = _merge_backtest_days(backtest_data, market_df_raw)

    sym_fills = fills_df[fills_df["symbol"] == symbol].copy() if not fills_df.empty else pd.DataFrame()
    if not sym_fills.empty:
        sym_fills["side"] = sym_fills["side"].str.upper()

    sym_quotes = pd.DataFrame()
    if show_quotes and not quotes_df.empty:
        sym_quotes = quotes_df[quotes_df["symbol"] == symbol].sort_values("timestamp").copy()

    # Strategy feature prices for this symbol (e.g. reservation price)
    sym_features: pd.DataFrame = pd.DataFrame()
    if not features_df.empty and "symbol" in features_df.columns:
        sym_features = features_df[features_df["symbol"] == symbol].sort_values("timestamp").copy()

    has_market = not market_df.empty
    n_rows = 3 if has_market else 2
    heights = [0.45, 0.20, 0.35] if has_market else [0.35, 0.65]
    titles = (["Price & Fills", "Position", "Equity PnL"] if has_market
              else ["Position", "Equity PnL"])

    fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=heights, subplot_titles=titles, vertical_spacing=0.05)

    price_row = 1
    pos_row   = 2 if has_market else 1
    pnl_row   = 3 if has_market else 2

    # Price + fills
    if has_market:
        sym_mkt = market_df[market_df["product"] == symbol].sort_values("timestamp")
        if not sym_mkt.empty:
            fig.add_trace(go.Scatter(x=sym_mkt["timestamp"],
                y=_smooth(sym_mkt["bid_price_1"], smooth_n),
                name="Best Bid", mode=_mode, marker=dict(**_marker, color=C_BID),
                line=dict(color=C_BID, width=1, shape=line_shape)), row=price_row, col=1)
            fig.add_trace(go.Scatter(x=sym_mkt["timestamp"],
                y=_smooth(sym_mkt["ask_price_1"], smooth_n),
                name="Best Ask", mode=_mode, marker=dict(**_marker, color=C_ASK),
                line=dict(color=C_ASK, width=1, shape=line_shape)), row=price_row, col=1)
            mid = (sym_mkt["bid_price_1"] + sym_mkt["ask_price_1"]) / 2
            fig.add_trace(go.Scatter(x=sym_mkt["timestamp"], y=_smooth(mid, smooth_n),
                name="Mid", mode=_mode, marker=dict(**_marker, color=C_FAIR),
                line=dict(color=C_FAIR, width=1, shape=line_shape)), row=price_row, col=1)

        # MM quotes overlay
        if not sym_quotes.empty:
            bid_q = sym_quotes.dropna(subset=["bid"])
            ask_q = sym_quotes.dropna(subset=["ask"])
            if not bid_q.empty:
                fig.add_trace(go.Scatter(
                    x=bid_q["timestamp"], y=_smooth(bid_q["bid"], smooth_n),
                    name="MM Bid Quote", mode=_mode, marker=dict(**_marker, color=C_QUOTE_BID),
                    line=dict(color=C_QUOTE_BID, width=1, shape=line_shape),
                ), row=price_row, col=1)
            if not ask_q.empty:
                fig.add_trace(go.Scatter(
                    x=ask_q["timestamp"], y=_smooth(ask_q["ask"], smooth_n),
                    name="MM Ask Quote", mode=_mode, marker=dict(**_marker, color=C_QUOTE_ASK),
                    line=dict(color=C_QUOTE_ASK, width=1, shape=line_shape),
                ), row=price_row, col=1)

        # Strategy feature price lines (e.g. reservation price)
        if not sym_features.empty:
            feature_cols = [c for c in sym_features.columns if c not in ("timestamp", "symbol")]
            for i, feat in enumerate(feature_cols):
                col_data = sym_features.dropna(subset=[feat])
                if col_data.empty:
                    continue
                color = C_FEATURE_PALETTE[i % len(C_FEATURE_PALETTE)]
                fig.add_trace(go.Scatter(
                    x=col_data["timestamp"], y=_smooth(col_data[feat], smooth_n),
                    name=feat, mode=_mode, marker=dict(**_marker, color=color),
                    line=dict(color=color, width=1.3, shape=line_shape),
                ), row=price_row, col=1)

        _trade_markers(fig, sym_fills, row=price_row)

    # Position
    pos_df = _position_series(sym_fills)
    if not pos_df.empty:
        fig.add_trace(go.Scatter(x=pos_df["timestamp"], y=pos_df["position"], name="Position",
            line=dict(color=C_POSITION, width=1.5), fill="tozeroy",
            fillcolor="rgba(112,72,232,0.12)"), row=pos_row, col=1)

    # Equity PnL — per-product stacked areas + total line
    per_prod_pnl = _per_prod_pnl if _per_prod_pnl is not None else _bt_per_product_pnl(backtest_data, market_df_raw)
    if not per_prod_pnl.empty:
        bt_color_map = _product_color_map(sorted(per_prod_pnl["symbol"].unique()))
        _add_pnl_traces(fig, per_prod_pnl, bt_color_map, row=pnl_row,
                        total_df=equity_df if not equity_df.empty else None)
    elif not equity_df.empty:
        fig.add_trace(go.Scatter(x=equity_df["timestamp"], y=equity_df["value"],
            name="Total PnL", line=dict(color=C_PNL_TOTAL, width=2)), row=pnl_row, col=1)

    height = 800 #if has_market else 700
    fig.update_layout(height=height, uirevision=f"bt-{symbol}", **_layout_base(theme))
    fig.update_annotations(**_subplot_title_style(theme))
    return fig


# ── Dash app ───────────────────────────────────────────────────────────────

_GRAPH_CONFIG = {"displayModeBar": True, "displaylogo": False,
                 "modeBarButtonsToKeep": ["zoom2d", "pan2d", "resetScale2d", "toImage"]}


def _page_style(theme: str) -> dict:
    t = THEMES[theme]
    return {
        "backgroundColor": t["outer_bg"],
        "minHeight": "100vh",
        "fontFamily": "Inter, system-ui, sans-serif",
        "color": t["text"],
    }


def _inner_style(theme: str) -> dict:
    return {
        #"maxWidth": "1280px",
        "margin": "0 auto",
        "padding": "0 40px 60px",
    }


def _header_style(theme: str) -> dict:
    return {
        "padding": "24px 0 16px",
        "borderBottom": f"2px solid {THEMES[theme]['border']}",
        "marginBottom": "28px",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
    }


def _card_style(theme: str) -> dict:
    t = THEMES[theme]
    return {
        "background": t["card_bg"],
        "borderRadius": "10px",
        "border": f"1px solid {t['border']}",
        "boxShadow": "0 4px 24px rgba(0,0,0,0.35)" if theme == "dark" else "0 1px 4px rgba(0,0,0,0.08)",
        "padding": "4px 0 0",
        "marginBottom": "24px",
    }


def _section_header(label: str, theme: str) -> "html.Div":
    t = THEMES[theme]
    return html.Div([
        html.Span("▌", style={"color": t["section_bar"], "marginRight": "8px", "fontSize": "20px"}),
        html.Span(label, style={"fontSize": "15px", "fontWeight": "700", "color": t["text"],
                                "letterSpacing": "0.02em"}),
    ], style={"display": "flex", "alignItems": "center", "padding": "10px 0 6px"})


def _divider(theme: str) -> "html.Hr":
    return html.Hr(style={"margin": "32px 0", "borderColor": THEMES[theme]["divider"], "borderWidth": "1px"})


def _toggle_btn_style(theme: str) -> dict:
    t = THEMES[theme]
    return {
        "background": t["btn_bg"],
        "color": t["text"],
        "border": f"1px solid {t['border']}",
        "borderRadius": "6px",
        "padding": "6px 14px",
        "fontSize": "13px",
        "cursor": "pointer",
        "fontFamily": "Inter, system-ui, sans-serif",
        "fontWeight": "500",
        "flexShrink": "0",
    }


def run_dash(log=None, backtest_data: dict | None = None, data_dir: str | None = None):
    if not HAS_DASH:
        print("dash not installed. Run: pip install dash")
        return

    from dash import State

    imc_symbols: list[str] = sorted(log.activities["product"].dropna().unique()) if log else []
    bt_symbols: list[str] = []
    if backtest_data:
        all_fills = [f for d in backtest_data["days"] for f in d["fills"]]
        bt_symbols = sorted({f["symbol"] for f in all_fills})

    all_symbols = sorted(set(imc_symbols) | set(bt_symbols))
    if not all_symbols:
        print("No symbols found.")
        return

    # Pre-load raw market data
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

    # Subtitle lines
    parts = []
    if log:
        parts.append(f"IMC · {log.submission_id}  |  profit = {log.profit}")
    if backtest_data:
        total = sum(d["pnl"] for d in backtest_data["days"])
        days_str = ", ".join(str(d["day"]) for d in backtest_data["days"])
        parts.append(f"Backtest · {backtest_data.get('strategy', '')}  |  PnL = {total:+.2f}  (days {days_str})")

    # ── Precompute expensive data merges once at startup ──
    bt_precomputed: tuple | None = None
    bt_per_prod_pnl: pd.DataFrame = pd.DataFrame()
    if backtest_data:
        bt_precomputed = _merge_backtest_days(backtest_data, market_df_raw)
        bt_per_prod_pnl = _bt_per_product_pnl(backtest_data, market_df_raw)
        print("Precomputed backtest data.")

    app = Dash(__name__, title="Prosperity Trading Dashboard")

    # ── Static layout shell (theme-independent IDs) ──
    chart_ids: list[str] = []
    if log:
        chart_ids.append("imc-chart")
    if backtest_data:
        chart_ids.append("bt-chart")

    app.layout = html.Div(id="outer-wrapper", children=[
        dcc.Store(id="theme-store", data="dark"),
        # Invisible div — clientside callback writes dynamic CSS into document.head
        html.Div(id="theme-css", style={"display": "none"}),
        html.Div(id="inner-wrapper", children=[
            # Header
            html.Div(id="header-div", children=[
                html.Div([
                    html.H2("Prosperity Trading Dashboard", id="title-h2",
                        style={"margin": "0 0 4px", "fontSize": "22px", "fontWeight": "700"}),
                    *[html.P(p, id=f"subtitle-{i}",
                             style={"margin": "2px 0", "fontSize": "13px"})
                      for i, p in enumerate(parts)],
                ]),
                html.Button("☀  Light", id="theme-btn",
                    style={"background": "#313244", "color": "#cdd6f4",
                           "border": "1px solid #45475a", "borderRadius": "6px",
                           "padding": "6px 14px", "fontSize": "13px", "cursor": "pointer",
                           "fontFamily": "Inter, system-ui, sans-serif", "fontWeight": "500"}),
            ]),
            # Controls
            html.Div(id="controls-bar", children=[
                html.Label("Product", id="product-label",
                    style={"fontWeight": "600", "fontSize": "13px", "marginRight": "10px"}),
                dcc.Dropdown(id="symbol-select",
                    options=[{"label": s, "value": s} for s in all_symbols],
                    value=all_symbols[0], clearable=False,
                    style={"width": "200px", "fontSize": "13px"}),
                *([
                    dcc.Checklist(
                        id="quotes-toggle",
                        options=[{"label": " Show MM quotes", "value": "show"}],
                        value=[],
                        style={"marginLeft": "24px", "fontSize": "13px"},
                        inputStyle={"marginRight": "6px"},
                    )
                ] if backtest_data else [html.Div(id="quotes-toggle")]),
                dcc.Checklist(
                    id="step-toggle",
                    options=[{"label": " Step chart (hv)", "value": "hv"}],
                    value=[],
                    style={"marginLeft": "24px", "fontSize": "13px"},
                    inputStyle={"marginRight": "6px"},
                ),
                dcc.Checklist(
                    id="smooth-toggle",
                    options=[{"label": " Smooth prices", "value": "on"}],
                    value=[],
                    style={"marginLeft": "24px", "fontSize": "13px"},
                    inputStyle={"marginRight": "6px"},
                ),
                html.Div([
                    html.Span("N=", id="smooth-n-label", style={"fontSize": "12px", "marginRight": "4px"}),
                    dcc.Slider(
                        id="smooth-n",
                        min=0, max=100, step=1, value=20,
                        marks={0: "0", 25: "25", 50: "50", 75: "75", 100: "100"},
                        tooltip={"placement": "top", "always_visible": False},
                        updatemode="drag",
                        included=True,
                    ),
                ], style={"display": "flex", "alignItems": "center", "marginLeft": "12px", "width": "220px"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "20px"}),
            # Chart area (rebuilt on theme/symbol change)
            html.Div(id="charts-area"),
        ]),
    ])

    # ── Theme toggle ──
    app.clientside_callback(
        """
        function(n, current) {
            if (!n) return current || 'dark';
            return current === 'dark' ? 'light' : 'dark';
        }
        """,
        Output("theme-store", "data"),
        Input("theme-btn", "n_clicks"),
        State("theme-store", "data"),
    )

    # ── Inject CSS directly into document.head via clientside callback ──
    # Themes as JSON so the clientside function can build CSS without a server round-trip
    _THEME_CSS_DATA = {
        name: {
            "card_bg":  t["card_bg"],
            "border":   t["border"],
            "btn_bg":   t["btn_bg"],
            "text":     t["text"],
            "text_muted": t["text_muted"],
            "accent":   t["accent"],
        }
        for name, t in THEMES.items()
    }
    import json as _json
    app.clientside_callback(
        f"""
        function(theme) {{
            var themes = {_json.dumps(_THEME_CSS_DATA)};
            var t = themes[theme] || themes['dark'];
            var css = [
                '.Select-control {{ background-color: ' + t.card_bg + ' !important; border-color: ' + t.border + ' !important; }}',
                '.Select-menu-outer {{ background-color: ' + t.card_bg + ' !important; border-color: ' + t.border + ' !important; }}',
                '.Select-option {{ background-color: ' + t.card_bg + ' !important; color: ' + t.text + ' !important; }}',
                '.Select-option.is-focused {{ background-color: ' + t.btn_bg + ' !important; }}',
                '.Select-value-label {{ color: #212529 !important; }}',
                '.Select-placeholder {{ color: #6c757d !important; }}',
                '.VirtualizedSelectOption {{ background-color: ' + t.card_bg + ' !important; color: ' + t.text + ' !important; }}',
                '.dash-checklist label {{ color: ' + t.text + ' !important; }}',
                '.rc-slider-mark-text {{ color: ' + t.text + ' !important; }}',
                '.rc-slider-rail {{ background-color: ' + t.border + ' !important; }}',
                '.rc-slider-track {{ background-color: ' + t.accent + ' !important; }}',
                '.rc-slider-handle {{ border-color: ' + t.accent + ' !important; background-color: ' + t.card_bg + ' !important; }}'
            ].join('\\n');
            var el = document.getElementById('prosperity-theme-style');
            if (!el) {{
                el = document.createElement('style');
                el.id = 'prosperity-theme-style';
                document.head.appendChild(el);
            }}
            el.textContent = css;
            return '';
        }}
        """,
        Output("theme-css", "children"),
        Input("theme-store", "data"),
    )

    # ── Update chrome on theme change ──
    @app.callback(
        Output("outer-wrapper", "style"),
        Output("inner-wrapper", "style"),
        Output("header-div", "style"),
        Output("theme-btn", "children"),
        Output("theme-btn", "style"),
        Output("title-h2", "style"),
        Output("controls-bar", "style"),
        Input("theme-store", "data"),
    )
    def update_theme(theme):
        t = THEMES[theme]
        btn_label = "☀  Light" if theme == "dark" else "🌙  Dark"
        return (
            _page_style(theme),
            _inner_style(theme),
            _header_style(theme),
            btn_label,
            _toggle_btn_style(theme),
            {"margin": "0 0 4px", "fontSize": "22px", "fontWeight": "700", "color": t["accent"]},
            {"display": "flex", "alignItems": "center", "marginBottom": "20px", "color": t["text"]},
        )

    # ── Rebuild charts area on theme, symbol, quotes-toggle, or smooth change ──
    @app.callback(
        Output("charts-area", "children"),
        Input("theme-store", "data"),
        Input("symbol-select", "value"),
        Input("quotes-toggle", "value"),
        Input("smooth-toggle", "value"),
        Input("smooth-n", "value"),
        Input("step-toggle", "value"),
    )
    def update_charts(theme, symbol, quotes_value, smooth_value, smooth_n_raw, step_value):
        show_quotes = bool(quotes_value)
        smooth_n = int(smooth_n_raw or 0) if smooth_value else 0
        line_shape = "hv" if step_value else "linear"
        children = []
        if log:
            children += [
                _section_header("IMC Official Results", theme),
                html.Div(
                    dcc.Graph(id="imc-chart",
                              figure=build_imc_figure(log, symbol, theme, smooth_n=smooth_n, line_shape=line_shape),
                              config=_GRAPH_CONFIG),
                    style=_card_style(theme),
                ),
            ]
        if log and backtest_data:
            children.append(_divider(theme))
        if backtest_data:
            children += [
                _section_header("Internal Backtest", theme),
                html.Div(
                    dcc.Graph(id="bt-chart",
                              figure=build_backtest_figure(
                                  backtest_data, symbol, market_df_raw, theme,
                                  show_quotes=show_quotes,
                                  smooth_n=smooth_n,
                                  line_shape=line_shape,
                                  _precomputed=bt_precomputed,
                                  _per_prod_pnl=bt_per_prod_pnl,
                              ),
                              config=_GRAPH_CONFIG),
                    style=_card_style(theme),
                ),
            ]
        return children

    host = "127.0.0.1"
    print(f"Starting tooling dashboard on http://{host}:8050")
    server = make_server(host, 8050, app.server, threaded=False)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping tooling dashboard...")
    finally:
        server.server_close()
        print("Tooling dashboard stopped.")


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
