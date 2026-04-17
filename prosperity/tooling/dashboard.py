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
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
try:
    from werkzeug.serving import make_server
    HAS_WERKZEUG = True
except ImportError:
    make_server = None
    HAS_WERKZEUG = False

try:
    from dash import Dash, dcc, html, Input, Output
    HAS_DASH = True
except ImportError:
    HAS_DASH = False


# ── Neon trace palette (catppuccin-mocha — works in dark and light) ────────
C_BID      = "#5b8fd4"   # darker blue for best bid
C_ASK      = "#d9556e"   # darker red for best ask
C_FAIR     = "#a6e3a1"   # green
C_BUY      = "#a6e3a1"   # green triangles  (maker buy)
C_SELL     = "#f38ba8"   # coral triangles  (maker sell)
C_TAKER_BUY  = "#fab387"  # orange triangles  (taker buy)
C_TAKER_SELL = "#89b4fa"  # blue triangles    (taker sell)
C_SPREAD   = "#89dceb"   # sky cyan fill
C_POSITION = "#cba6f7"   # mauve purple
C_IMB_POS  = "#a6e3a1"   # green bars
C_IMB_NEG  = "#f38ba8"   # red bars
C_PNL_TOTAL = "#f9e2af"  # yellow total line

# Per-product color palette
PRODUCT_COLORS = ["#89b4fa", "#f9e2af", "#a6e3a1", "#f38ba8", "#cba6f7", "#89dceb"]
TOOLING_DASHBOARD_PORT = 8050


def _product_color_map(symbols: list[str]) -> dict[str, str]:
    return {sym: PRODUCT_COLORS[i % len(PRODUCT_COLORS)] for i, sym in enumerate(sorted(symbols))}


def _list_listening_pids_for_port(port: int) -> list[int]:
    """Return PIDs currently listening on ``port`` on Windows."""
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        check=False,
    )
    stdout = result.stdout.decode(errors="ignore") if isinstance(result.stdout, (bytes, bytearray)) else (result.stdout or "")
    pids: set[int] = set()
    target = f":{port}"
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


def _apply_price_height_inc(heights: list, base_total: int, inc: int) -> tuple:
    """Add inc*100 px to the price row (row 0) absolute height.

    All other rows keep their absolute pixel size; the total figure height
    grows by the same amount.  Returns (new_heights, new_total).
    """
    if inc <= 0:
        return heights, base_total
    extra = inc * 100
    new_total = base_total + extra
    price_abs = heights[0] * base_total + extra
    new_heights = [price_abs / new_total] + [h * base_total / new_total for h in heights[1:]]
    return new_heights, new_total


# ── Shared helpers ─────────────────────────────────────────────────────────

def _trade_markers(fig, df: pd.DataFrame, row: int, prefix: str = ""):
    """Add buy/sell triangle markers to a subplot row.

    When the DataFrame has an ``aggressive`` column (internal backtest fills),
    taker fills use orange/blue triangles and maker fills use the standard
    green/coral triangles.  Falls back to two traces when the column is absent.
    """
    if df.empty:
        return
    mkw = dict(line=dict(width=0.6, color="#212529"))
    has_aggressive = "aggressive" in df.columns

    def _scatter(subset, name, symbol, color):
        if subset.empty:
            return
        fig.add_trace(go.Scatter(
            x=subset["timestamp"], y=subset["price"], mode="markers",
            name=f"{prefix}{name}",
            marker=dict(symbol=symbol, color=color,
                        size=(subset["quantity"].clip(1, 20) * 0.5 + 5).astype(int), **mkw),
            text=[f"qty={q}  px={p}" for q, p in zip(subset["quantity"], subset["price"])],
            hoverinfo="text+name",
        ), row=row, col=1)

    if has_aggressive:
        _scatter(df[(df["side"] == "BUY")  & (~df["aggressive"])], "Maker buy",  "triangle-up",   C_BUY)
        _scatter(df[(df["side"] == "SELL") & (~df["aggressive"])], "Maker sell", "triangle-down", C_SELL)
        _scatter(df[(df["side"] == "BUY")  &   df["aggressive"]],  "Taker buy",  "triangle-up",   C_TAKER_BUY)
        _scatter(df[(df["side"] == "SELL") &   df["aggressive"]],  "Taker sell", "triangle-down", C_TAKER_SELL)
    else:
        _scatter(df[df["side"] == "BUY"],  "Buy",  "triangle-up",   C_BUY)
        _scatter(df[df["side"] == "SELL"], "Sell", "triangle-down", C_SELL)


C_TILT_BUY  = "#f9e2af"   # yellow diamond — tilted buy fill
C_TILT_SELL = "#89dceb"   # cyan diamond  — tilted sell fill
C_GAP_BUY   = "#a6e3a1"   # green square  — gap exploit buy
C_GAP_SELL  = "#f38ba8"   # coral square  — gap exploit sell


def _gap_exploit_markers(fig, df: pd.DataFrame, row: int) -> None:
    """Square markers for gap exploit fills (subset of aggressive fills)."""
    if df.empty or "gap_exploit" not in df.columns:
        return
    gap_df = df[df["gap_exploit"].fillna(False).astype(bool)]
    if gap_df.empty:
        return
    mkw = dict(line=dict(width=1.2, color="#212529"))
    for side, color, label in [
        ("BUY",  C_GAP_BUY,  "Gap buy"),
        ("SELL", C_GAP_SELL, "Gap sell"),
    ]:
        subset = gap_df[gap_df["side"].str.upper() == side]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["timestamp"], y=subset["price"], mode="markers",
            name=label,
            marker=dict(symbol="square", color=color, size=11, **mkw),
            text=[f"qty={q}  px={p}  (gap exploit)" for q, p in zip(subset["quantity"], subset["price"])],
            hoverinfo="text+name",
        ), row=row, col=1)


def _trade_markers_tilted(fig, df: pd.DataFrame, row: int) -> None:
    """Diamond markers for fills that occurred while z-score tilt was active."""
    if df.empty:
        return
    mkw = dict(line=dict(width=0.8, color="#212529"))
    for side, color, symbol_shape in [
        ("BUY",  C_TILT_BUY,  "diamond"),
        ("SELL", C_TILT_SELL, "diamond"),
    ]:
        subset = df[df["side"].str.upper() == side]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["timestamp"], y=subset["price"], mode="markers",
            name=f"Tilted {'buy' if side == 'BUY' else 'sell'}",
            marker=dict(symbol=symbol_shape, color=color,
                        size=(subset["quantity"].clip(1, 20) * 0.5 + 6).astype(int), **mkw),
            text=[f"qty={q}  px={p}  z={z:.2f}  bf={bf:.2f}"
                  for q, p, z, bf in zip(
                      subset["quantity"], subset["price"],
                      subset.get("Z", pd.Series([float("nan")] * len(subset))).fillna(float("nan")),
                      subset.get("BidFactor", pd.Series([1.0] * len(subset))).fillna(1.0),
                  )],
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

    # Backtest days are independent and positions reset to zero at the start of
    # each day. When we stitch multiple days onto one x-axis for the dashboard,
    # preserve those daily resets instead of cumulatively carrying inventory
    # across day boundaries.
    if "day" in df.columns:
        chunks: list[pd.DataFrame] = []
        for _, day_df in df.groupby("day", sort=False):
            day_df = day_df.sort_values("timestamp").copy()
            day_df["position"] = day_df["signed_qty"].cumsum()

            day_start_ts = (
                int(day_df["day_start_timestamp"].iloc[0])
                if "day_start_timestamp" in day_df.columns
                else int(day_df["timestamp"].iloc[0])
            )
            reset_row = pd.DataFrame([{"timestamp": day_start_ts, "position": 0}])
            # Hold final position flat until end-of-day so the line does not
            # visually disappear after the last fill.
            day_end_ts = day_start_ts + 999_900
            final_pos = int(day_df["position"].iloc[-1])
            tail_row = pd.DataFrame([{"timestamp": day_end_ts, "position": final_pos}])
            chunks.append(pd.concat(
                [reset_row, day_df[["timestamp", "position"]], tail_row],
                ignore_index=True,
            ))

        return pd.concat(chunks, ignore_index=True).sort_values("timestamp", kind="stable")

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

    for day in sorted(backtest_data["days"], key=lambda d: int(d["day"])):
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

        summary_syms = sorted(day.get("product_summaries", {}).keys())
        if has_market:
            all_syms = sorted(day_mkt["product"].unique())
        elif not fills_df.empty:
            all_syms = sorted(fills_df["symbol"].unique())
        elif summary_syms:
            all_syms = summary_syms
        else:
            all_syms = []
        # Include any product that has summary data even if not in market/fills
        all_syms = sorted(set(all_syms) | set(summary_syms))

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

            # MidSmooth lookup from feature_ticks (smoother fair value for MTM)
            _ft_smooth: dict[int, float] = {}
            for ft in day.get("feature_ticks", []):
                if ft.get("symbol") == sym:
                    ms = ft.get("MidSmooth")
                    if ms is not None:
                        _ft_smooth[int(ft["timestamp"])] = float(ms)

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
                        raw_mid = ((bid + ask) / 2.0 if pd.notna(bid) and pd.notna(ask)
                                   else float(bid if pd.notna(bid) else ask if pd.notna(ask) else 0))
                    else:
                        raw_mid = 0.0
                    # Prefer strategy's smoothed fair value (MidSmooth) over raw mid
                    fair = _ft_smooth.get(ts, raw_mid)
                    intraday_pnl = cash + position * fair
                elif _ft_smooth:
                    # No market CSV but we have MidSmooth from strategy feature_ticks
                    fair = _ft_smooth.get(ts)
                    intraday_pnl = cash + position * fair if fair is not None else cash
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


C_DIVERGENCE = "rgba(180, 100, 255, 0.14)"   # light purple — trade-divergence bands


def _add_divergence_bands(fig: go.Figure, divergent_ts: set, row: int, col: int = 1) -> None:
    """Add a light-purple full-height band for every timestamp in *this* panel
    that is absent from the comparison panel (i.e. unique trades here)."""
    if not divergent_ts:
        return
    for ts in sorted(divergent_ts):
        fig.add_shape(
            type="rect",
            x0=ts - 50, x1=ts + 50,
            y0=0, y1=1,
            yref="y domain",
            xref="x",
            fillcolor=C_DIVERGENCE,
            line_width=0,
            layer="below",
            row=row, col=col,
        )


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


def build_imc_figure(log, symbol: str, theme: str = "dark", smooth_n: int = 0, line_shape: str = "linear", price_height_inc: int = 0, divergent_ts: set | None = None) -> go.Figure:
    _mode = "lines+markers" if line_shape == "hv" else "lines"
    _marker = dict(size=3) if line_shape == "hv" else {}
    from prosperity.tooling.logs import _compute_activity_features, _parse_lambda_logs, official_market_trade_flow

    act = log.activities[log.activities["product"] == symbol].copy().sort_values("timestamp")
    if act.empty:
        return go.Figure()

    act = _compute_activity_features(act)
    sym_trades = _imc_sym_trades(log.trades, symbol)

    # Annotate trades with taker/maker using strategy-logged taker_fills trace
    from prosperity.tooling.logs import _parse_taker_fills
    taker_df = _parse_taker_fills(log.runtime_logs)
    sym_takers = taker_df[taker_df["product"] == symbol] if not taker_df.empty else pd.DataFrame()
    if not sym_trades.empty and not sym_takers.empty:
        taker_price_side = set(zip(sym_takers["price"].astype(int), sym_takers["side"].str.upper()))
        sym_trades["aggressive"] = sym_trades.apply(
            lambda r: (int(r["price"]), str(r["side"]).upper()) in taker_price_side, axis=1,
        )
        # Gap exploit annotation — subset of takers flagged in the logged trace
        _gap_col = sym_takers.get("gap_exploit", pd.Series(False, index=sym_takers.index)).fillna(False)
        _gap_takers = sym_takers[_gap_col.astype(bool)]
        if not _gap_takers.empty:
            gap_price_side = set(zip(_gap_takers["price"].astype(int), _gap_takers["side"].str.upper()))
            sym_trades["gap_exploit"] = sym_trades.apply(
                lambda r: (int(r["price"]), str(r["side"]).upper()) in gap_price_side, axis=1,
            )
        else:
            sym_trades["gap_exploit"] = False

    pos_df = _position_series(sym_trades)
    market_flow_df = official_market_trade_flow(log, symbol)
    lambda_df = _parse_lambda_logs(log.runtime_logs)
    lambda_sym = lambda_df[lambda_df["product"] == symbol] if not lambda_df.empty else pd.DataFrame()

    # Detect vol-scale and zscore columns in lambda logs
    _skip = {"timestamp", "product", "bid_price", "ask_price", "reservation", "position"}
    _lambda_extra = [c for c in lambda_sym.columns if c not in _skip] if not lambda_sym.empty else []
    _vol_cols  = [c for c in _lambda_extra if "sigma" in c.lower() or "vol" in c.lower()]
    has_vol    = bool(_vol_cols)
    has_zscore = "zscore" in _lambda_extra and not lambda_sym.empty

    # Row layout: price + spread + flow + position (4 fixed), then optional vol/zscore, then pnl
    flow_row     = 3
    position_row = 4
    next_row     = 5
    n_rows  = 4
    heights = [0.46, 0.08, 0.10, 0.10]
    titles  = ["Price & Trades", "Spread (Market vs Quote)", "Trade Flow", "Position & Imbalance"]
    vol_row    = None
    zscore_row = None

    if has_vol:
        vol_row = next_row
        heights.append(0.18)
        titles.append("Volatility (σ)")
        next_row += 1
        n_rows   += 1

    if has_zscore:
        zscore_row = next_row
        heights.append(0.18)
        titles.append("Z-score")
        next_row += 1
        n_rows   += 1

    # PnL is always last
    pnl_row = next_row
    heights.append(0.18)
    titles.append("PnL")
    n_rows += 1

    height = 940 + 120 * int(has_vol) + 120 * int(has_zscore)
    heights, height = _apply_price_height_inc(heights, height, price_height_inc)

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=heights,
        subplot_titles=titles,
        vertical_spacing=0.07,
    )

    # Price (with optional EWMA smoothing)
    fig.add_trace(go.Scatter(x=act["timestamp"], y=_smooth(act["bid_price_1"], smooth_n),
        customdata=act["bid_volume_1"].values,
        name="Best Bid", mode=_mode, marker=dict(**_marker, color=C_BID),
        line=dict(color=C_BID, width=1, shape=line_shape),
        hovertemplate="%{y} ×%{customdata}<extra>Best Bid</extra>",
        ), row=1, col=1)
    fig.add_trace(go.Scatter(x=act["timestamp"], y=_smooth(act["ask_price_1"], smooth_n),
        customdata=act["ask_volume_1"].values,
        name="Best Ask", mode=_mode, marker=dict(**_marker, color=C_ASK),
        line=dict(color=C_ASK, width=1, shape=line_shape),
        hovertemplate="%{y} ×%{customdata}<extra>Best Ask</extra>",
        ), row=1, col=1)
    fig.add_trace(go.Scatter(x=act["timestamp"], y=_smooth(act["fair"], smooth_n),
        name="Fair (EWM)", mode=_mode, marker=dict(**_marker, color=C_FAIR),
        line=dict(color=C_FAIR, width=1.3, shape=line_shape)), row=1, col=1)
    _trade_markers(fig, sym_trades, row=1)
    _gap_exploit_markers(fig, sym_trades, row=1)
    if divergent_ts:
        _add_divergence_bands(fig, divergent_ts, row=1)

    # Strategy lambda logs: reservation price, mid_smooth, and MM quotes (no smoothing on discrete prices)
    if not lambda_sym.empty:
        if "mid_smooth" in lambda_sym.columns:
            ms_data = lambda_sym.dropna(subset=["mid_smooth"])
            if not ms_data.empty:
                fig.add_trace(go.Scatter(
                    x=ms_data["timestamp"], y=ms_data["mid_smooth"],
                    name="MidSmooth", mode=_mode,
                    marker=dict(**_marker, color=C_FEATURE_PALETTE[0]),
                    line=dict(color=C_FEATURE_PALETTE[0], width=1.2, shape=line_shape, dash="dot"),
                ), row=1, col=1)
        if "fair_value" in lambda_sym.columns:
            fv_data = lambda_sym.dropna(subset=["fair_value"])
            if not fv_data.empty:
                fig.add_trace(go.Scatter(
                    x=fv_data["timestamp"], y=fv_data["fair_value"],
                    name="Strategy fair (block-OLS reg)", mode=_mode,
                    marker=dict(**_marker, color="#9c36b5"),
                    line=dict(color="#9c36b5", width=1.6, shape=line_shape, dash="dash"),
                ), row=1, col=1)
        if "reservation" in lambda_sym.columns:
            res_data = lambda_sym.dropna(subset=["reservation"])
            if not res_data.empty:
                fig.add_trace(go.Scatter(x=res_data["timestamp"], y=_smooth(res_data["reservation"], smooth_n),
                    name="Reservation", mode=_mode, marker=dict(**_marker, color=C_FEATURE_PALETTE[0]),
                    line=dict(color=C_FEATURE_PALETTE[0], width=1.2, shape=line_shape)), row=1, col=1)
        bid_data = lambda_sym.dropna(subset=["bid_price"])
        ask_data = lambda_sym.dropna(subset=["ask_price"])
        if not bid_data.empty:
            _lbd_bid_sizes = bid_data["bid_size"].values if "bid_size" in bid_data.columns else None
            fig.add_trace(go.Scatter(x=bid_data["timestamp"], y=bid_data["bid_price"],
                customdata=_lbd_bid_sizes,
                name="MM Bid (log)", mode=_mode, marker=dict(**_marker, color=C_QUOTE_BID),
                line=dict(color=C_QUOTE_BID, width=1, shape=line_shape),
                hovertemplate=("%{y} ×%{customdata}<extra>MM Bid (log)</extra>"
                               if _lbd_bid_sizes is not None else "%{y}<extra>MM Bid (log)</extra>"),
                ), row=1, col=1)
        if not ask_data.empty:
            _lbd_ask_sizes = ask_data["ask_size"].values if "ask_size" in ask_data.columns else None
            fig.add_trace(go.Scatter(x=ask_data["timestamp"], y=ask_data["ask_price"],
                customdata=_lbd_ask_sizes,
                name="MM Ask (log)", mode=_mode, marker=dict(**_marker, color=C_QUOTE_ASK),
                line=dict(color=C_QUOTE_ASK, width=1, shape=line_shape),
                hovertemplate=("%{y} ×%{customdata}<extra>MM Ask (log)</extra>"
                               if _lbd_ask_sizes is not None else "%{y}<extra>MM Ask (log)</extra>"),
                ), row=1, col=1)

    # Spread
    fig.add_trace(go.Scatter(x=act["timestamp"], y=act["spread"], name="Spread",
        line=dict(color=C_SPREAD, width=1), fill="tozeroy",
        fillcolor="rgba(134,142,150,0.15)", showlegend=False), row=2, col=1)
    if not lambda_sym.empty:
        quote_spread = (lambda_sym["ask_price"] - lambda_sym["bid_price"]).dropna()
        if not quote_spread.empty:
            quote_spread_df = lambda_sym.loc[quote_spread.index, ["timestamp"]].copy()
            quote_spread_df["spread"] = quote_spread.values
            fig.add_trace(go.Scatter(
                x=quote_spread_df["timestamp"], y=quote_spread_df["spread"],
                name="Quoted Spread", mode=_mode, marker=dict(**_marker, color=C_FEATURE_PALETTE[1]),
                line=dict(color=C_FEATURE_PALETTE[1], width=1.2, shape=line_shape)), row=2, col=1)

    if not market_flow_df.empty:
        flow_by_timestamp = market_flow_df.groupby("timestamp", as_index=False)["signed_quantity"].sum()
        fig.add_trace(go.Bar(
            x=flow_by_timestamp["timestamp"], y=flow_by_timestamp["signed_quantity"],
            name="All Trade Flow",
            marker_color=[C_IMB_POS if value > 0 else C_IMB_NEG for value in flow_by_timestamp["signed_quantity"]],
            opacity=0.55), row=flow_row, col=1)
    if not sym_trades.empty:
        submission_flow = sym_trades.groupby("timestamp", as_index=False)["signed_qty"].sum()
        fig.add_trace(go.Scatter(
            x=submission_flow["timestamp"], y=submission_flow["signed_qty"],
            name="Submission Flow", mode="lines+markers",
            marker=dict(size=4, color=C_PNL_TOTAL),
            line=dict(color=C_PNL_TOTAL, width=1.4, shape=line_shape)), row=flow_row, col=1)

    # Position
    if not pos_df.empty:
        fig.add_trace(go.Scatter(x=pos_df["timestamp"], y=pos_df["position"], name="Position",
            mode="lines", line=dict(color=C_POSITION, width=1.5, shape=line_shape),
            fill="tozeroy", fillcolor="rgba(112,72,232,0.12)"), row=position_row, col=1)

    # Imbalance
    bv = act["bid_volume_1"].clip(lower=1)
    av = act["ask_volume_1"].clip(lower=1)
    imb = (bv - av) / (bv + av)
    fig.add_trace(go.Bar(x=act["timestamp"], y=imb, name="Imbalance",
        marker_color=[C_IMB_POS if v > 0 else C_IMB_NEG for v in imb],
        opacity=0.6, showlegend=False), row=position_row, col=1)

    # Volatility subplot (sigma and other vol-scale lambda columns)
    if vol_row is not None and not lambda_sym.empty:
        for i, feat in enumerate(_vol_cols):
            col_data = lambda_sym.dropna(subset=[feat])
            if col_data.empty:
                continue
            color = C_FEATURE_PALETTE[i % len(C_FEATURE_PALETTE)]
            fig.add_trace(go.Scatter(
                x=col_data["timestamp"], y=_smooth(col_data[feat], smooth_n),
                name=feat, mode=_mode, marker=dict(**_marker, color=color),
                line=dict(color=color, width=1.3, shape=line_shape),
            ), row=vol_row, col=1)

    # Z-score subplot
    if zscore_row is not None and not lambda_sym.empty:
        z_data = lambda_sym[["timestamp", "zscore"]].dropna(subset=["zscore"]).sort_values("timestamp")
        if not z_data.empty:
            fig.add_trace(go.Scatter(
                x=z_data["timestamp"], y=z_data["zscore"],
                name="Z-score", mode=_mode, marker=dict(**_marker, color=C_FEATURE_PALETTE[2]),
                line=dict(color=C_FEATURE_PALETTE[2], width=1.3, shape=line_shape),
            ), row=zscore_row, col=1)
            for level, dash in [(1.0, "dash"), (-1.0, "dash"), (2.0, "dot"), (-2.0, "dot")]:
                fig.add_hline(y=level, line_dash=dash, line_color="rgba(255,255,255,0.25)",
                              line_width=1, row=zscore_row, col=1)

    # PnL — per-product areas + total line
    pnl_df = _imc_per_product_pnl(log)
    symbols = sorted(pnl_df["symbol"].unique())
    color_map = _product_color_map(symbols)
    _add_pnl_traces(fig, pnl_df, color_map, row=pnl_row, total_df=log.graph if not log.graph.empty else None)

    height = 1360 if has_vol else 1220
    fig.update_layout(height=height, uirevision=f"imc-{symbol}", **_layout_base(theme))
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

    for day in sorted(backtest_data["days"], key=lambda d: int(d["day"])):
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
            all_fills.append({
                **f,
                "day": day["day"],
                "day_start_timestamp": ts_offset,
                "timestamp": f["timestamp"] + ts_offset,
            })

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
                          price_height_inc: int = 0,
                          _precomputed: tuple | None = None,
                          _per_prod_pnl: pd.DataFrame | None = None,
                          divergent_ts: set | None = None) -> go.Figure:
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

    # Detect vol-scale features (sigma / vol) to route to a dedicated subplot.
    # Detect z-score panel columns: "Z", "BidFactor", "AskFactor" (from ZScoreStrategy).
    _all_feat_cols = (
        [c for c in sym_features.columns if c not in ("timestamp", "symbol")]
        if not sym_features.empty else []
    )
    _vol_feat_cols   = [c for c in _all_feat_cols if "sigma" in c.lower() or "vol" in c.lower()]
    _zscore_col      = "Z" if "Z" in _all_feat_cols else None
    _zfactor_cols    = [c for c in _all_feat_cols if c in ("BidFactor", "AskFactor")]
    _price_feat_cols = [c for c in _all_feat_cols
                        if c not in _vol_feat_cols
                        and c != _zscore_col
                        and c not in _zfactor_cols]
    has_vol    = bool(_vol_feat_cols)             # show vol when features present, even without market CSV
    has_zscore = bool(_zscore_col)               # show Z-score when "Z" feature present (no BidFactor required)

    # Dynamic layout builder: price + position (base), then optional vol/zscore, then pnl
    price_row = 1 if has_market else None
    pos_row   = 2 if has_market else 1
    next_row  = pos_row + 1
    n_rows    = 2 if has_market else 1
    heights   = [0.38, 0.13] if has_market else [0.20]
    titles    = ["Price & Fills", "Position"] if has_market else ["Position"]
    vol_row    = None
    zscore_row = None

    if has_vol:
        vol_row = next_row
        heights.append(0.13)
        titles.append("Volatility (σ)")
        next_row += 1
        n_rows   += 1

    if has_zscore:
        zscore_row = next_row
        heights.append(0.16)
        titles.append("Z-score")
        next_row += 1
        n_rows   += 1

    pnl_row = next_row
    heights.append(0.20)
    titles.append("Equity PnL")
    n_rows += 1

    height = 800
    heights, height = _apply_price_height_inc(heights, height, price_height_inc)

    fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=heights, subplot_titles=titles, vertical_spacing=0.05)

    price_row = 1
    pos_row   = 2 if has_market else 1

    # Price + fills
    if has_market:
        sym_mkt = market_df[market_df["product"] == symbol].sort_values("timestamp")
        if not sym_mkt.empty:
            fig.add_trace(go.Scatter(x=sym_mkt["timestamp"],
                y=_smooth(sym_mkt["bid_price_1"], smooth_n),
                customdata=sym_mkt["bid_volume_1"].values,
                name="Best Bid", mode=_mode, marker=dict(**_marker, color=C_BID),
                line=dict(color=C_BID, width=1, shape=line_shape),
                hovertemplate="%{y} ×%{customdata}<extra>Best Bid</extra>",
                ), row=price_row, col=1)
            fig.add_trace(go.Scatter(x=sym_mkt["timestamp"],
                y=_smooth(sym_mkt["ask_price_1"], smooth_n),
                customdata=sym_mkt["ask_volume_1"].values,
                name="Best Ask", mode=_mode, marker=dict(**_marker, color=C_ASK),
                line=dict(color=C_ASK, width=1, shape=line_shape),
                hovertemplate="%{y} ×%{customdata}<extra>Best Ask</extra>",
                ), row=price_row, col=1)
            mid = (sym_mkt["bid_price_1"] + sym_mkt["ask_price_1"]) / 2
            fig.add_trace(go.Scatter(x=sym_mkt["timestamp"], y=_smooth(mid, smooth_n),
                name="Mid", mode=_mode, marker=dict(**_marker, color=C_FAIR),
                line=dict(color=C_FAIR, width=1, shape=line_shape)), row=price_row, col=1)

        # MM quotes overlay — never smooth (discrete integer prices; smoothing crosses bid/ask)
        if not sym_quotes.empty:
            bid_q = sym_quotes.dropna(subset=["bid"])
            ask_q = sym_quotes.dropna(subset=["ask"])
            if not bid_q.empty:
                _bid_sizes = bid_q["bid_size"].values if "bid_size" in bid_q.columns else None
                fig.add_trace(go.Scatter(
                    x=bid_q["timestamp"], y=bid_q["bid"],
                    customdata=_bid_sizes,
                    name="MM Bid Quote", mode=_mode, marker=dict(**_marker, color=C_QUOTE_BID),
                    line=dict(color=C_QUOTE_BID, width=1, shape=line_shape),
                    hovertemplate=("%{y} ×%{customdata}<extra>MM Bid Quote</extra>"
                                  if _bid_sizes is not None else "%{y}<extra>MM Bid Quote</extra>"),
                ), row=price_row, col=1)
            if not ask_q.empty:
                _ask_sizes = ask_q["ask_size"].values if "ask_size" in ask_q.columns else None
                fig.add_trace(go.Scatter(
                    x=ask_q["timestamp"], y=ask_q["ask"],
                    customdata=_ask_sizes,
                    name="MM Ask Quote", mode=_mode, marker=dict(**_marker, color=C_QUOTE_ASK),
                    line=dict(color=C_QUOTE_ASK, width=1, shape=line_shape),
                    hovertemplate=("%{y} ×%{customdata}<extra>MM Ask Quote</extra>"
                                  if _ask_sizes is not None else "%{y}<extra>MM Ask Quote</extra>"),
                ), row=price_row, col=1)

        # Strategy feature price lines (e.g. reservation price) on price chart
        if not sym_features.empty:
            for i, feat in enumerate(_price_feat_cols):
                col_data = sym_features.dropna(subset=[feat])
                if col_data.empty:
                    continue
                color = C_FEATURE_PALETTE[i % len(C_FEATURE_PALETTE)]
                fig.add_trace(go.Scatter(
                    x=col_data["timestamp"], y=_smooth(col_data[feat], smooth_n),
                    name=feat, mode=_mode, marker=dict(**_marker, color=color),
                    line=dict(color=color, width=1.3, shape=line_shape),
                ), row=price_row, col=1)

        # Tilted-fill-aware markers: only when BidFactor/AskFactor columns are present
        # (legacy ZScoreStrategy). For strategies that only export "Z", fall through to plain markers.
        if has_zscore and bool(_zfactor_cols) and not sym_fills.empty and not sym_features.empty:
            _zf_cols = ["timestamp"] + [c for c in ("Z", "BidFactor", "AskFactor") if c in sym_features.columns]
            _zf_data = sym_features[_zf_cols].dropna(subset=["BidFactor"]).sort_values("timestamp")
            _merged  = pd.merge_asof(sym_fills.sort_values("timestamp"), _zf_data, on="timestamp")
            _tilted  = _merged[
                ((_merged["BidFactor"].fillna(1.0) - 1.0).abs() > 0.01) |
                ((_merged["AskFactor"].fillna(1.0) - 1.0).abs() > 0.01)
            ]
            _neutral = _merged[~_merged.index.isin(_tilted.index)]
            _trade_markers(fig, _neutral, row=price_row, prefix="")
            _trade_markers_tilted(fig, _tilted, row=price_row)
            _gap_exploit_markers(fig, _merged, row=price_row)
        else:
            _trade_markers(fig, sym_fills, row=price_row)
            _gap_exploit_markers(fig, sym_fills, row=price_row)
        if divergent_ts:
            _add_divergence_bands(fig, divergent_ts, row=price_row)

    # Position
    pos_df = _position_series(sym_fills)
    if not pos_df.empty:
        fig.add_trace(go.Scatter(x=pos_df["timestamp"], y=pos_df["position"], name="Position",
            mode="lines", line=dict(color=C_POSITION, width=1.5, shape=line_shape),
            fill="tozeroy", fillcolor="rgba(112,72,232,0.12)"), row=pos_row, col=1)

    # Volatility (sigma and other vol-scale features) — backtest only
    if vol_row is not None and not sym_features.empty:
        for i, feat in enumerate(_vol_feat_cols):
            col_data = sym_features.dropna(subset=[feat])
            if col_data.empty:
                continue
            color = C_FEATURE_PALETTE[(len(_price_feat_cols) + i) % len(C_FEATURE_PALETTE)]
            fig.add_trace(go.Scatter(
                x=col_data["timestamp"], y=col_data[feat],
                name=feat, mode=_mode, marker=dict(**_marker, color=color),
                line=dict(color=color, width=1.3, shape=line_shape),
            ), row=vol_row, col=1)

    # Z-score subplot
    if zscore_row is not None and not sym_features.empty and _zscore_col is not None:
        z_data = sym_features[["timestamp", "Z"]].dropna(subset=["Z"]).sort_values("timestamp")
        if not z_data.empty:
            fig.add_trace(go.Scatter(
                x=z_data["timestamp"], y=z_data["Z"],
                name="Z-score", mode=_mode, marker=dict(**_marker, color="#cba6f7"),
                line=dict(color="#cba6f7", width=1.4, shape=line_shape),
            ), row=zscore_row, col=1)
            for level, dash in [(1.0, "dash"), (-1.0, "dash"), (2.0, "dot"), (-2.0, "dot")]:
                fig.add_hline(y=level, line_dash=dash, line_color="rgba(255,255,255,0.25)",
                              line_width=1, row=zscore_row, col=1)
            fig.add_hline(y=0, line_color="rgba(150,150,150,0.4)",
                          line_dash="dot", line_width=1, row=zscore_row, col=1)
            # BidFactor / AskFactor overlay when present (legacy ZScoreStrategy)
            for col_name, color, label in [
                ("BidFactor", "#a6e3a1", "Bid factor"),
                ("AskFactor", "#f38ba8", "Ask factor"),
            ]:
                if col_name in sym_features.columns:
                    fd = sym_features[["timestamp", col_name]].dropna(subset=[col_name])
                    if not fd.empty:
                        fig.add_trace(go.Scatter(
                            x=fd["timestamp"], y=fd[col_name],
                            name=label, mode=_mode, marker=dict(**_marker, color=color),
                            line=dict(color=color, width=1, dash="dot", shape=line_shape),
                        ), row=zscore_row, col=1)

    # Equity PnL — per-product stacked areas + total line
    per_prod_pnl = _per_prod_pnl if _per_prod_pnl is not None else _bt_per_product_pnl(backtest_data, market_df_raw)
    if not per_prod_pnl.empty:
        bt_color_map = _product_color_map(sorted(per_prod_pnl["symbol"].unique()))
        _add_pnl_traces(fig, per_prod_pnl, bt_color_map, row=pnl_row,
                        total_df=equity_df if not equity_df.empty else None)
    elif not equity_df.empty:
        fig.add_trace(go.Scatter(x=equity_df["timestamp"], y=equity_df["value"],
            name="Total PnL", line=dict(color=C_PNL_TOTAL, width=2)), row=pnl_row, col=1)

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


def run_dash(log=None, log2=None, backtest_data: dict | None = None, data_dir: str | None = None,
             log_path: str | None = None, log2_path: str | None = None,
             backtest_json_path: str | None = None, backtest_json2_path: str | None = None,
             backtest_data2: dict | None = None,
             reconcile_report: dict | None = None,
             price_height_inc: int = 0):
    if not HAS_DASH:
        print("dash not installed. Run: pip install dash")
        return
    if not HAS_WERKZEUG:
        print("werkzeug not installed. Run: pip install werkzeug")
        return

    from dash import State

    imc_symbols: list[str] = sorted(log.activities["product"].dropna().unique()) if log else []
    imc2_symbols: list[str] = sorted(log2.activities["product"].dropna().unique()) if log2 else []
    bt_symbols: list[str] = []
    if backtest_data:
        all_fills = [f for d in backtest_data["days"] for f in d["fills"]]
        fill_syms = {f["symbol"] for f in all_fills}
        summary_syms = {sym for d in backtest_data["days"] for sym in d.get("product_summaries", {})}
        bt_symbols = sorted(fill_syms | summary_syms)
    bt2_symbols: list[str] = []
    if backtest_data2:
        all_fills2 = [f for d in backtest_data2["days"] for f in d["fills"]]
        fill_syms2 = {f["symbol"] for f in all_fills2}
        summary_syms2 = {sym for d in backtest_data2["days"] for sym in d.get("product_summaries", {})}
        bt2_symbols = sorted(fill_syms2 | summary_syms2)

    all_symbols = sorted(set(imc_symbols) | set(imc2_symbols) | set(bt_symbols) | set(bt2_symbols))
    if not all_symbols:
        print("No symbols found.")
        return

    # Pre-load raw market data (shared by both backtests — same round assumed)
    market_df_raw: pd.DataFrame | None = None
    _active_bt = backtest_data or backtest_data2
    if _active_bt and data_dir is None:
        # Auto-detect the data directory from the project root
        from pathlib import Path as _Path
        for _candidate in ("data", "../data"):
            if _Path(_candidate).exists():
                data_dir = _candidate
                print(f"Auto-detected market data directory: {_candidate}")
                break
    if data_dir and _active_bt:
        from prosperity.tooling.data import MarketDataLoader
        loader = MarketDataLoader(data_dir)
        round_num = _active_bt.get("round", 0)
        _ref_days = sorted(_active_bt["days"], key=lambda d: int(d["day"]))
        frames = []
        for day in _ref_days:
            try:
                df = loader.load_prices(f"prices_round_{round_num}_day_{day['day']}.csv")
                df["day"] = str(day["day"])
                frames.append(df)
            except Exception:
                pass
        market_df_raw = pd.concat(frames, ignore_index=True) if frames else None

    # Subtitle lines
    parts = []
    loaded_files = []
    if log:
        parts.append(f"IMC #1 · {log.submission_id}  |  profit = {log.profit}")
    if log2:
        parts.append(f"IMC #2 · {log2.submission_id}  |  profit = {log2.profit}")
    if backtest_data and not log2:
        total = sum(d["pnl"] for d in backtest_data["days"])
        days_str = ", ".join(str(d["day"]) for d in backtest_data["days"])
        label = "Backtest #1" if backtest_data2 else "Backtest"
        parts.append(f"{label} · {backtest_data.get('strategy', '')}  |  PnL = {total:+.2f}  (days {days_str})")
    if backtest_data2 and not log2:
        total2 = sum(d["pnl"] for d in backtest_data2["days"])
        days_str2 = ", ".join(str(d["day"]) for d in backtest_data2["days"])
        parts.append(f"Backtest #2 · {backtest_data2.get('strategy', '')}  |  PnL = {total2:+.2f}  (days {days_str2})")
    if log_path:
        loaded_files.append(f"Log: {log_path}")
    if log2_path:
        loaded_files.append(f"Log2: {log2_path}")
    if backtest_json_path and not log2:
        loaded_files.append(f"BT1: {backtest_json_path}")
    if backtest_json2_path and not log2:
        loaded_files.append(f"BT2: {backtest_json2_path}")
    if data_dir:
        loaded_files.append(f"Market data: {data_dir}")
    if loaded_files:
        parts.append("Files: " + "  |  ".join(loaded_files))

    # ── Precompute expensive data merges once at startup ──
    bt_precomputed: tuple | None = None
    bt_per_prod_pnl: pd.DataFrame = pd.DataFrame()
    if backtest_data:
        bt_precomputed = _merge_backtest_days(backtest_data, market_df_raw)
        bt_per_prod_pnl = _bt_per_product_pnl(backtest_data, market_df_raw)
        print("Precomputed backtest data.")

    bt2_precomputed: tuple | None = None
    bt2_per_prod_pnl: pd.DataFrame = pd.DataFrame()
    if backtest_data2:
        bt2_precomputed = _merge_backtest_days(backtest_data2, market_df_raw)
        bt2_per_prod_pnl = _bt_per_product_pnl(backtest_data2, market_df_raw)
        print("Precomputed backtest2 data.")

    app = Dash(__name__, title="Prosperity Trading Dashboard")

    # ── Static layout shell (theme-independent IDs) ──
    chart_ids: list[str] = []
    if log:
        chart_ids.append("imc-chart")
    if log2 or backtest_data:
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
                html.Div(id="quotes-toggle", style={"display": "none"}),
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

    # ── Rebuild charts area on theme, symbol, or smooth change ──
    @app.callback(
        Output("charts-area", "children"),
        Input("theme-store", "data"),
        Input("symbol-select", "value"),
        Input("smooth-toggle", "value"),
        Input("smooth-n", "value"),
        Input("step-toggle", "value"),
    )
    def update_charts(theme, symbol, smooth_value, smooth_n_raw, step_value):
        smooth_n = int(smooth_n_raw or 0) if smooth_value else 0
        line_shape = "hv" if step_value else "linear"

        # ── Trade-divergence: timestamps where panels differ ──────────────
        # A timestamp is "divergent" in panel A when:
        #   - panel A traded there but panel B didn't, OR
        #   - both traded but with different price or quantity on any fill.
        # We compare the full set of (side, price, qty) tuples per timestamp.

        def _trade_dict(df: pd.DataFrame) -> dict:
            """Build {timestamp: frozenset of (side, price, qty)} from a fills/trades df."""
            result: dict = {}
            for row in df.itertuples(index=False):
                ts  = int(row.timestamp)
                key = (str(row.side).upper(), int(row.price), int(row.quantity))
                if ts in result:
                    result[ts] = result[ts] | {key}
                else:
                    result[ts] = frozenset({key})
            # freeze all sets
            return {ts: frozenset(v) for ts, v in result.items()}

        def _bt_trade_dict(fills_df: pd.DataFrame) -> dict:
            if fills_df is None or fills_df.empty:
                return {}
            sub = fills_df[fills_df["symbol"] == symbol]
            return _trade_dict(sub) if not sub.empty else {}

        def _imc_trade_dict(log_obj) -> dict:
            trades = _imc_sym_trades(log_obj.trades, symbol)
            return _trade_dict(trades) if not trades.empty else {}

        def _divergent_ts(dict_a: dict, dict_b: dict) -> tuple[set, set]:
            """Return (only_or_diff_in_a, only_or_diff_in_b)."""
            all_ts = set(dict_a) | set(dict_b)
            diff_a, diff_b = set(), set()
            for ts in all_ts:
                a, b = dict_a.get(ts), dict_b.get(ts)
                if a != b:
                    if a is not None:
                        diff_a.add(ts)
                    if b is not None:
                        diff_b.add(ts)
            return diff_a, diff_b

        div_log1: set = set()
        div_log2: set = set()
        if log and log2:
            div_log1, div_log2 = _divergent_ts(_imc_trade_dict(log), _imc_trade_dict(log2))

        div_bt1: set = set()
        div_bt2: set = set()
        if backtest_data and backtest_data2 and bt_precomputed and bt2_precomputed:
            div_bt1, div_bt2 = _divergent_ts(_bt_trade_dict(bt_precomputed[0]), _bt_trade_dict(bt2_precomputed[0]))

        children = []
        if log:
            children += [
                _section_header("IMC Simulation Results", theme),
                html.Div(
                    dcc.Graph(id="imc-chart",
                              figure=build_imc_figure(log, symbol, theme, smooth_n=smooth_n, line_shape=line_shape,
                                                      price_height_inc=price_height_inc,
                                                      divergent_ts=div_log1 or None),
                              config=_GRAPH_CONFIG),
                    style=_card_style(theme),
                ),
            ]
        if log and (log2 or backtest_data or backtest_data2):
            children.append(_divider(theme))
        if log2:
            children += [
                _section_header(f"IMC Simulation #2 · {log2.submission_id}", theme),
                html.Div(
                    dcc.Graph(id="bt-chart",
                              figure=build_imc_figure(log2, symbol, theme, smooth_n=smooth_n, line_shape=line_shape,
                                                      price_height_inc=price_height_inc,
                                                      divergent_ts=div_log2 or None),
                              config=_GRAPH_CONFIG),
                    style=_card_style(theme),
                ),
            ]
        elif backtest_data and backtest_data2:
            # Two backtest panels side-by-side (stacked vertically)
            strat1 = backtest_data.get("strategy", "Backtest #1")
            strat2 = backtest_data2.get("strategy", "Backtest #2")
            children += [
                _section_header(f"Backtest #1 · {strat1}", theme),
                html.Div(
                    dcc.Graph(id="bt-chart",
                              figure=build_backtest_figure(
                                  backtest_data, symbol, market_df_raw, theme,
                                  show_quotes=True,
                                  smooth_n=smooth_n, line_shape=line_shape,
                                  price_height_inc=price_height_inc,
                                  _precomputed=bt_precomputed,
                                  _per_prod_pnl=bt_per_prod_pnl,
                                  divergent_ts=div_bt1 or None,
                              ),
                              config=_GRAPH_CONFIG),
                    style=_card_style(theme),
                ),
                _divider(theme),
                _section_header(f"Backtest #2 · {strat2}", theme),
                html.Div(
                    dcc.Graph(id="bt-chart2",
                              figure=build_backtest_figure(
                                  backtest_data2, symbol, market_df_raw, theme,
                                  show_quotes=True,
                                  smooth_n=smooth_n, line_shape=line_shape,
                                  price_height_inc=price_height_inc,
                                  _precomputed=bt2_precomputed,
                                  _per_prod_pnl=bt2_per_prod_pnl,
                                  divergent_ts=div_bt2 or None,
                              ),
                              config=_GRAPH_CONFIG),
                    style=_card_style(theme),
                ),
            ]
        elif backtest_data:
            children += [
                _section_header("Internal Backtest", theme),
                html.Div(
                    dcc.Graph(id="bt-chart",
                              figure=build_backtest_figure(
                                  backtest_data, symbol, market_df_raw, theme,
                                  show_quotes=True,
                                  smooth_n=smooth_n,
                                  line_shape=line_shape,
                                  price_height_inc=price_height_inc,
                                  _precomputed=bt_precomputed,
                                  _per_prod_pnl=bt_per_prod_pnl,
                              ),
                              config=_GRAPH_CONFIG),
                    style=_card_style(theme),
                ),
            ]
        return children

    # ── Divergence band zoom-scaling (clientside, fires on every pan/zoom) ──
    # Identifies divergence shapes by their fillcolor string, then scales their
    # x-width proportionally to the current x-range — capped at 2× the base
    # half-width of 50 data units.
    # refRange = 30 000 data units (≈ 300 ticks): below this the bands stay at
    # their base width; above (zoomed out) they scale up linearly to 2×.
    _DIV_COLOR_FRAG = "180, 100, 255"   # substring of C_DIVERGENCE rgba string
    _ZOOM_SCALE_JS = f"""
    function(relayoutData, figure) {{
        if (!figure || !relayoutData) return window.dash_clientside.no_update;
        var shapes = (figure.layout || {{}}).shapes;
        if (!shapes || !shapes.some(function(s) {{
            return s.fillcolor && s.fillcolor.indexOf('{_DIV_COLOR_FRAG}') !== -1;
        }})) return window.dash_clientside.no_update;

        var xRange;
        if (relayoutData['xaxis.autorange'] === true) {{
            // full reset — treat as maximally zoomed out
            xRange = 999900;
        }} else if (relayoutData['xaxis.range[0]'] !== undefined) {{
            xRange = relayoutData['xaxis.range[1]'] - relayoutData['xaxis.range[0]'];
        }} else {{
            return window.dash_clientside.no_update;
        }}

        var refRange  = 30000;   // ~300 ticks: transition point 1× → 4×
        var baseHalf  = 50;      // half-width at 1× (matches _add_divergence_bands)
        var scale     = Math.min(4.0, Math.max(1.0, xRange / refRange));
        var halfWidth = baseHalf * scale;

        var changed = false;
        var newShapes = shapes.map(function(s) {{
            if (!s.fillcolor || s.fillcolor.indexOf('{_DIV_COLOR_FRAG}') === -1) return s;
            var center = (parseFloat(s.x0) + parseFloat(s.x1)) / 2;
            var newX0 = center - halfWidth;
            var newX1 = center + halfWidth;
            if (newX0 === s.x0 && newX1 === s.x1) return s;
            changed = true;
            return Object.assign({{}}, s, {{ x0: newX0, x1: newX1 }});
        }});

        if (!changed) return window.dash_clientside.no_update;
        return Object.assign({{}}, figure, {{
            layout: Object.assign({{}}, figure.layout, {{ shapes: newShapes }})
        }});
    }}
    """
    for _gid in ("imc-chart", "bt-chart", "bt-chart2"):
        app.clientside_callback(
            _ZOOM_SCALE_JS,
            Output(_gid, "figure", allow_duplicate=True),
            Input(_gid, "relayoutData"),
            State(_gid, "figure"),
            prevent_initial_call=True,
        )

    host = "127.0.0.1"
    _cleanup_dashboard_port(TOOLING_DASHBOARD_PORT, "tooling dashboard")
    print(f"Starting tooling dashboard on http://{host}:{TOOLING_DASHBOARD_PORT}")
    server = make_server(host, TOOLING_DASHBOARD_PORT, app.server, threaded=False)
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
    parser.add_argument("--log2", help="Second IMC log for side-by-side comparison (replaces backtest panel)")
    parser.add_argument("--backtest-json", help="Path to backtest JSON (optional: auto-discovery is attempted from artifacts/)")
    parser.add_argument("--backtest-json2", dest="backtest_json2",
        help="Second backtest JSON — adds a second panel for strategy comparison (e.g. --backtest-json2 artifacts/bt2.json)")
    parser.add_argument("--data-dir", default=None,
        help="Market data root or per-round directory (enables price chart in backtest view)")
    parser.add_argument("--inc-height", type=int, default=0, metavar="N",
        help="Increase the Price & Fills chart height by N×100 px (e.g. --inc-height 2 adds 200 px)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.log and not args.backtest_json and not getattr(args, "log2", None):
        parser.error("Provide at least one of --log, --log2, or --backtest-json")

    log = None
    if args.log:
        from prosperity.tooling.logs import load_official_log
        log = load_official_log(args.log)
        print(f"Loaded IMC log: {log.submission_id}  profit={log.profit}")

    log2 = None
    if getattr(args, "log2", None):
        from prosperity.tooling.logs import load_official_log
        log2 = load_official_log(args.log2)
        print(f"Loaded IMC log2: {log2.submission_id}  profit={log2.profit}")

    backtest_data = None
    backtest_json_path = args.backtest_json
    if log2 is None:
        if backtest_json_path is None and log is not None:
            from prosperity.tooling.reconcile import discover_backtest_json

            discovered = discover_backtest_json(log)
            if discovered is not None:
                backtest_json_path = str(discovered)
                print(f"Auto-discovered backtest JSON: {backtest_json_path}")
            else:
                print("No confident backtest JSON auto-discovered. Pass --backtest-json to force reconciliation.")

        if backtest_json_path:
            backtest_data = json.loads(Path(backtest_json_path).read_text(encoding="utf-8"))
            total = sum(d["pnl"] for d in backtest_data["days"])
            print(f"Loaded backtest: strategy={backtest_data.get('strategy')}  "
                  f"days={[d['day'] for d in backtest_data['days']]}  total_pnl={total:.2f}")

    backtest_data2 = None
    backtest_json2_path = getattr(args, "backtest_json2", None)
    if backtest_json2_path:
        backtest_data2 = json.loads(Path(backtest_json2_path).read_text(encoding="utf-8"))
        total2 = sum(d["pnl"] for d in backtest_data2["days"])
        print(f"Loaded backtest2: strategy={backtest_data2.get('strategy')}  "
              f"days={[d['day'] for d in backtest_data2['days']]}  total_pnl={total2:.2f}")

    reconcile_report = None
    if log is not None and backtest_data is not None:
        from prosperity.tooling.reconcile import reconcile_backtest_to_official, summarize_reconcile_report

        reconcile_report = reconcile_backtest_to_official(backtest_data, log)
        print(summarize_reconcile_report(reconcile_report))

    run_dash(log=log, log2=log2, backtest_data=backtest_data, data_dir=args.data_dir,
             log_path=args.log, log2_path=getattr(args, "log2", None),
             backtest_json_path=backtest_json_path, backtest_json2_path=backtest_json2_path,
             backtest_data2=backtest_data2,
             reconcile_report=reconcile_report,
             price_height_inc=args.inc_height)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
