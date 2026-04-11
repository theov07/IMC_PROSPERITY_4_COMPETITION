"""Interactive research dashboard for raw round data exploration.

This dashboard is meant for the very start of a round, before a trading
strategy exists. It loads the CSV files from ``data/`` and builds an
overview-first interface that helps answer questions such as:

- Is the product trending or ranging?
- How wide is the spread over the full session?
- Is liquidity stable or episodic?
- When do trades cluster, and how does VWAP/VPIN evolve?
- What does the order book look like at a specific timestamp?

Design principles of this file:

1. Precompute as much as possible once at startup.
   The dashboard should stay responsive even when playback is enabled.
2. Show the full timeline by default.
   The main value at round open is understanding the entire day, not only
   inspecting a narrow window around one timestamp.
3. Keep one moving cursor and one live order-book snapshot.
   The cursor gives temporal context while the depth chart shows the current
   microstructure state.
4. Keep the dashboard strategy-agnostic.
   This tool is for market research on raw data, not for backtest review.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple

import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from werkzeug.serving import make_server

# Add repository root to path to import local modules
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from research.visualizer.data_loader import DataLoader
from research.visualizer.visualizer import MarketVisualizer
from datamodel import OrderDepth, Symbol


GRAPH_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "modeBarButtonsToKeep": ["zoom2d", "pan2d", "autoScale2d", "resetScale2d", "toImage"],
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}

RESEARCH_DASHBOARD_PORT = 8051

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "page_bg": "#eef3f8",
        "panel_bg": "#ffffff",
        "panel_alt": "#f8fafc",
        "border": "#d7e0ea",
        "text": "#16202a",
        "text_muted": "#5e7183",
        "accent": "#0f62fe",
        "accent_soft": "#dbeafe",
        "plot_bg": "#f8fafc",
        "paper_bg": "#ffffff",
        "legend_bg": "rgba(255,255,255,0.92)",
        "legend_border": "#d7e0ea",
        "subplot_title": "#4b5f74",
        "shadow": "0 12px 28px rgba(15, 23, 42, 0.08)",
        "cursor": "rgba(71, 85, 105, 0.85)",
        "trade_marker": "rgba(15, 23, 42, 0.38)",
        "raw_line": "rgba(71, 85, 105, 0.35)",
    },
    "dark": {
        "page_bg": "#0f172a",
        "panel_bg": "#111c2f",
        "panel_alt": "#172338",
        "border": "#24324a",
        "text": "#e5edf5",
        "text_muted": "#9fb0c3",
        "accent": "#7cc7ff",
        "accent_soft": "#16324f",
        "plot_bg": "#172338",
        "paper_bg": "#111c2f",
        "legend_bg": "rgba(17,28,47,0.92)",
        "legend_border": "#24324a",
        "subplot_title": "#a9bdd2",
        "shadow": "0 16px 36px rgba(2, 8, 23, 0.35)",
        "cursor": "rgba(148, 163, 184, 0.85)",
        "trade_marker": "rgba(226, 232, 240, 0.32)",
        "raw_line": "rgba(148, 163, 184, 0.32)",
    },
}

SERIES_COLORS = {
    "mid": "#2563eb",
    "best_bid": "#16a34a",
    "best_ask": "#dc2626",
    "vwap": "#f59e0b",
    "imbalance_pos": "#22c55e",
    "imbalance_neg": "#f97316",
    "spread": "#64748b",
    "rolling_vol": "#ea580c",
    "trade_price": "#2563eb",
    "trade_volume": "#94a3b8",
    "trade_count": "#8b5cf6",
    "vpin": "#b91c1c",
    "depth_bid": "#16a34a",
    "depth_ask": "#dc2626",
    "cum_volume": "#0f766e",
}


def _theme_outer_style(theme: str) -> dict[str, str]:
    """Build CSS variables and outer-shell styles for the selected theme."""
    t = THEMES[theme]
    return {
        "--page-bg": t["page_bg"],
        "--panel-bg": t["panel_bg"],
        "--panel-alt": t["panel_alt"],
        "--panel-border": t["border"],
        "--text-main": t["text"],
        "--text-muted": t["text_muted"],
        "--accent": t["accent"],
        "--accent-soft": t["accent_soft"],
        "--shadow": t["shadow"],
        "backgroundColor": "var(--page-bg)",
        "color": "var(--text-main)",
        "minHeight": "100vh",
        "fontFamily": "Inter, system-ui, sans-serif",
    }


def _layout_base(theme: str) -> dict[str, Any]:
    """Return a Plotly layout baseline shared by all charts."""
    t = THEMES[theme]
    return dict(
        template="plotly_dark" if theme == "dark" else "plotly_white",
        hovermode="x unified",
        margin=dict(l=64, r=34, t=54, b=56),
        plot_bgcolor=t["plot_bg"],
        paper_bgcolor=t["paper_bg"],
        font=dict(family="Inter, system-ui, sans-serif", size=12, color=t["text"]),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.08,
            xanchor="center",
            x=0.5,
            bgcolor=t["legend_bg"],
            bordercolor=t["legend_border"],
            borderwidth=1,
            font=dict(size=11, color=t["text"]),
        ),
    )


def _subplot_title_style(theme: str) -> dict[str, Any]:
    """Style subplot headings in a theme-aware way."""
    return dict(font=dict(size=12, color=THEMES[theme]["subplot_title"]))


def _panel_style(padding: str = "16px 18px") -> dict[str, str]:
    """Reusable card-like container style driven by CSS variables."""
    return {
        "background": "var(--panel-bg)",
        "border": "1px solid var(--panel-border)",
        "borderRadius": "16px",
        "boxShadow": "var(--shadow)",
        "padding": padding,
    }


def _section_header(label: str, subtitle: str | None = None) -> html.Div:
    """Render a styled section header for the dashboard shell."""
    children: list[Any] = [
        html.Div(
            label,
            style={
                "fontSize": "17px",
                "fontWeight": "700",
                "color": "var(--text-main)",
                "letterSpacing": "0.01em",
            },
        )
    ]
    if subtitle:
        children.append(
            html.Div(
                subtitle,
                style={"fontSize": "12px", "color": "var(--text-muted)", "marginTop": "4px"},
            )
        )
    return html.Div(children, style={"margin": "24px 0 12px"})


def extract_day(file_name: str) -> str:
    """Extract the day suffix from a CSV file name.

    Example:
        ``prices_round_0_day_-2.csv`` -> ``-2``
    """
    parts = file_name.replace(".csv", "").split("day_")
    return parts[-1] if len(parts) > 1 else file_name


def build_vwap(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Build a cumulative VWAP series from raw trade rows."""
    if trades_df.empty:
        return pd.DataFrame(columns=["timestamp", "vwap"])

    out = trades_df.sort_values("timestamp").copy()
    out["dollar"] = out["price"] * out["quantity"]
    out["cum_qty"] = out["quantity"].cumsum()
    out["cum_dollar"] = out["dollar"].cumsum()
    out["vwap"] = out["cum_dollar"] / out["cum_qty"]
    return out


def build_vpin(trades_df: pd.DataFrame, bucket_volume: int = 500) -> pd.DataFrame:
    """Approximate VPIN from trade price changes and bucketed signed volume.

    This is intentionally lightweight and research-oriented rather than a
    perfect market microstructure implementation.
    """
    df = trades_df.sort_values("timestamp").copy()
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "vpin"])

    price_changes = df["price"].diff().fillna(0)
    signs = np.sign(price_changes)
    signs = pd.Series(signs).replace(0, np.nan).ffill().fillna(1)
    df["signed_volume"] = df["quantity"] * signs

    bucket_end_times: List[int] = []
    vpin_values: List[float] = []
    buy_volume = 0
    sell_volume = 0
    bucket_acc = 0

    for _, row in df.iterrows():
        vol = int(row["quantity"])
        signed = float(row["signed_volume"])

        if signed >= 0:
            buy_volume += vol
        else:
            sell_volume += vol

        bucket_acc += vol

        if bucket_acc >= bucket_volume:
            vpin = abs(buy_volume - sell_volume) / bucket_acc if bucket_acc else 0.0
            vpin_values.append(vpin)
            bucket_end_times.append(int(row["timestamp"]))
            buy_volume = 0
            sell_volume = 0
            bucket_acc = 0

    return pd.DataFrame({"timestamp": bucket_end_times, "vpin": vpin_values})


def build_trade_volume(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate trades by timestamp for volume and trade-count plots."""
    if trades_df.empty:
        return pd.DataFrame(columns=["timestamp", "volume", "trade_count", "cum_volume"])

    grouped = (
        trades_df.groupby("timestamp", as_index=False)
        .agg(volume=("quantity", "sum"), trade_count=("quantity", "count"))
        .sort_values("timestamp")
    )
    grouped["cum_volume"] = grouped["volume"].cumsum()
    return grouped


def infer_tick_size(timestamps: pd.Series) -> int:
    """Infer the base timestamp step from a sorted timestamp series."""
    if timestamps.empty:
        return 100
    diffs = timestamps.sort_values().diff().dropna()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return 100
    return int(diffs.median())


def build_candle_frame(
    orderbook_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    source: str = "mid",
    bucket_ticks: int = 10,
) -> pd.DataFrame:
    """Aggregate raw ticks into OHLC candles plus bucketed volume."""
    if source == "trade" and not trades_df.empty:
        base = trades_df[["timestamp", "price"]].rename(columns={"price": "value"}).sort_values("timestamp")
    else:
        base = orderbook_df[["timestamp", "mid"]].rename(columns={"mid": "value"}).sort_values("timestamp")

    if base.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "trade_count", "ema_fast", "ema_slow"])

    tick_size = infer_tick_size(base["timestamp"])
    bucket_width = max(int(bucket_ticks), 1) * max(tick_size, 1)
    start_ts = int(base["timestamp"].iloc[0])

    base = base.copy()
    base["bucket"] = ((base["timestamp"] - start_ts) // bucket_width).astype(int)
    candles = (
        base.groupby("bucket", as_index=False)
        .agg(
            timestamp=("timestamp", "first"),
            open=("value", "first"),
            high=("value", "max"),
            low=("value", "min"),
            close=("value", "last"),
        )
        .sort_values("timestamp")
    )

    if trades_df.empty:
        candles["volume"] = 0
        candles["trade_count"] = 0
    else:
        volume = trades_df[["timestamp", "quantity"]].sort_values("timestamp").copy()
        volume["bucket"] = ((volume["timestamp"] - start_ts) // bucket_width).astype(int)
        volume = volume.groupby("bucket", as_index=False).agg(volume=("quantity", "sum"), trade_count=("quantity", "count"))
        candles = candles.merge(volume, on="bucket", how="left")
        candles["volume"] = candles["volume"].fillna(0)
        candles["trade_count"] = candles["trade_count"].fillna(0)

    candles["ema_fast"] = candles["close"].ewm(span=8, adjust=False).mean()
    candles["ema_slow"] = candles["close"].ewm(span=21, adjust=False).mean()
    return candles


def enrich_orderbook_df(orderbook_df: pd.DataFrame) -> pd.DataFrame:
    """Add derived time-series features used by the dashboard.

    The raw order-book series already contains mid, best bid/ask, spread,
    imbalance, and displayed volume. Here we add:

    - ``mid_return``: first difference of the mid price
    - ``rolling_vol``: rolling standard deviation of mid changes
    """
    if orderbook_df.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "mid",
                "best_bid",
                "best_ask",
                "bid_volume",
                "ask_volume",
                "spread",
                "imbalance",
                "mid_return",
                "rolling_vol",
            ]
        )

    out = orderbook_df.sort_values("timestamp").copy()
    out["mid_return"] = out["mid"].diff().fillna(0.0)
    out["rolling_vol"] = out["mid_return"].rolling(50, min_periods=2).std().fillna(0.0)
    return out


def build_depth_curve(order_depth: OrderDepth) -> Tuple[List[int], List[int], List[int], List[int]]:
    """Convert one order-book snapshot into cumulative bid/ask depth curves."""
    bids = sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)
    asks = sorted(order_depth.sell_orders.items(), key=lambda x: x[0])

    bid_prices = [p for p, _ in bids]
    bid_cum = np.cumsum([v for _, v in bids]).tolist()
    ask_prices = [p for p, _ in asks]
    ask_cum = np.cumsum([abs(v) for _, v in asks]).tolist()
    return bid_prices, bid_cum, ask_prices, ask_cum


def build_slider_marks(timestamps: List[int], max_labels: int = 6) -> Dict[int, str]:
    """Create sparse slider labels so large sessions stay readable."""
    if not timestamps:
        return {}

    if len(timestamps) <= max_labels:
        return {idx: str(ts) for idx, ts in enumerate(timestamps)}

    positions = np.linspace(0, len(timestamps) - 1, num=max_labels, dtype=int)
    return {int(pos): str(timestamps[int(pos)]) for pos in positions}


def clamp_index(index: int, size: int) -> int:
    """Clamp a slider/frame index into the valid timestamp range."""
    if size <= 0:
        return 0
    return max(0, min(int(index), size - 1))


def _smooth(series: pd.Series, n: int) -> pd.Series:
    """Apply EWMA smoothing while keeping the original index intact."""
    if series.empty or n <= 1:
        return series
    return series.ewm(span=max(int(n), 1), adjust=False).mean()


def _fmt(value: Any, digits: int = 2, signed: bool = False) -> str:
    """Format metric values consistently for cards and callouts."""
    if value is None:
        return "-"
    if isinstance(value, (int, np.integer)):
        return f"{value:+d}" if signed else f"{value:d}"
    if isinstance(value, (float, np.floating)):
        return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
    return str(value)


def build_market_summary(
    orderbook_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    vpin_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Summarize one product/day into research-friendly diagnostics.

    The result is used for the summary cards at the top of the dashboard and
    provides a quick first-pass interpretation of the session:

    - price range and drift
    - average spread and imbalance
    - displayed liquidity
    - trade activity
    - rough regime classification
    """
    if orderbook_df.empty:
        return {
            "ticks": 0,
            "start_ts": None,
            "end_ts": None,
            "mid_first": None,
            "mid_last": None,
            "mid_range": 0.0,
            "mid_change": 0.0,
            "mid_std": 0.0,
            "avg_spread": 0.0,
            "avg_abs_imbalance": 0.0,
            "avg_bid_vol": 0.0,
            "avg_ask_vol": 0.0,
            "trade_count": int(len(trades_df)),
            "traded_volume": int(trades_df["quantity"].sum()) if not trades_df.empty else 0,
            "vpin_mean": float(vpin_df["vpin"].mean()) if not vpin_df.empty else 0.0,
            "regime_hint": "No order book data",
            "volume_hint": "No trade data" if trades_df.empty else "Sparse",
            "strategy_hint": "Wait for a usable book before forming a view.",
            "risk_hint": "No meaningful microstructure signal yet.",
            "pattern_hint": "Not enough information to classify the session.",
        }

    mid_first = float(orderbook_df["mid"].iloc[0])
    mid_last = float(orderbook_df["mid"].iloc[-1])
    mid_change = mid_last - mid_first
    mid_std = float(orderbook_df["mid"].std() or 0.0)
    avg_spread = float(orderbook_df["spread"].mean() or 0.0)
    avg_abs_imbalance = float(orderbook_df["imbalance"].abs().mean() or 0.0)

    trend_strength = abs(mid_change) / max(mid_std, 1.0)
    if trend_strength >= 1.5 and abs(mid_change) >= max(avg_spread, 1.0):
        regime_hint = "Trending"
    elif avg_spread <= 2.0 and avg_abs_imbalance <= 0.15:
        regime_hint = "Tight MM-friendly"
    elif avg_spread >= 4.0:
        regime_hint = "Wide spread / selective"
    else:
        regime_hint = "Range / mixed"

    if trades_df.empty:
        volume_hint = "No trade data"
    else:
        qty_std = float(trades_df["quantity"].std() or 0.0)
        qty_mean = float(trades_df["quantity"].mean() or 0.0)
        volume_hint = "Spiky flow" if qty_std > qty_mean * 1.25 else "Stable flow"

    vpin_mean = float(vpin_df["vpin"].mean() or 0.0) if not vpin_df.empty else 0.0

    if regime_hint == "Tight MM-friendly" and volume_hint != "No trade data":
        strategy_hint = "Start with passive two-sided quoting and inventory control."
    elif regime_hint == "Trending":
        strategy_hint = "Use trend-aware filters before leaning inventory or fading moves."
    elif regime_hint == "Wide spread / selective":
        strategy_hint = "Quote selectively, demand edge, and avoid blind passive fills."
    else:
        strategy_hint = "Begin neutral and test whether imbalance persistence offers edge."

    if vpin_mean >= 0.65:
        risk_hint = "Flow looks toxic; adverse selection risk is elevated for passive orders."
    elif avg_abs_imbalance >= 0.25:
        risk_hint = "Book pressure is persistent; inventory can drift quickly if ignored."
    else:
        risk_hint = "Flow looks relatively balanced; passive participation is safer than usual."

    if trend_strength >= 1.5:
        pattern_hint = "Directional exploration matters more than noise."
    elif float(orderbook_df["mid"].max() - orderbook_df["mid"].min()) <= max(avg_spread * 3, 3.0):
        pattern_hint = "Compression dominates; queue management and mean reversion deserve attention."
    else:
        pattern_hint = "Mixed session; keep both MM and directional hypotheses alive."

    return {
        "ticks": int(len(orderbook_df)),
        "start_ts": int(orderbook_df["timestamp"].iloc[0]),
        "end_ts": int(orderbook_df["timestamp"].iloc[-1]),
        "mid_first": round(mid_first, 2),
        "mid_last": round(mid_last, 2),
        "mid_range": round(float(orderbook_df["mid"].max() - orderbook_df["mid"].min()), 2),
        "mid_change": round(mid_change, 2),
        "mid_std": round(mid_std, 3),
        "avg_spread": round(avg_spread, 2),
        "avg_abs_imbalance": round(avg_abs_imbalance, 3),
        "avg_bid_vol": round(float(orderbook_df["bid_volume"].mean() or 0.0), 1),
        "avg_ask_vol": round(float(orderbook_df["ask_volume"].mean() or 0.0), 1),
        "trade_count": int(len(trades_df)),
        "traded_volume": int(trades_df["quantity"].sum()) if not trades_df.empty else 0,
        "vpin_mean": round(vpin_mean, 3),
        "regime_hint": regime_hint,
        "volume_hint": volume_hint,
        "strategy_hint": strategy_hint,
        "risk_hint": risk_hint,
        "pattern_hint": pattern_hint,
    }


def get_current_snapshot(orderbook_df: pd.DataFrame, ts_value: int) -> Dict[str, Any]:
    """Return the latest known order-book state at or before ``ts_value``."""
    if orderbook_df.empty:
        return {}

    exact = orderbook_df[orderbook_df["timestamp"] == ts_value]
    if not exact.empty:
        row = exact.iloc[-1]
    else:
        previous = orderbook_df[orderbook_df["timestamp"] <= ts_value]
        if previous.empty:
            row = orderbook_df.iloc[0]
        else:
            row = previous.iloc[-1]

    return {
        "best_bid": round(float(row["best_bid"]), 2),
        "best_ask": round(float(row["best_ask"]), 2),
        "mid": round(float(row["mid"]), 2),
        "spread": round(float(row["spread"]), 2),
        "imbalance": round(float(row["imbalance"]), 3),
        "bid_volume": round(float(row["bid_volume"]), 1),
        "ask_volume": round(float(row["ask_volume"]), 1),
        "rolling_vol": round(float(row.get("rolling_vol", 0.0)), 4),
    }


def make_card(label: str, value: str, subtitle: str | None = None) -> html.Div:
    """Render one summary card used in the top overview panel."""
    children: List[Any] = [
        html.Div(label, style={"fontSize": "12px", "color": "var(--text-muted)", "marginBottom": "6px"}),
        html.Div(value, style={"fontSize": "20px", "fontWeight": "700", "color": "var(--text-main)"}),
    ]
    if subtitle:
        children.append(html.Div(subtitle, style={"fontSize": "11px", "color": "var(--text-muted)", "marginTop": "6px"}))
    return html.Div(
        children,
        style={
            "background": "var(--panel-alt)",
            "border": "1px solid var(--panel-border)",
            "borderRadius": "14px",
            "padding": "12px 14px",
            "minWidth": "170px",
            "flex": "1 1 180px",
        },
    )


def make_note_panel(label: str, text: str) -> html.Div:
    """Render a compact narrative panel for the research hints section."""
    return html.Div(
        [
            html.Div(label, style={"fontSize": "12px", "fontWeight": "700", "color": "var(--accent)", "marginBottom": "8px"}),
            html.Div(text, style={"fontSize": "13px", "lineHeight": "1.55", "color": "var(--text-main)"}),
        ],
        style={
            "background": "var(--panel-alt)",
            "border": "1px solid var(--panel-border)",
            "borderRadius": "14px",
            "padding": "14px 16px",
            "flex": "1 1 260px",
        },
    )


def build_summary_panel(summary: Dict[str, Any], snapshot: Dict[str, Any], ts_value: int) -> html.Div:
    """Assemble the top-level overview cards for the selected product/day."""
    return html.Div(
        [
            make_card("Regime", str(summary["regime_hint"]), f"Flow: {summary['volume_hint']}"),
            make_card("Timeline", f"{summary['start_ts']} -> {summary['end_ts']}", f"Cursor: {ts_value}"),
            make_card("Mid", f"{summary['mid_first']} -> {summary['mid_last']}", f"Delta: {_fmt(summary['mid_change'], signed=True)}"),
            make_card("Mid Range", str(summary["mid_range"]), f"Std: {_fmt(summary['mid_std'], digits=3)}"),
            make_card("Avg Spread", str(summary["avg_spread"]), f"Abs imbalance: {_fmt(summary['avg_abs_imbalance'], digits=3)}"),
            make_card("Liquidity", f"Bid {summary['avg_bid_vol']} / Ask {summary['avg_ask_vol']}", f"VPIN mean: {_fmt(summary['vpin_mean'], digits=3)}"),
            make_card("Trades", str(summary["trade_count"]), f"Volume: {summary['traded_volume']}"),
            make_card(
                "Snapshot",
                f"Bid {snapshot.get('best_bid', '-')} / Ask {snapshot.get('best_ask', '-')}",
                f"Mid: {snapshot.get('mid', '-')}  Spread: {snapshot.get('spread', '-')}",
            ),
        ],
        style={
            "display": "flex",
            "flexWrap": "wrap",
            "gap": "12px",
        },
    )


def build_insight_panel(summary: Dict[str, Any], snapshot: Dict[str, Any]) -> html.Div:
    """Convert the session diagnostics into trading-oriented research notes."""
    cursor_spread = float(snapshot.get("spread", 0.0) or 0.0)
    avg_spread = float(summary.get("avg_spread", 0.0) or 0.0)
    cursor_imbalance = abs(float(snapshot.get("imbalance", 0.0) or 0.0))
    avg_abs_imbalance = float(summary.get("avg_abs_imbalance", 0.0) or 0.0)

    if cursor_spread > max(avg_spread * 1.5, avg_spread + 1.0):
        cursor_note = "The current spread is wider than the session norm. This is a good place to inspect whether passive edge is temporarily improving."
    elif cursor_imbalance > max(0.28, avg_abs_imbalance * 1.5):
        cursor_note = "The current book is strongly imbalanced. Watch whether price follows this pressure or mean reverts after the queue thins."
    else:
        cursor_note = "The current snapshot is close to session averages. This is a useful baseline state to compare against spikes later in the day."

    return html.Div(
        [
            make_note_panel("Suggested Starting Angle", summary["strategy_hint"]),
            make_note_panel("Main Risk To Respect", summary["risk_hint"]),
            make_note_panel("What This Cursor Says", cursor_note),
            make_note_panel("Pattern Read", summary["pattern_hint"]),
        ],
        style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "marginTop": "14px"},
    )


def make_line_trace(
    x: pd.Series,
    y: pd.Series,
    name: str,
    color: str,
    width: float = 1.5,
    line_shape: str = "linear",
    dash: str | None = None,
    opacity: float = 1.0,
) -> go.Scattergl:
    """Create a consistent high-performance line trace."""
    line: dict[str, Any] = {"color": color, "width": width, "shape": line_shape}
    if dash:
        line["dash"] = dash
    return go.Scattergl(
        x=x,
        y=y,
        mode="lines",
        name=name,
        line=line,
        opacity=opacity,
    )


def add_vertical_cursor(fig: go.Figure, ts_value: int, row_count: int, theme: str) -> None:
    """Add the same timestamp cursor to each subplot row."""
    for row in range(1, row_count + 1):
        fig.add_vline(
            x=ts_value,
            line_width=1,
            line_dash="dash",
            line_color=THEMES[theme]["cursor"],
            row=row,
            col=1,
        )


def empty_figure(theme: str, title: str = "No data") -> go.Figure:
    """Return a theme-aware placeholder figure."""
    fig = go.Figure()
    fig.update_layout(title=title, height=320, **_layout_base(theme))
    return fig


def _list_listening_pids_for_port(port: int) -> list[int]:
    """Return PIDs currently listening on ``port`` on Windows.

    We parse ``netstat -ano`` output rather than relying on optional third-party
    packages so the cleanup logic works on a fresh repo checkout.
    """
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        check=False,
    )
    pids: set[int] = set()
    target = f":{port}"
    stdout = result.stdout.decode(errors="ignore") if isinstance(result.stdout, (bytes, bytearray)) else (result.stdout or "")
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if target not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3].upper()
        pid_text = parts[4]
        if not local_addr.endswith(target):
            continue
        if state != "LISTENING":
            continue
        if pid_text.isdigit():
            pids.add(int(pid_text))
    return sorted(pids)


def _kill_process_tree(pid: int) -> None:
    """Force-stop a process tree on Windows."""
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F", "/T"],
        capture_output=True,
        check=False,
    )


def _cleanup_dashboard_port(port: int, label: str) -> None:
    """Kill old listeners on the dashboard port before starting a new server."""
    current_pid = os.getpid()
    stale_pids = [pid for pid in _list_listening_pids_for_port(port) if pid != current_pid]
    if not stale_pids:
        return

    print(f"Cleaning up stale {label} listeners on port {port}: {', '.join(map(str, stale_pids))}")
    for pid in stale_pids:
        _kill_process_tree(pid)

    deadline = time.time() + 5.0
    while time.time() < deadline:
        remaining = [pid for pid in _list_listening_pids_for_port(port) if pid != current_pid]
        if not remaining:
            return
        time.sleep(0.1)

    remaining = [pid for pid in _list_listening_pids_for_port(port) if pid != current_pid]
    if remaining:
        print(f"Warning: port {port} still has listeners after cleanup: {', '.join(map(str, remaining))}")


def load_data() -> Dict[str, Dict[str, object]]:
    """Load and precompute all day/product research data once at startup.

    This function is the heart of the dashboard architecture. It scans the
    ``data/`` directory, pairs price/trade files by day, and then precomputes
    the per-product tables required by the UI:

    - order-book time series
    - trades
    - VWAP
    - VPIN
    - aggregated trade volume
    - summary statistics

    The goal is to keep callbacks focused on presentation rather than data
    preparation.
    """
    data_dir = os.path.join(ROOT_DIR, "data")
    loader = DataLoader(data_dir)
    visualizer = MarketVisualizer()

    price_files = sorted(f for f in os.listdir(data_dir) if f.startswith("prices") and f.endswith(".csv"))
    trade_files = sorted(f for f in os.listdir(data_dir) if f.startswith("trades") and f.endswith(".csv"))

    price_by_day = {extract_day(file_name): file_name for file_name in price_files}
    trade_by_day = {extract_day(file_name): file_name for file_name in trade_files}
    days = sorted(set(price_by_day.keys()) & set(trade_by_day.keys()))

    data: Dict[str, Dict[str, object]] = {}
    for day in days:
        price_file = price_by_day[day]
        trade_file = trade_by_day[day]

        df_prices = loader.load_prices(price_file)
        history = loader.get_order_depths(df_prices)
        timestamps = sorted(history.keys())
        products = sorted(df_prices["product"].unique())
        trades = loader.load_trade_objects(trade_file)

        product_data: Dict[str, Dict[str, object]] = {}
        for product in products:
            orderbook_df = enrich_orderbook_df(visualizer._orderbook_series(history, product))
            trades_df = visualizer._trade_series(trades, product).sort_values("timestamp")
            vwap_df = build_vwap(trades_df)
            vpin_df = build_vpin(trades_df)
            trade_volume_df = build_trade_volume(trades_df)
            summary = build_market_summary(orderbook_df, trades_df, vpin_df)

            product_data[product] = {
                "orderbook_df": orderbook_df,
                "trades_df": trades_df,
                "vwap_df": vwap_df,
                "vpin_df": vpin_df,
                "trade_volume_df": trade_volume_df,
                "summary": summary,
            }

        data[day] = {
            "price_file": price_file,
            "trade_file": trade_file,
            "history": history,
            "timestamps": timestamps,
            "products": products,
            "product_data": product_data,
        }

    return data


DATA_STORE = load_data()

app = dash.Dash(__name__, title="Prosperity Round Data Explorer")
app.layout = html.Div(
    id="outer-wrapper",
    className="research-shell",
    style=_theme_outer_style("light"),
    children=[
        dcc.Store(id="theme-store", data="light"),
        html.Div(id="theme-css", style={"display": "none"}),
        html.Div(
            id="inner-wrapper",
            style={"maxWidth": "1480px", "margin": "0 auto", "padding": "0 22px 48px"},
            children=[
                html.Div(
                    id="header-div",
                    style={
                        "padding": "28px 0 18px",
                        "marginBottom": "20px",
                        "borderBottom": "2px solid var(--panel-border)",
                        "display": "flex",
                        "gap": "16px",
                        "justifyContent": "space-between",
                        "alignItems": "flex-start",
                    },
                    children=[
                        html.Div(
                            [
                                html.H2(
                                    "Prosperity Round Data Explorer",
                                    id="title-h2",
                                    style={"margin": "0", "fontSize": "30px", "fontWeight": "800", "color": "var(--text-main)"},
                                ),
                                html.P(
                                    "Research dashboard for raw market data: full-session structure, fast playback, smoother price reading, and microstructure hints for day-zero strategy design.",
                                    id="subtitle-p",
                                    style={
                                        "margin": "10px 0 0",
                                        "maxWidth": "920px",
                                        "fontSize": "14px",
                                        "lineHeight": "1.6",
                                        "color": "var(--text-muted)",
                                    },
                                ),
                            ]
                        ),
                        html.Button(
                            "Switch To Dark",
                            id="theme-btn",
                            style={
                                "background": "var(--panel-bg)",
                                "color": "var(--text-main)",
                                "border": "1px solid var(--panel-border)",
                                "borderRadius": "999px",
                                "padding": "10px 16px",
                                "fontSize": "13px",
                                "fontWeight": "700",
                                "cursor": "pointer",
                            },
                        ),
                    ],
                ),
                html.Div(
                    id="controls-card",
                    style=_panel_style("18px 18px 14px"),
                    children=[
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Label("Day", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)", "marginBottom": "8px"}),
                                        dcc.Dropdown(
                                            id="day-dropdown",
                                            options=[{"label": f"Day {day}", "value": day} for day in DATA_STORE.keys()],
                                            value=next(iter(DATA_STORE.keys())) if DATA_STORE else None,
                                            clearable=False,
                                        ),
                                    ],
                                    style={"flex": "0 0 220px"},
                                ),
                                html.Div(
                                    [
                                        html.Label("Product", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)", "marginBottom": "8px"}),
                                        dcc.Dropdown(id="product-dropdown", clearable=False),
                                    ],
                                    style={"flex": "0 0 220px"},
                                ),
                                html.Div(
                                    [
                                        html.Label("Playback", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)", "marginBottom": "8px"}),
                                        dcc.Checklist(
                                            id="play-toggle",
                                            options=[{"label": "Play timeline", "value": "play"}],
                                            value=[],
                                            inputStyle={"marginRight": "6px"},
                                        ),
                                    ],
                                    style={"flex": "0 0 150px"},
                                ),
                                html.Div(
                                    [
                                        html.Label("Speed", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)", "marginBottom": "8px"}),
                                        dcc.Dropdown(
                                            id="speed-dropdown",
                                            options=[
                                                {"label": "Ultra (25 ms)", "value": 25},
                                                {"label": "Turbo (50 ms)", "value": 50},
                                                {"label": "Fast (100 ms)", "value": 100},
                                                {"label": "Medium (200 ms)", "value": 200},
                                                {"label": "Slow (500 ms)", "value": 500},
                                            ],
                                            value=100,
                                            clearable=False,
                                        ),
                                    ],
                                    style={"flex": "0 0 180px"},
                                ),
                                html.Div(
                                    [
                                        html.Label("Playback Step", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)", "marginBottom": "8px"}),
                                        dcc.Dropdown(
                                            id="step-dropdown",
                                            options=[
                                                {"label": "x1", "value": 1},
                                                {"label": "x2", "value": 2},
                                                {"label": "x5", "value": 5},
                                                {"label": "x10", "value": 10},
                                                {"label": "x25", "value": 25},
                                            ],
                                            value=5,
                                            clearable=False,
                                        ),
                                    ],
                                    style={"flex": "0 0 140px"},
                                ),
                                html.Div(
                                    id="current-ts-label",
                                    style={
                                        "marginLeft": "auto",
                                        "paddingTop": "26px",
                                        "fontSize": "13px",
                                        "fontWeight": "700",
                                        "color": "var(--text-main)",
                                    },
                                ),
                            ],
                            style={"display": "flex", "flexWrap": "wrap", "gap": "14px", "alignItems": "flex-end"},
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        dcc.Checklist(
                                            id="smooth-toggle",
                                            options=[{"label": "Smooth structural lines", "value": "on"}],
                                            value=["on"],
                                            inputStyle={"marginRight": "6px"},
                                        )
                                    ],
                                    style={"flex": "0 0 230px"},
                                ),
                                html.Div(
                                    [
                                        dcc.Checklist(
                                            id="line-shape-toggle",
                                            options=[{"label": "Step lines (tick style)", "value": "hv"}],
                                            value=[],
                                            inputStyle={"marginRight": "6px"},
                                        )
                                    ],
                                    style={"flex": "0 0 220px"},
                                ),
                                html.Div(
                                    [
                                        dcc.Checklist(
                                            id="show-trades-toggle",
                                            options=[{"label": "Show trade markers on price chart", "value": "show"}],
                                            value=["show"],
                                            inputStyle={"marginRight": "6px"},
                                        )
                                    ],
                                    style={"flex": "0 0 280px"},
                                ),
                                html.Div(
                                    [
                                        html.Div("Candle Source", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)", "marginBottom": "6px"}),
                                        dcc.Dropdown(
                                            id="candle-source-dropdown",
                                            options=[
                                                {"label": "Mid Price", "value": "mid"},
                                                {"label": "Trade Price", "value": "trade"},
                                            ],
                                            value="mid",
                                            clearable=False,
                                        ),
                                    ],
                                    style={"flex": "0 0 180px"},
                                ),
                                html.Div(
                                    [
                                        html.Div("Candle Bucket", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)", "marginBottom": "6px"}),
                                        dcc.Dropdown(
                                            id="candle-bucket-dropdown",
                                            options=[
                                                {"label": "5 ticks", "value": 5},
                                                {"label": "10 ticks", "value": 10},
                                                {"label": "25 ticks", "value": 25},
                                                {"label": "50 ticks", "value": 50},
                                                {"label": "100 ticks", "value": 100},
                                            ],
                                            value=25,
                                            clearable=False,
                                        ),
                                    ],
                                    style={"flex": "0 0 160px"},
                                ),
                                html.Div(
                                    [
                                        html.Div("Smoothing Window", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)", "marginBottom": "6px"}),
                                        dcc.Slider(
                                            id="smooth-n",
                                            min=1,
                                            max=80,
                                            step=1,
                                            value=18,
                                            marks={1: "1", 20: "20", 40: "40", 60: "60", 80: "80"},
                                            tooltip={"placement": "top", "always_visible": False},
                                        ),
                                    ],
                                    style={"flex": "1 1 360px", "paddingRight": "8px"},
                                ),
                            ],
                            style={"display": "flex", "flexWrap": "wrap", "gap": "14px", "alignItems": "center", "marginTop": "16px"},
                        ),
                        html.Div(style={"marginTop": "16px"}, children=[html.Label("Timestamp", id="timestamp-label", style={"fontSize": "12px", "fontWeight": "700", "color": "var(--text-muted)"})]),
                        dcc.Slider(id="timestamp-slider", min=0, max=1, step=1, value=0),
                    ],
                ),
                dcc.Interval(id="play-interval", interval=100, n_intervals=0, disabled=True),
                _section_header(
                    "Session Overview",
                    "Read the market regime first, then scrub the cursor to inspect where spreads, flow, and depth change character.",
                ),
                html.Div(id="summary-panel"),
                html.Div(id="insight-panel"),
                _section_header("Cross-Asset Evolution", "Normalized paths let you compare how every product moved through the session, even if price scales differ."),
                html.Div(dcc.Graph(id="cross-asset-graph", config=GRAPH_CONFIG), style=_panel_style("6px 6px 2px")),
                _section_header("Candles And Tape", "Binance-style candles help you read structure faster, while volume shows when the move had real participation behind it."),
                html.Div(dcc.Graph(id="candle-graph", config=GRAPH_CONFIG), style=_panel_style("6px 6px 2px")),
                _section_header("Price Discovery", "Use smoothing for structure, then toggle it off to inspect the raw microstructure noise."),
                html.Div(dcc.Graph(id="price-graph", config=GRAPH_CONFIG), style=_panel_style("6px 6px 2px")),
                _section_header("Liquidity And Risk", "Displayed depth, spread, and rolling volatility tell you how costly it is to provide or take liquidity."),
                html.Div(dcc.Graph(id="liquidity-graph", config=GRAPH_CONFIG), style=_panel_style("6px 6px 2px")),
                _section_header("Trade Flow", "Trade clustering, cumulative volume, and VPIN help separate benign activity from potentially toxic flow."),
                html.Div(dcc.Graph(id="trade-graph", config=GRAPH_CONFIG), style=_panel_style("6px 6px 2px")),
                _section_header("Order Book Snapshot", "The depth chart stays tied to the shared cursor so you can connect timeline events to exact book states."),
                html.Div(dcc.Graph(id="orderbook-graph", config=GRAPH_CONFIG), style=_panel_style("6px 6px 2px")),
            ],
        ),
    ],
)


@app.callback(Output("theme-store", "data"), Input("theme-btn", "n_clicks"), State("theme-store", "data"))
def toggle_theme(_n_clicks: int | None, current_theme: str | None) -> str:
    """Toggle the dashboard theme between light and dark."""
    if not _n_clicks:
        return current_theme or "light"
    return "dark" if (current_theme or "light") == "light" else "light"


app.clientside_callback(
    f"""
    function(theme) {{
        var themes = {json.dumps(THEMES)};
        var t = themes[theme] || themes["light"];
        var css = [
            '.research-shell .Select-control {{ background-color: ' + t.panel_bg + ' !important; border-color: ' + t.border + ' !important; }}',
            '.research-shell .Select-menu-outer {{ background-color: ' + t.panel_bg + ' !important; border-color: ' + t.border + ' !important; }}',
            '.research-shell .Select-menu {{ background-color: ' + t.panel_bg + ' !important; }}',
            '.research-shell .Select-option {{ background-color: ' + t.panel_bg + ' !important; color: ' + t.text + ' !important; }}',
            '.research-shell .Select-option.is-focused {{ background-color: ' + t.panel_alt + ' !important; }}',
            '.research-shell .Select-value-label {{ color: ' + t.text + ' !important; }}',
            '.research-shell .Select-placeholder {{ color: ' + t.text_muted + ' !important; }}',
            '.research-shell .VirtualizedSelectOption {{ background-color: ' + t.panel_bg + ' !important; color: ' + t.text + ' !important; }}',
            '.research-shell label {{ color: ' + t.text + ' !important; }}',
            '.research-shell .dash-checklist label {{ color: ' + t.text + ' !important; }}',
            '.research-shell .rc-slider-mark-text {{ color: ' + t.text_muted + ' !important; }}',
            '.research-shell .rc-slider-rail {{ background-color: ' + t.border + ' !important; }}',
            '.research-shell .rc-slider-track {{ background-color: ' + t.accent + ' !important; }}',
            '.research-shell .rc-slider-handle {{ border-color: ' + t.accent + ' !important; background-color: ' + t.panel_bg + ' !important; }}'
        ].join('\\n');
        var el = document.getElementById('research-theme-style');
        if (!el) {{
            el = document.createElement('style');
            el.id = 'research-theme-style';
            document.head.appendChild(el);
        }}
        el.textContent = css;
        return '';
    }}
    """,
    Output("theme-css", "children"),
    Input("theme-store", "data"),
)


@app.callback(
    [Output("outer-wrapper", "style"), Output("theme-btn", "children"), Output("theme-btn", "style")],
    Input("theme-store", "data"),
)
def update_theme_chrome(theme: str):
    """Apply theme variables to the outer shell and update the toggle button."""
    button_label = "Switch To Dark" if theme == "light" else "Switch To Light"
    button_style = {
        "background": "var(--panel-bg)",
        "color": "var(--text-main)",
        "border": "1px solid var(--panel-border)",
        "borderRadius": "999px",
        "padding": "10px 16px",
        "fontSize": "13px",
        "fontWeight": "700",
        "cursor": "pointer",
    }
    return _theme_outer_style(theme), button_label, button_style


@app.callback(
    [
        Output("product-dropdown", "options"),
        Output("product-dropdown", "value"),
        Output("timestamp-slider", "min"),
        Output("timestamp-slider", "max"),
        Output("timestamp-slider", "value"),
        Output("timestamp-slider", "marks"),
    ],
    [Input("day-dropdown", "value")],
)
def update_products(day: str):
    """Update product selector and slider bounds when the selected day changes."""
    if not day or day not in DATA_STORE:
        return [], None, 0, 1, 0, {}

    products = DATA_STORE[day]["products"]
    timestamps = DATA_STORE[day]["timestamps"]
    if not timestamps:
        return [], None, 0, 1, 0, {}

    return (
        [{"label": product, "value": product} for product in products],
        products[0],
        0,
        len(timestamps) - 1,
        0,
        build_slider_marks(timestamps),
    )


@app.callback(
    [Output("play-interval", "disabled"), Output("play-interval", "interval")],
    [Input("play-toggle", "value"), Input("speed-dropdown", "value")],
)
def update_playback(play_toggle: List[str], speed: int):
    """Toggle playback and control the frame interval speed."""
    is_playing = "play" in (play_toggle or [])
    return (not is_playing, int(speed or 100))


@app.callback(
    Output("timestamp-slider", "value", allow_duplicate=True),
    [Input("play-interval", "n_intervals")],
    [State("day-dropdown", "value"), State("timestamp-slider", "value"), State("step-dropdown", "value")],
    prevent_initial_call=True,
)
def advance_timestamp(_n: int, day: str, current_idx: int, step: int):
    """Advance the slider during playback.

    ``step`` lets the user skip multiple timestamps per frame. Playback wraps
    around to the start instead of freezing at the end.
    """
    if not day or day not in DATA_STORE:
        return current_idx

    timestamps = DATA_STORE[day]["timestamps"]
    if not timestamps:
        return current_idx

    size = len(timestamps)
    return (int(current_idx or 0) + int(step or 1)) % size


@app.callback(
    [
        Output("summary-panel", "children"),
        Output("insight-panel", "children"),
        Output("current-ts-label", "children"),
        Output("cross-asset-graph", "figure"),
        Output("candle-graph", "figure"),
        Output("price-graph", "figure"),
        Output("liquidity-graph", "figure"),
        Output("trade-graph", "figure"),
        Output("orderbook-graph", "figure"),
    ],
    [
        Input("day-dropdown", "value"),
        Input("product-dropdown", "value"),
        Input("timestamp-slider", "value"),
        Input("theme-store", "data"),
        Input("smooth-toggle", "value"),
        Input("smooth-n", "value"),
        Input("line-shape-toggle", "value"),
        Input("show-trades-toggle", "value"),
        Input("candle-source-dropdown", "value"),
        Input("candle-bucket-dropdown", "value"),
    ],
)
def update_graphs(
    day: str,
    product: Symbol,
    timestamp_index: int,
    theme: str,
    smooth_toggle: List[str],
    smooth_n: int,
    line_shape_toggle: List[str],
    show_trades_toggle: List[str],
    candle_source: str,
    candle_bucket: int,
):
    """Render the complete dashboard for the selected day/product/timestamp.

    Output sections:

    - summary cards
    - research hints
    - full-session price overview
    - liquidity and spread/risk panel
    - trade-flow panel with VWAP and VPIN
    - live order-book depth snapshot at the cursor timestamp

    The price, liquidity, and trade charts are full-timeline views. Only the
    cursor position and the order-book snapshot change as playback advances.
    """
    empty = empty_figure(theme)
    if not day or day not in DATA_STORE or not product:
        return html.Div(), html.Div(), "Timestamp: -", empty, empty, empty, empty, empty, empty

    day_data = DATA_STORE[day]
    timestamps = day_data["timestamps"]
    if not timestamps or product not in day_data["product_data"]:
        return html.Div(), html.Div(), "Timestamp: -", empty, empty, empty, empty, empty, empty

    index = clamp_index(timestamp_index, len(timestamps))
    ts_value = timestamps[index]
    progress = (index + 1) / len(timestamps) * 100.0
    product_data = day_data["product_data"][product]
    orderbook_df = product_data["orderbook_df"]
    trades_df = product_data["trades_df"]
    vwap_df = product_data["vwap_df"]
    vpin_df = product_data["vpin_df"]
    trade_volume_df = product_data["trade_volume_df"]
    summary = product_data["summary"]
    snapshot = get_current_snapshot(orderbook_df, ts_value)

    current_label = f"Timestamp {ts_value} / {timestamps[-1]}  |  Frame {index + 1}/{len(timestamps)}  |  {progress:.1f}% through session"
    summary_panel = build_summary_panel(summary, snapshot, ts_value)
    insight_panel = build_insight_panel(summary, snapshot)

    smoothing_on = "on" in (smooth_toggle or [])
    smooth_window = int(smooth_n or 1) if smoothing_on else 1
    line_shape = "hv" if "hv" in (line_shape_toggle or []) else "linear"
    show_price_trades = "show" in (show_trades_toggle or [])

    mid_series = _smooth(orderbook_df["mid"], smooth_window) if not orderbook_df.empty else pd.Series(dtype=float)
    bid_series = _smooth(orderbook_df["best_bid"], smooth_window) if not orderbook_df.empty else pd.Series(dtype=float)
    ask_series = _smooth(orderbook_df["best_ask"], smooth_window) if not orderbook_df.empty else pd.Series(dtype=float)
    imbalance_series = _smooth(orderbook_df["imbalance"], smooth_window) if not orderbook_df.empty else pd.Series(dtype=float)
    bid_volume_series = _smooth(orderbook_df["bid_volume"], smooth_window) if not orderbook_df.empty else pd.Series(dtype=float)
    ask_volume_series = _smooth(orderbook_df["ask_volume"], smooth_window) if not orderbook_df.empty else pd.Series(dtype=float)
    spread_series = _smooth(orderbook_df["spread"], smooth_window) if not orderbook_df.empty else pd.Series(dtype=float)
    rolling_vol_series = _smooth(orderbook_df["rolling_vol"], smooth_window) if not orderbook_df.empty else pd.Series(dtype=float)
    vwap_series = _smooth(vwap_df["vwap"], smooth_window) if not vwap_df.empty else pd.Series(dtype=float)
    vpin_series = _smooth(vpin_df["vpin"], smooth_window) if not vpin_df.empty else pd.Series(dtype=float)
    cum_volume_series = _smooth(trade_volume_df["cum_volume"], smooth_window) if not trade_volume_df.empty else pd.Series(dtype=float)

    cross_asset_fig = go.Figure()
    comparison_colors = ["#2563eb", "#16a34a", "#dc2626", "#8b5cf6", "#0f766e", "#f59e0b", "#d946ef", "#0891b2"]
    for idx_sym, sym in enumerate(day_data["products"]):
        sym_orderbook = day_data["product_data"][sym]["orderbook_df"]
        if sym_orderbook.empty:
            continue
        sym_mid = _smooth(sym_orderbook["mid"], smooth_window) if smoothing_on else sym_orderbook["mid"]
        start_price = float(sym_mid.iloc[0]) if not sym_mid.empty else 0.0
        if start_price == 0:
            continue
        normalized = (sym_mid / start_price) * 100.0
        cross_asset_fig.add_trace(
            go.Scattergl(
                x=sym_orderbook["timestamp"],
                y=normalized,
                mode="lines",
                name=sym,
                opacity=1.0 if sym == product else 0.62,
                line=dict(
                    color=comparison_colors[idx_sym % len(comparison_colors)],
                    width=3.0 if sym == product else 1.6,
                    shape=line_shape,
                ),
            )
        )
    cross_asset_fig.add_vline(x=ts_value, line_width=1, line_dash="dash", line_color=THEMES[theme]["cursor"])
    cross_asset_fig.update_layout(
        height=420,
        title=f"Cross-Asset Evolution - Day {day}",
        uirevision=f"cross-{day}-{theme}-{line_shape}-{smooth_window}-{product}",
        yaxis_title="Normalized Price (100 = session open)",
        **_layout_base(theme),
    )

    effective_candle_source = candle_source if candle_source == "trade" and not trades_df.empty else "mid"
    candle_df = build_candle_frame(orderbook_df, trades_df, source=effective_candle_source, bucket_ticks=int(candle_bucket or 25))
    candle_fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.74, 0.26],
        vertical_spacing=0.05,
        subplot_titles=("Candlestick Structure", "Bucketed Volume"),
    )
    if not candle_df.empty:
        candle_fig.add_trace(
            go.Candlestick(
                x=candle_df["timestamp"],
                open=candle_df["open"],
                high=candle_df["high"],
                low=candle_df["low"],
                close=candle_df["close"],
                name="OHLC",
                increasing_line_color=SERIES_COLORS["best_bid"],
                decreasing_line_color=SERIES_COLORS["best_ask"],
                increasing_fillcolor=SERIES_COLORS["best_bid"],
                decreasing_fillcolor=SERIES_COLORS["best_ask"],
            ),
            row=1,
            col=1,
        )
        candle_fig.add_trace(
            go.Scattergl(
                x=candle_df["timestamp"],
                y=candle_df["ema_fast"],
                mode="lines",
                name="EMA 8",
                line=dict(color=SERIES_COLORS["vwap"], width=1.5, shape=line_shape),
            ),
            row=1,
            col=1,
        )
        candle_fig.add_trace(
            go.Scattergl(
                x=candle_df["timestamp"],
                y=candle_df["ema_slow"],
                mode="lines",
                name="EMA 21",
                line=dict(color=SERIES_COLORS["trade_count"], width=1.5, shape=line_shape),
            ),
            row=1,
            col=1,
        )
        volume_colors = [
            SERIES_COLORS["best_bid"] if close_px >= open_px else SERIES_COLORS["best_ask"]
            for open_px, close_px in zip(candle_df["open"], candle_df["close"])
        ]
        candle_fig.add_trace(
            go.Bar(
                x=candle_df["timestamp"],
                y=candle_df["volume"],
                name="Volume",
                marker_color=volume_colors,
                opacity=0.72,
            ),
            row=2,
            col=1,
        )
        active_candle = candle_df[candle_df["timestamp"] <= ts_value]
        active_ts = int(active_candle["timestamp"].iloc[-1]) if not active_candle.empty else int(candle_df["timestamp"].iloc[0])
        add_vertical_cursor(candle_fig, active_ts, 2, theme)
    candle_fig.update_layout(
        height=760,
        title=f"Candles - {product}  |  source={effective_candle_source}  |  bucket={int(candle_bucket or 25)} ticks",
        uirevision=f"candles-{day}-{product}-{theme}-{effective_candle_source}-{candle_bucket}-{line_shape}",
        xaxis_rangeslider_visible=False,
        **_layout_base(theme),
    )
    candle_fig.update_annotations(**_subplot_title_style(theme))
    candle_fig.update_yaxes(title_text="Price", row=1, col=1)
    candle_fig.update_yaxes(title_text="Volume", row=2, col=1)

    price_fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.74, 0.26],
        vertical_spacing=0.06,
        subplot_titles=("Full Price Timeline", "Order Book Imbalance"),
    )
    if not orderbook_df.empty:
        if smoothing_on and smooth_window > 1:
            price_fig.add_trace(
                make_line_trace(
                    orderbook_df["timestamp"],
                    orderbook_df["mid"],
                    "Mid (raw)",
                    THEMES[theme]["raw_line"],
                    1.0,
                    line_shape,
                    opacity=0.9,
                ),
                row=1,
                col=1,
            )
        price_fig.add_trace(make_line_trace(orderbook_df["timestamp"], mid_series, "Mid (EWMA)" if smoothing_on and smooth_window > 1 else "Mid", SERIES_COLORS["mid"], 2.4, line_shape), row=1, col=1)
        price_fig.add_trace(make_line_trace(orderbook_df["timestamp"], bid_series, "Best Bid", SERIES_COLORS["best_bid"], 1.2, line_shape), row=1, col=1)
        price_fig.add_trace(make_line_trace(orderbook_df["timestamp"], ask_series, "Best Ask", SERIES_COLORS["best_ask"], 1.2, line_shape), row=1, col=1)
        if not vwap_df.empty:
            price_fig.add_trace(make_line_trace(vwap_df["timestamp"], vwap_series, "VWAP", SERIES_COLORS["vwap"], 1.5, line_shape), row=1, col=1)
        if show_price_trades and not trades_df.empty:
            sizes = trades_df["quantity"].clip(lower=1, upper=25) * 1.6
            price_fig.add_trace(
                go.Scattergl(
                    x=trades_df["timestamp"],
                    y=trades_df["price"],
                    mode="markers",
                    name="Trades",
                    marker=dict(size=sizes, color=THEMES[theme]["trade_marker"], opacity=0.95),
                ),
                row=1,
                col=1,
            )
        imbalance_colors = [SERIES_COLORS["imbalance_pos"] if v >= 0 else SERIES_COLORS["imbalance_neg"] for v in imbalance_series]
        price_fig.add_trace(
            go.Bar(
                x=orderbook_df["timestamp"],
                y=imbalance_series,
                name="Imbalance",
                marker_color=imbalance_colors,
                opacity=0.68,
                showlegend=False,
            ),
            row=2,
            col=1,
        )
    add_vertical_cursor(price_fig, ts_value, 2, theme)
    price_fig.update_layout(
        height=680,
        title=f"Price Discovery - {product}",
        uirevision=f"price-{day}-{product}-{theme}-{line_shape}-{smooth_window}-{show_price_trades}",
        **_layout_base(theme),
    )
    price_fig.update_annotations(**_subplot_title_style(theme))
    price_fig.update_xaxes(rangeslider_visible=True, row=2, col=1)
    price_fig.update_yaxes(title_text="Price", row=1, col=1)
    price_fig.update_yaxes(title_text="Imbalance", row=2, col=1)

    liquidity_fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.58, 0.42],
        vertical_spacing=0.07,
        subplot_titles=("Displayed Liquidity", "Spread And Rolling Volatility"),
    )
    if not orderbook_df.empty:
        liquidity_fig.add_trace(make_line_trace(orderbook_df["timestamp"], bid_volume_series, "Bid Volume", SERIES_COLORS["best_bid"], 1.9, line_shape), row=1, col=1)
        liquidity_fig.add_trace(make_line_trace(orderbook_df["timestamp"], ask_volume_series, "Ask Volume", SERIES_COLORS["best_ask"], 1.9, line_shape), row=1, col=1)
        liquidity_fig.add_trace(
            go.Scattergl(
                x=orderbook_df["timestamp"],
                y=spread_series,
                mode="lines",
                name="Spread",
                line=dict(color=SERIES_COLORS["spread"], width=1.5, shape=line_shape),
                fill="tozeroy",
                fillcolor="rgba(100,116,139,0.12)",
            ),
            row=2,
            col=1,
        )
        liquidity_fig.add_trace(make_line_trace(orderbook_df["timestamp"], rolling_vol_series, "Rolling Vol", SERIES_COLORS["rolling_vol"], 1.5, line_shape), row=2, col=1)
    add_vertical_cursor(liquidity_fig, ts_value, 2, theme)
    liquidity_fig.update_layout(
        height=580,
        title=f"Liquidity And Risk Cues - {product}",
        uirevision=f"liquidity-{day}-{product}-{theme}-{line_shape}-{smooth_window}",
        **_layout_base(theme),
    )
    liquidity_fig.update_annotations(**_subplot_title_style(theme))
    liquidity_fig.update_yaxes(title_text="Displayed Volume", row=1, col=1)
    liquidity_fig.update_yaxes(title_text="Spread / Vol", row=2, col=1)

    trade_fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.07,
        row_heights=[0.58, 0.42],
        specs=[[{}], [{"secondary_y": True}]],
        subplot_titles=("Trades Across The Full Timeline", "Trade Volume, Count, And Toxicity"),
    )
    if not trades_df.empty:
        sizes = trades_df["quantity"].clip(lower=1, upper=25) * 1.8
        trade_fig.add_trace(
            go.Scattergl(
                x=trades_df["timestamp"],
                y=trades_df["price"],
                mode="markers",
                name="Trade Price",
                marker=dict(size=sizes, color="#2563eb", opacity=0.5),
                ),
            row=1,
            col=1,
        )
        if not vwap_df.empty:
            trade_fig.add_trace(make_line_trace(vwap_df["timestamp"], vwap_series, "VWAP", SERIES_COLORS["vwap"], 1.5, line_shape), row=1, col=1)
        if not trade_volume_df.empty:
            trade_fig.add_trace(
                go.Bar(
                    x=trade_volume_df["timestamp"],
                    y=trade_volume_df["volume"],
                    name="Trade Volume",
                    marker_color=SERIES_COLORS["trade_volume"],
                    opacity=0.68,
                ),
                row=2,
                col=1,
                secondary_y=False,
            )
            trade_fig.add_trace(
                go.Scattergl(
                    x=trade_volume_df["timestamp"],
                    y=trade_volume_df["trade_count"],
                    mode="lines",
                    name="Trade Count",
                    line=dict(color=SERIES_COLORS["trade_count"], width=1.4, shape=line_shape, dash="dot"),
                ),
                row=2,
                col=1,
                secondary_y=False,
            )
            trade_fig.add_trace(
                go.Scattergl(
                    x=trade_volume_df["timestamp"],
                    y=cum_volume_series,
                    mode="lines",
                    name="Cumulative Volume",
                    line=dict(color=SERIES_COLORS["cum_volume"], width=1.4, shape=line_shape),
                ),
                row=2,
                col=1,
                secondary_y=False,
            )
        if not vpin_df.empty:
            trade_fig.add_trace(
                go.Scattergl(
                    x=vpin_df["timestamp"],
                    y=vpin_series,
                    mode="lines",
                    name="VPIN",
                    line=dict(color=SERIES_COLORS["vpin"], width=1.7, shape=line_shape),
                ),
                row=2,
                col=1,
                secondary_y=True,
            )
    add_vertical_cursor(trade_fig, ts_value, 2, theme)
    trade_fig.update_layout(
        height=650,
        title=f"Trade Flow - {product}",
        uirevision=f"trades-{day}-{product}-{theme}-{line_shape}-{smooth_window}",
        **_layout_base(theme),
    )
    trade_fig.update_annotations(**_subplot_title_style(theme))
    trade_fig.update_yaxes(title_text="Volume / Count", row=2, col=1, secondary_y=False)
    trade_fig.update_yaxes(title_text="VPIN", row=2, col=1, secondary_y=True)

    orderbook_fig = go.Figure()
    history = day_data["history"]
    if ts_value in history and product in history[ts_value]:
        order_depth = history[ts_value][product]
        bid_prices, bid_cum, ask_prices, ask_cum = build_depth_curve(order_depth)
        orderbook_fig.add_trace(
            go.Scatter(
                x=bid_prices,
                y=bid_cum,
                mode="lines+markers",
                fill="tozeroy",
                name="Bid Depth",
                line=dict(color=SERIES_COLORS["depth_bid"], width=2),
            )
        )
        orderbook_fig.add_trace(
            go.Scatter(
                x=ask_prices,
                y=ask_cum,
                mode="lines+markers",
                fill="tozeroy",
                name="Ask Depth",
                line=dict(color=SERIES_COLORS["depth_ask"], width=2),
            )
        )
        if snapshot:
            orderbook_fig.add_vline(x=snapshot["best_bid"], line_width=1, line_dash="dot", line_color=SERIES_COLORS["depth_bid"])
            orderbook_fig.add_vline(x=snapshot["best_ask"], line_width=1, line_dash="dot", line_color=SERIES_COLORS["depth_ask"])
            orderbook_fig.add_vline(x=snapshot["mid"], line_width=1, line_dash="dash", line_color=THEMES[theme]["cursor"])
    orderbook_fig.update_layout(
        title=f"Order Book Snapshot - {product} @ {ts_value}",
        height=450,
        uirevision=f"book-{day}-{product}-{theme}",
        xaxis_title="Price",
        yaxis_title="Cumulative Displayed Volume",
        **_layout_base(theme),
    )

    return summary_panel, insight_panel, current_label, cross_asset_fig, candle_fig, price_fig, liquidity_fig, trade_fig, orderbook_fig


def run_research_dashboard_server() -> None:
    """Run the research dashboard with explicit shutdown semantics.

    Using Werkzeug's server directly avoids ambiguous teardown behavior when
    stopping the dashboard with ``Ctrl+C`` on Windows terminals.
    """
    host = "127.0.0.1"
    _cleanup_dashboard_port(RESEARCH_DASHBOARD_PORT, "research dashboard")
    print(f"Starting research dashboard on http://{host}:{RESEARCH_DASHBOARD_PORT}")
    server = make_server(host, RESEARCH_DASHBOARD_PORT, app.server, threaded=False)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping research dashboard...")
    finally:
        server.server_close()
        print("Research dashboard stopped.")


if __name__ == "__main__":
    run_research_dashboard_server()
