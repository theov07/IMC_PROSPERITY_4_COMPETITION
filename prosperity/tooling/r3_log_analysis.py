"""Round 3 official-log analysis.

This module complements the generic official-log reviewer with option-aware
diagnostics for Round 3:

* final PnL and position by product
* submission trade summary and short-horizon markouts
* option implied-vol/smile/fair-value snapshots
* reconstructed option portfolio delta/vega/gamma exposure
* static PNG plots and a compact markdown report
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Iterable

_MPL_CACHE = Path(os.environ.get("MPLCONFIGDIR", "/tmp/matplotlib-r3-log-analysis"))
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from prosperity.options.black_scholes import call_delta, call_gamma, call_price, call_vega
from prosperity.options.implied_vol import call_implied_vol
from prosperity.options.smile import fit_smile_poly, smile_predict
from prosperity.options.time import time_to_expiry_days
from prosperity.tooling.logs import OfficialLog, load_official_log


ROUND_3_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
ROUND_3_OPTIONS = [f"VEV_{strike}" for strike in ROUND_3_STRIKES]
ROUND_3_UNDERLYING = "VELVETFRUIT_EXTRACT"
ROUND_3_DELTA_ONE = ["HYDROGEL_PACK", ROUND_3_UNDERLYING]
ROUND_3_PRODUCTS = [*ROUND_3_DELTA_ONE, *ROUND_3_OPTIONS]
ROUND_3_INITIAL_TTE_DAYS = 5.0
ROUND_3_TIMESTAMP_UNITS_PER_DAY = 1_000_000
SIGMA_FLOOR = 0.005
SIGMA_CAP = 0.10
PRIOR_VOL = 0.0125


def _option_strike(symbol: str) -> int | None:
    if not symbol.startswith("VEV_"):
        return None
    try:
        return int(symbol.replace("VEV_", ""))
    except ValueError:
        return None


def _fmt(value: object, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:,.{digits}f}"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(out)


def _activities_for_round3(log: OfficialLog) -> pd.DataFrame:
    if log.activities.empty:
        return pd.DataFrame()
    frame = log.activities.copy()
    frame = frame[frame["product"].isin(ROUND_3_PRODUCTS)].copy()
    if frame.empty:
        return frame
    numeric_cols = [
        "timestamp",
        "mid_price",
        "profit_and_loss",
        "bid_price_1",
        "ask_price_1",
        "bid_volume_1",
        "ask_volume_1",
    ]
    for column in numeric_cols:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["timestamp"] = frame["timestamp"].fillna(0).astype(int)
    return frame.sort_values(["timestamp", "product"]).reset_index(drop=True)


def _submission_trades(log: OfficialLog) -> pd.DataFrame:
    if log.trades.empty:
        return pd.DataFrame(
            columns=["timestamp", "symbol", "side", "price", "quantity", "signed_quantity"]
        )

    trades = log.trades.copy()
    buyer = trades.get("buyer", pd.Series(dtype=str)).fillna("")
    seller = trades.get("seller", pd.Series(dtype=str)).fillna("")
    mask = trades["symbol"].isin(ROUND_3_PRODUCTS) & ((buyer == "SUBMISSION") | (seller == "SUBMISSION"))
    trades = trades.loc[mask].copy()
    if trades.empty:
        return pd.DataFrame(
            columns=["timestamp", "symbol", "side", "price", "quantity", "signed_quantity"]
        )

    trades["timestamp"] = pd.to_numeric(trades["timestamp"], errors="coerce").fillna(0).astype(int)
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce").fillna(0).astype(int)
    trades["side"] = trades["buyer"].fillna("").eq("SUBMISSION").map({True: "BUY", False: "SELL"})
    trades["signed_quantity"] = trades["quantity"] * trades["side"].map({"BUY": 1, "SELL": -1})
    return trades.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def _pivot_activities(activities: pd.DataFrame, value: str) -> pd.DataFrame:
    if activities.empty:
        return pd.DataFrame()
    return activities.pivot_table(index="timestamp", columns="product", values=value, aggfunc="last").sort_index()


def _position_matrix(timestamps: pd.Index, trades: pd.DataFrame) -> pd.DataFrame:
    positions = pd.DataFrame(index=pd.Index(timestamps, name="timestamp"))
    if len(positions.index) == 0:
        return positions

    for product in ROUND_3_PRODUCTS:
        product_trades = trades.loc[trades["symbol"] == product, ["timestamp", "signed_quantity"]].copy()
        if product_trades.empty:
            positions[product] = 0
            continue
        product_trades = product_trades.groupby("timestamp", as_index=False)["signed_quantity"].sum()
        product_trades["position"] = product_trades["signed_quantity"].cumsum()
        merged = pd.merge_asof(
            positions.reset_index()[["timestamp"]].sort_values("timestamp"),
            product_trades[["timestamp", "position"]].sort_values("timestamp"),
            on="timestamp",
            direction="backward",
        )
        positions[product] = merged["position"].fillna(0).astype(int).to_numpy()
    return positions


def _final_rows(activities: pd.DataFrame) -> pd.DataFrame:
    if activities.empty:
        return pd.DataFrame()
    return (
        activities.sort_values(["product", "timestamp"])
        .groupby("product", as_index=False)
        .tail(1)
        .sort_values("product")
        .reset_index(drop=True)
    )


def _trade_markouts(activities: pd.DataFrame, trades: pd.DataFrame, horizons: tuple[int, ...] = (100, 500, 1000)) -> pd.DataFrame:
    if activities.empty or trades.empty:
        return trades.copy()

    marked = trades.copy()
    for horizon in horizons:
        values: list[float | None] = []
        for trade in marked.itertuples(index=False):
            product_activities = activities.loc[activities["product"] == trade.symbol, ["timestamp", "mid_price"]]
            target_ts = int(trade.timestamp) + horizon
            future = product_activities.loc[product_activities["timestamp"] >= target_ts].head(1)
            if future.empty or pd.isna(future.iloc[0]["mid_price"]):
                values.append(None)
                continue
            future_mid = float(future.iloc[0]["mid_price"])
            if trade.side == "BUY":
                values.append(future_mid - float(trade.price))
            else:
                values.append(float(trade.price) - future_mid)
        marked[f"markout_{horizon}"] = values
    return marked


def _weighted_mean(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    valid = frame.loc[frame[column].notna()].copy()
    if valid.empty:
        return None
    weights = valid["quantity"].abs().clip(lower=1)
    return float((valid[column] * weights).sum() / weights.sum())


def _trade_summary(trades: pd.DataFrame, marked_trades: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for product in ROUND_3_PRODUCTS:
        product_trades = trades.loc[trades["symbol"] == product]
        marked = marked_trades.loc[marked_trades["symbol"] == product] if not marked_trades.empty else product_trades
        buy_qty = int(product_trades.loc[product_trades["side"] == "BUY", "quantity"].sum()) if not product_trades.empty else 0
        sell_qty = int(product_trades.loc[product_trades["side"] == "SELL", "quantity"].sum()) if not product_trades.empty else 0
        rows.append(
            {
                "product": product,
                "trade_count": int(len(product_trades)),
                "buy_qty": buy_qty,
                "sell_qty": sell_qty,
                "net_qty": int(product_trades["signed_quantity"].sum()) if not product_trades.empty else 0,
                "markout_100": _weighted_mean(marked, "markout_100"),
                "markout_500": _weighted_mean(marked, "markout_500"),
                "markout_1000": _weighted_mean(marked, "markout_1000"),
            }
        )
    return rows


def _clip_sigma(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return max(SIGMA_FLOOR, min(SIGMA_CAP, float(value)))


def _option_metrics(mid: pd.DataFrame, positions: pd.DataFrame, sample_step: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    if mid.empty or ROUND_3_UNDERLYING not in mid.columns:
        return pd.DataFrame(), pd.DataFrame()

    timestamps = [int(ts) for ts in mid.index if int(ts) % sample_step == 0]
    rows: list[dict[str, object]] = []
    exposure_rows: list[dict[str, object]] = []

    for ts in timestamps:
        row = mid.loc[ts]
        spot_raw = row.get(ROUND_3_UNDERLYING)
        if pd.isna(spot_raw):
            continue
        spot = float(spot_raw)
        tte = time_to_expiry_days(
            ts,
            ROUND_3_INITIAL_TTE_DAYS,
            timestamp_units_per_day=ROUND_3_TIMESTAMP_UNITS_PER_DAY,
        )

        iv_by_strike: dict[int, float] = {}
        for strike in ROUND_3_STRIKES:
            option_mid = row.get(f"VEV_{strike}")
            if pd.isna(option_mid):
                continue
            iv = call_implied_vol(float(option_mid), spot, strike, tte, sigma_init=PRIOR_VOL)
            iv = _clip_sigma(iv)
            if iv is not None:
                iv_by_strike[strike] = iv

        coeffs = None
        if len(iv_by_strike) >= 3:
            coeffs = fit_smile_poly(
                list(iv_by_strike.keys()),
                list(iv_by_strike.values()),
                spot,
                tte,
                degree=2,
            )

        net_delta = float(positions.loc[ts, ROUND_3_UNDERLYING]) if ts in positions.index and ROUND_3_UNDERLYING in positions else 0.0
        net_gamma = 0.0
        net_vega = 0.0
        gross_option_pos = 0

        for strike in ROUND_3_STRIKES:
            symbol = f"VEV_{strike}"
            option_mid = row.get(symbol)
            if pd.isna(option_mid):
                continue

            sigma = None
            if coeffs is not None:
                sigma = _clip_sigma(smile_predict(strike, coeffs, spot, tte))
            if sigma is None:
                sigma = iv_by_strike.get(strike)
            if sigma is None:
                sigma = PRIOR_VOL

            fair = call_price(spot, strike, tte, sigma)
            delta = call_delta(spot, strike, tte, sigma)
            gamma = call_gamma(spot, strike, tte, sigma)
            vega = call_vega(spot, strike, tte, sigma)
            position = int(positions.loc[ts, symbol]) if ts in positions.index and symbol in positions else 0

            gross_option_pos += abs(position)
            net_delta += position * delta
            net_gamma += position * gamma
            net_vega += position * vega

            rows.append(
                {
                    "timestamp": ts,
                    "strike": strike,
                    "symbol": symbol,
                    "spot": spot,
                    "tte_days": tte,
                    "mid": float(option_mid),
                    "iv": iv_by_strike.get(strike),
                    "sigma_used": sigma,
                    "fair": fair,
                    "edge": fair - float(option_mid),
                    "delta": delta,
                    "gamma": gamma,
                    "vega": vega,
                    "position": position,
                }
            )

        exposure_rows.append(
            {
                "timestamp": ts,
                "spot": spot,
                "tte_days": tte,
                "underlying_position": int(positions.loc[ts, ROUND_3_UNDERLYING]) if ts in positions.index and ROUND_3_UNDERLYING in positions else 0,
                "net_delta": net_delta,
                "net_gamma": net_gamma,
                "net_vega": net_vega,
                "gross_option_position": gross_option_pos,
            }
        )

    return pd.DataFrame(rows), pd.DataFrame(exposure_rows)


def _edge_summary(option_metrics: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for strike in ROUND_3_STRIKES:
        symbol_rows = option_metrics.loc[option_metrics["strike"] == strike]
        if symbol_rows.empty:
            rows.append({"strike": strike, "samples": 0})
            continue
        rows.append(
            {
                "strike": strike,
                "samples": int(len(symbol_rows)),
                "mean_iv_pct": float(symbol_rows["iv"].dropna().mean() * 100.0) if symbol_rows["iv"].notna().any() else None,
                "mean_edge": float(symbol_rows["edge"].mean()),
                "mean_abs_edge": float(symbol_rows["edge"].abs().mean()),
                "fair_gt_mid_ratio": float((symbol_rows["edge"] > 0).mean()),
                "final_position": int(symbol_rows.iloc[-1]["position"]),
            }
        )
    return rows


def _portfolio_summary(exposures: pd.DataFrame) -> dict[str, object]:
    if exposures.empty:
        return {}
    return {
        "samples": int(len(exposures)),
        "avg_abs_net_delta": float(exposures["net_delta"].abs().mean()),
        "max_abs_net_delta": float(exposures["net_delta"].abs().max()),
        "avg_abs_net_gamma": float(exposures["net_gamma"].abs().mean()),
        "max_abs_net_gamma": float(exposures["net_gamma"].abs().max()),
        "avg_abs_net_vega": float(exposures["net_vega"].abs().mean()),
        "max_abs_net_vega": float(exposures["net_vega"].abs().max()),
        "max_gross_option_position": int(exposures["gross_option_position"].max()),
    }


def _final_product_summary(activities: pd.DataFrame, positions: pd.DataFrame) -> list[dict[str, object]]:
    final = _final_rows(activities)
    rows: list[dict[str, object]] = []
    if final.empty:
        return rows

    last_ts = int(final["timestamp"].max())
    for product in ROUND_3_PRODUCTS:
        product_final = final.loc[final["product"] == product]
        if product_final.empty:
            continue
        row = product_final.iloc[0]
        position = int(positions.loc[last_ts, product]) if last_ts in positions.index and product in positions else 0
        rows.append(
            {
                "product": product,
                "kind": "option" if _option_strike(product) is not None else "delta_1",
                "mid": float(row["mid_price"]) if pd.notna(row["mid_price"]) else None,
                "pnl": float(row["profit_and_loss"]) if pd.notna(row["profit_and_loss"]) else None,
                "position": position,
            }
        )
    return rows


def _plot_equity_and_pnl(log: OfficialLog, activities: pd.DataFrame, output_dir: Path) -> Path:
    path = output_dir / "01_r3_equity_pnl.png"
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)

    if not log.graph.empty and {"timestamp", "value"}.issubset(log.graph.columns):
        axes[0].plot(log.graph["timestamp"], log.graph["value"], color="#1f77b4", lw=1.2)
        axes[0].set_title("Total official PnL curve")
        axes[0].set_xlabel("Timestamp")
        axes[0].set_ylabel("PnL")
        axes[0].grid(True, alpha=0.3)
    else:
        axes[0].text(0.5, 0.5, "No graphLog found", ha="center", va="center")
        axes[0].set_axis_off()

    final_rows = _final_rows(activities)
    if not final_rows.empty:
        final_rows = final_rows[final_rows["product"].isin(ROUND_3_PRODUCTS)].copy()
        final_rows["sort_key"] = final_rows["product"].map({product: idx for idx, product in enumerate(ROUND_3_PRODUCTS)})
        final_rows = final_rows.sort_values("sort_key")
        colors = ["#2ca02c" if value >= 0 else "#d62728" for value in final_rows["profit_and_loss"]]
        axes[1].bar(final_rows["product"], final_rows["profit_and_loss"], color=colors)
        axes[1].tick_params(axis="x", rotation=45)
        axes[1].set_title("Final PnL by product")
        axes[1].set_ylabel("PnL")
        axes[1].grid(True, alpha=0.3, axis="y")
    else:
        axes[1].text(0.5, 0.5, "No activitiesLog found", ha="center", va="center")
        axes[1].set_axis_off()

    plt.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _plot_delta_one(activities: pd.DataFrame, trades: pd.DataFrame, positions: pd.DataFrame, output_dir: Path) -> Path:
    path = output_dir / "02_r3_delta_one.png"
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
    colors = {"HYDROGEL_PACK": "#1f77b4", ROUND_3_UNDERLYING: "#ff7f0e"}

    for product in ROUND_3_DELTA_ONE:
        product_activities = activities.loc[activities["product"] == product].sort_values("timestamp")
        if product_activities.empty:
            continue
        axes[0].plot(product_activities["timestamp"], product_activities["mid_price"], label=product, lw=0.8, color=colors[product])
        axes[1].plot(product_activities["timestamp"], product_activities["profit_and_loss"], label=product, lw=0.9, color=colors[product])
        if product in positions:
            axes[2].step(positions.index, positions[product], where="post", label=product, lw=0.9, color=colors[product])

        product_trades = trades.loc[trades["symbol"] == product]
        buys = product_trades.loc[product_trades["side"] == "BUY"]
        sells = product_trades.loc[product_trades["side"] == "SELL"]
        axes[0].scatter(buys["timestamp"], buys["price"], marker="^", s=32, color="#2ca02c", alpha=0.8)
        axes[0].scatter(sells["timestamp"], sells["price"], marker="v", s=32, color="#d62728", alpha=0.8)

    axes[0].set_title("Delta-1 mid price and submission fills")
    axes[1].set_title("Official product PnL")
    axes[2].set_title("Reconstructed position from SUBMISSION trades")
    for ax in axes:
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=8)
    axes[-1].set_xlabel("Timestamp")
    plt.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _plot_option_chain(option_metrics: pd.DataFrame, output_dir: Path) -> Path:
    path = output_dir / "03_r3_option_chain.png"
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    if option_metrics.empty:
        for ax in axes.flatten():
            ax.text(0.5, 0.5, "No option metrics", ha="center", va="center")
            ax.set_axis_off()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        return path

    latest_ts = int(option_metrics["timestamp"].max())
    latest = option_metrics.loc[option_metrics["timestamp"] == latest_ts].sort_values("strike")

    axes[0, 0].plot(latest["strike"], latest["mid"], "o-", label="Market mid", color="#1f77b4")
    axes[0, 0].plot(latest["strike"], latest["fair"], "o-", label="Smile fair", color="#d62728")
    axes[0, 0].set_title(f"Final option chain price vs fair (ts={latest_ts})")
    axes[0, 0].set_ylabel("Price")
    axes[0, 0].legend()

    axes[0, 1].bar(latest["strike"].astype(str), latest["edge"], color=["#2ca02c" if x >= 0 else "#d62728" for x in latest["edge"]])
    axes[0, 1].set_title("Smile fair - market mid")
    axes[0, 1].tick_params(axis="x", rotation=45)
    axes[0, 1].set_ylabel("Ticks")

    axes[1, 0].plot(latest["strike"], latest["iv"] * 100.0, "o-", label="Own IV", color="#9467bd")
    axes[1, 0].plot(latest["strike"], latest["sigma_used"] * 100.0, "o-", label="Sigma used", color="#8c564b")
    axes[1, 0].set_title("Daily implied vol")
    axes[1, 0].set_ylabel("Vol (%)")
    axes[1, 0].legend()

    axes[1, 1].bar(latest["strike"].astype(str), latest["position"], color="#17becf")
    axes[1, 1].set_title("Final option position")
    axes[1, 1].tick_params(axis="x", rotation=45)
    axes[1, 1].set_ylabel("Position")

    for ax in axes.flatten():
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _plot_greeks(exposures: pd.DataFrame, output_dir: Path) -> Path:
    path = output_dir / "04_r3_portfolio_greeks.png"
    fig, axes = plt.subplots(4, 1, figsize=(13, 10), sharex=True)
    if exposures.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "No exposure metrics", ha="center", va="center")
            ax.set_axis_off()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        return path

    axes[0].plot(exposures["timestamp"], exposures["net_delta"], color="#1f77b4", lw=1.0)
    axes[0].axhline(0, color="black", lw=0.6)
    axes[0].set_title("Net delta: VELVETFRUIT position + option deltas")

    axes[1].plot(exposures["timestamp"], exposures["net_vega"], color="#9467bd", lw=1.0)
    axes[1].axhline(0, color="black", lw=0.6)
    axes[1].set_title("Net option vega")

    axes[2].plot(exposures["timestamp"], exposures["net_gamma"], color="#2ca02c", lw=1.0)
    axes[2].axhline(0, color="black", lw=0.6)
    axes[2].set_title("Net option gamma")

    axes[3].step(exposures["timestamp"], exposures["gross_option_position"], where="post", color="#ff7f0e", lw=1.0)
    axes[3].set_title("Gross option position")
    axes[3].set_xlabel("Timestamp")

    for ax in axes:
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _plot_iv_heatmap(option_metrics: pd.DataFrame, output_dir: Path) -> Path:
    path = output_dir / "05_r3_iv_heatmap.png"
    fig, ax = plt.subplots(figsize=(13, 5))
    if option_metrics.empty:
        ax.text(0.5, 0.5, "No option metrics", ha="center", va="center")
        ax.set_axis_off()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        return path

    heat = option_metrics.pivot_table(index="strike", columns="timestamp", values="iv", aggfunc="last")
    heat = heat.reindex(ROUND_3_STRIKES)
    values = heat.to_numpy(dtype=float) * 100.0
    im = ax.imshow(values, aspect="auto", origin="lower", cmap="viridis")
    ax.set_yticks(range(len(ROUND_3_STRIKES)))
    ax.set_yticklabels(ROUND_3_STRIKES)
    if len(heat.columns) > 0:
        tick_locs = np.linspace(0, len(heat.columns) - 1, min(8, len(heat.columns))).astype(int)
        ax.set_xticks(tick_locs)
        ax.set_xticklabels([str(int(heat.columns[i])) for i in tick_locs], rotation=45)
    ax.set_title("Daily implied vol heatmap")
    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Strike")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("IV (%)")
    plt.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _plotly_div(fig, *, div_id: str) -> str:
    import plotly.io as pio

    return pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        div_id=div_id,
        config={"responsive": True, "displaylogo": False},
    )


def _plotly_overview(log: OfficialLog, activities: pd.DataFrame):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2,
        cols=1,
        vertical_spacing=0.14,
        row_heights=[0.58, 0.42],
        subplot_titles=("Official total PnL", "Final PnL by product"),
    )

    if not log.graph.empty and {"timestamp", "value"}.issubset(log.graph.columns):
        fig.add_trace(
            go.Scatter(
                x=log.graph["timestamp"],
                y=log.graph["value"],
                mode="lines",
                name="Total PnL",
                line={"color": "#2563eb", "width": 2},
                hovertemplate="t=%{x}<br>PnL=%{y:.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    final_rows = _final_rows(activities)
    if not final_rows.empty:
        final_rows = final_rows[final_rows["product"].isin(ROUND_3_PRODUCTS)].copy()
        final_rows["sort_key"] = final_rows["product"].map({product: idx for idx, product in enumerate(ROUND_3_PRODUCTS)})
        final_rows = final_rows.sort_values("sort_key")
        colors = ["#16a34a" if float(value) >= 0 else "#dc2626" for value in final_rows["profit_and_loss"]]
        fig.add_trace(
            go.Bar(
                x=final_rows["product"],
                y=final_rows["profit_and_loss"],
                name="Product PnL",
                marker={"color": colors},
                hovertemplate="%{x}<br>PnL=%{y:.2f}<extra></extra>",
            ),
            row=2,
            col=1,
        )

    fig.update_yaxes(title_text="PnL", row=1, col=1)
    fig.update_yaxes(title_text="PnL", row=2, col=1)
    fig.update_layout(
        template="plotly_white",
        height=760,
        margin={"l": 56, "r": 28, "t": 72, "b": 80},
        showlegend=False,
    )
    return fig


def _plotly_product_review(activities: pd.DataFrame, trades: pd.DataFrame, positions: pd.DataFrame):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.055,
        row_heights=[0.52, 0.24, 0.24],
        subplot_titles=("Mid price with SUBMISSION buys/sells", "Inventory", "Official product PnL"),
    )

    products = [product for product in ROUND_3_PRODUCTS if product in set(activities["product"])]
    default_product = products[0] if products else None
    trace_ranges: dict[str, list[int]] = {}

    for product in products:
        visible = product == default_product
        start_index = len(fig.data)
        product_activities = activities.loc[activities["product"] == product].sort_values("timestamp")
        product_trades = trades.loc[trades["symbol"] == product].sort_values("timestamp")
        buys = product_trades.loc[product_trades["side"] == "BUY"]
        sells = product_trades.loc[product_trades["side"] == "SELL"]

        fig.add_trace(
            go.Scatter(
                x=product_activities["timestamp"],
                y=product_activities["mid_price"],
                mode="lines",
                name=f"{product} mid",
                visible=visible,
                line={"color": "#2563eb", "width": 1.5},
                hovertemplate="t=%{x}<br>mid=%{y:.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=buys["timestamp"],
                y=buys["price"],
                mode="markers",
                name="Buys",
                visible=visible,
                marker={"symbol": "triangle-up", "size": 11, "color": "#16a34a", "line": {"width": 1, "color": "white"}},
                text=buys["quantity"],
                hovertemplate="BUY<br>t=%{x}<br>px=%{y}<br>qty=%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=sells["timestamp"],
                y=sells["price"],
                mode="markers",
                name="Sells",
                visible=visible,
                marker={"symbol": "triangle-down", "size": 11, "color": "#dc2626", "line": {"width": 1, "color": "white"}},
                text=sells["quantity"],
                hovertemplate="SELL<br>t=%{x}<br>px=%{y}<br>qty=%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        if product in positions.columns:
            fig.add_trace(
                go.Scatter(
                    x=positions.index,
                    y=positions[product],
                    mode="lines",
                    name="Inventory",
                    visible=visible,
                    line={"shape": "hv", "color": "#7c3aed", "width": 1.6},
                    hovertemplate="t=%{x}<br>pos=%{y}<extra></extra>",
                ),
                row=2,
                col=1,
            )
        else:
            fig.add_trace(go.Scatter(x=[], y=[], visible=visible, name="Inventory"), row=2, col=1)

        fig.add_trace(
            go.Scatter(
                x=product_activities["timestamp"],
                y=product_activities["profit_and_loss"],
                mode="lines",
                name="Product PnL",
                visible=visible,
                line={"color": "#f59e0b", "width": 1.6},
                hovertemplate="t=%{x}<br>PnL=%{y:.2f}<extra></extra>",
            ),
            row=3,
            col=1,
        )
        trace_ranges[product] = list(range(start_index, len(fig.data)))

    buttons = []
    for product, indexes in trace_ranges.items():
        visible = [False] * len(fig.data)
        for index in indexes:
            visible[index] = True
        buttons.append(
            {
                "label": product,
                "method": "update",
                "args": [{"visible": visible}, {"title": {"text": f"Trade review - {product}"}}],
            }
        )

    fig.update_layout(
        template="plotly_white",
        height=920,
        title={"text": f"Trade review - {default_product or 'n/a'}"},
        margin={"l": 58, "r": 28, "t": 104, "b": 54},
        hovermode="x unified",
        updatemenus=[
            {
                "buttons": buttons,
                "direction": "down",
                "showactive": True,
                "x": 0,
                "xanchor": "left",
                "y": 1.08,
                "yanchor": "top",
            }
        ],
        legend={"orientation": "h", "y": 1.02, "x": 0.27},
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Position", row=2, col=1)
    fig.update_yaxes(title_text="PnL", row=3, col=1)
    fig.update_xaxes(title_text="Timestamp", row=3, col=1)
    return fig


def _plotly_option_chain(option_metrics: pd.DataFrame):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2,
        cols=2,
        vertical_spacing=0.15,
        horizontal_spacing=0.10,
        subplot_titles=("Market mid vs smile fair", "Fair - mid edge", "Daily IV", "Current option position"),
    )

    if not option_metrics.empty:
        latest_ts = int(option_metrics["timestamp"].max())
        latest = option_metrics.loc[option_metrics["timestamp"] == latest_ts].sort_values("strike")
        strike_labels = latest["strike"].astype(str)

        fig.add_trace(go.Scatter(x=latest["strike"], y=latest["mid"], mode="lines+markers", name="Market mid"), row=1, col=1)
        fig.add_trace(go.Scatter(x=latest["strike"], y=latest["fair"], mode="lines+markers", name="Smile fair"), row=1, col=1)
        fig.add_trace(
            go.Bar(
                x=strike_labels,
                y=latest["edge"],
                name="Edge",
                marker={"color": ["#16a34a" if value >= 0 else "#dc2626" for value in latest["edge"]]},
            ),
            row=1,
            col=2,
        )
        fig.add_trace(go.Scatter(x=latest["strike"], y=latest["iv"] * 100.0, mode="lines+markers", name="Own IV %"), row=2, col=1)
        fig.add_trace(go.Scatter(x=latest["strike"], y=latest["sigma_used"] * 100.0, mode="lines+markers", name="Sigma used %"), row=2, col=1)
        fig.add_trace(go.Bar(x=strike_labels, y=latest["position"], name="Position", marker={"color": "#0891b2"}), row=2, col=2)
        fig.update_layout(title={"text": f"Option chain snapshot - t={latest_ts}"})

    fig.update_layout(
        template="plotly_white",
        height=780,
        margin={"l": 56, "r": 28, "t": 88, "b": 58},
        legend={"orientation": "h", "y": 1.03, "x": 0},
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Ticks", row=1, col=2)
    fig.update_yaxes(title_text="IV (%)", row=2, col=1)
    fig.update_yaxes(title_text="Position", row=2, col=2)
    return fig


def _plotly_greeks(exposures: pd.DataFrame):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.055,
        subplot_titles=("Net delta", "Net vega", "Net gamma", "Gross option position"),
    )

    if not exposures.empty:
        fig.add_trace(go.Scatter(x=exposures["timestamp"], y=exposures["net_delta"], mode="lines", name="Net delta"), row=1, col=1)
        fig.add_trace(go.Scatter(x=exposures["timestamp"], y=exposures["net_vega"], mode="lines", name="Net vega"), row=2, col=1)
        fig.add_trace(go.Scatter(x=exposures["timestamp"], y=exposures["net_gamma"], mode="lines", name="Net gamma"), row=3, col=1)
        fig.add_trace(
            go.Scatter(
                x=exposures["timestamp"],
                y=exposures["gross_option_position"],
                mode="lines",
                line={"shape": "hv"},
                name="Gross option pos",
            ),
            row=4,
            col=1,
        )
        for row in [1, 2, 3]:
            fig.add_hline(y=0, line_width=1, line_color="#94a3b8", row=row, col=1)

    fig.update_layout(
        template="plotly_white",
        height=820,
        margin={"l": 64, "r": 28, "t": 76, "b": 52},
        showlegend=False,
    )
    fig.update_xaxes(title_text="Timestamp", row=4, col=1)
    return fig


def _plotly_markouts(trade_summary: list[dict[str, object]]):
    import plotly.graph_objects as go

    rows = [row for row in trade_summary if int(row.get("trade_count", 0)) > 0]
    products = [str(row["product"]) for row in rows]
    fig = go.Figure()
    for key, label, color in [
        ("markout_100", "M100", "#2563eb"),
        ("markout_500", "M500", "#7c3aed"),
        ("markout_1000", "M1000", "#f59e0b"),
    ]:
        fig.add_trace(
            go.Bar(
                x=products,
                y=[row.get(key) for row in rows],
                name=label,
                marker={"color": color},
                hovertemplate="%{x}<br>%{fullData.name}=%{y:.2f}<extra></extra>",
            )
        )
    fig.update_layout(
        template="plotly_white",
        height=480,
        barmode="group",
        title="Signed markouts from our fills",
        margin={"l": 56, "r": 28, "t": 70, "b": 90},
        legend={"orientation": "h", "y": 1.06, "x": 0},
    )
    fig.update_yaxes(title_text="Ticks / price units")
    return fig


def _plotly_iv_heatmap(option_metrics: pd.DataFrame):
    import plotly.graph_objects as go

    if option_metrics.empty:
        return go.Figure()
    heat = option_metrics.pivot_table(index="strike", columns="timestamp", values="iv", aggfunc="last")
    heat = heat.reindex(ROUND_3_STRIKES)
    fig = go.Figure(
        data=[
            go.Heatmap(
                z=heat.to_numpy(dtype=float) * 100.0,
                x=[int(column) for column in heat.columns],
                y=[str(strike) for strike in heat.index],
                colorscale="Viridis",
                colorbar={"title": "IV %"},
                hovertemplate="t=%{x}<br>K=%{y}<br>IV=%{z:.3f}%<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        template="plotly_white",
        height=520,
        title="Implied volatility heatmap",
        margin={"l": 64, "r": 28, "t": 70, "b": 58},
    )
    fig.update_xaxes(title_text="Timestamp")
    fig.update_yaxes(title_text="Strike")
    return fig


def _html_summary_cards(payload: dict[str, object]) -> str:
    portfolio = payload.get("portfolio_summary", {})
    final_total = sum(float(row.get("pnl") or 0.0) for row in payload.get("final_products", []))
    cards = [
        ("Official Profit", _fmt(payload.get("profit"), 2)),
        ("Product PnL Sum", _fmt(final_total, 2)),
        ("Avg Abs Delta", _fmt(portfolio.get("avg_abs_net_delta"), 2)),
        ("Max Abs Delta", _fmt(portfolio.get("max_abs_net_delta"), 2)),
        ("Max Option Pos", _fmt(portfolio.get("max_gross_option_position"))),
    ]
    return "\n".join(
        f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>'
        for label, value in cards
    )


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    header_html = "".join(f"<th>{header}</th>" for header in headers)
    row_html = "\n".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{row_html}</tbody></table>"


def _write_html_report(
    payload: dict[str, object],
    log: OfficialLog,
    activities: pd.DataFrame,
    trades: pd.DataFrame,
    option_metrics: pd.DataFrame,
    exposures: pd.DataFrame,
    output_path: Path,
) -> None:
    from plotly.offline import get_plotlyjs

    output_path.parent.mkdir(parents=True, exist_ok=True)

    trade_summary = payload.get("trade_summary", [])
    final_products = payload.get("final_products", [])
    positions = _position_matrix(_pivot_activities(activities, "mid_price").index, trades)

    figures = [
        ("overview", _plotly_overview(log, activities)),
        ("product-review", _plotly_product_review(activities, trades, positions)),
        ("option-chain", _plotly_option_chain(option_metrics)),
        ("greeks", _plotly_greeks(exposures)),
        ("markouts", _plotly_markouts(trade_summary)),
        ("iv-heatmap", _plotly_iv_heatmap(option_metrics)),
    ]

    final_table = _html_table(
        ["Product", "Kind", "PnL", "Mid", "Position"],
        [
            [
                str(row.get("product")),
                str(row.get("kind")),
                _fmt(row.get("pnl"), 2),
                _fmt(row.get("mid"), 2),
                _fmt(row.get("position")),
            ]
            for row in final_products
        ],
    )
    trade_table = _html_table(
        ["Product", "Trades", "Buy", "Sell", "Net", "M100", "M500", "M1000"],
        [
            [
                str(row.get("product")),
                _fmt(row.get("trade_count")),
                _fmt(row.get("buy_qty")),
                _fmt(row.get("sell_qty")),
                _fmt(row.get("net_qty")),
                _fmt(row.get("markout_100"), 2),
                _fmt(row.get("markout_500"), 2),
                _fmt(row.get("markout_1000"), 2),
            ]
            for row in trade_summary
            if int(row.get("trade_count", 0)) > 0
        ],
    )

    figure_html = "\n".join(
        f'<section class="panel"><h2>{title}</h2>{_plotly_div(fig, div_id=f"r3-{div_id}")}</section>'
        for div_id, title, fig in [
            ("overview", "Overview", figures[0][1]),
            ("product-review", "Trades, Inventory, PnL", figures[1][1]),
            ("option-chain", "Option Chain", figures[2][1]),
            ("greeks", "Portfolio Greeks", figures[3][1]),
            ("markouts", "Fill Markouts", figures[4][1]),
            ("iv-heatmap", "IV Heatmap", figures[5][1]),
        ]
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Round 3 Log Analysis - {payload.get('submission_id')}</title>
  <script>{get_plotlyjs()}</script>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #172033;
      --muted: #64748b;
      --border: #d9e0ea;
      --shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .page {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 22px 18px 34px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 18px;
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      line-height: 1.1;
    }}
    .subtitle {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 12px;
      margin: 16px 0 18px;
    }}
    .metric-card, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      box-shadow: var(--shadow);
      border-radius: 10px;
    }}
    .metric-card {{
      padding: 14px 16px;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .metric-value {{
      margin-top: 6px;
      font-size: 24px;
      font-weight: 760;
    }}
    .panel {{
      padding: 16px;
      margin: 14px 0;
      overflow: hidden;
    }}
    .tables {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    th, td {{
      border-bottom: 1px solid #e6ebf2;
      padding: 7px 8px;
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child,
    th:nth-child(2), td:nth-child(2) {{
      text-align: left;
    }}
    th {{
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    @media (max-width: 1100px) {{
      .cards {{ grid-template-columns: repeat(2, minmax(150px, 1fr)); }}
      .tables {{ grid-template-columns: 1fr; }}
      header {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div>
        <h1>Round 3 Log Analysis</h1>
        <div class="subtitle">
          Submission <code>{payload.get('submission_id')}</code><br>
          Source <code>{payload.get('source_path')}</code> | Loaded <code>{", ".join(payload.get('loaded_paths', []))}</code>
        </div>
      </div>
      <div class="subtitle">Status <strong>{payload.get('status')}</strong> | Round <strong>{payload.get('round')}</strong></div>
    </header>
    <section class="cards">
      {_html_summary_cards(payload)}
    </section>
    <section class="tables">
      <div class="panel"><h2>Final Products</h2>{final_table}</div>
      <div class="panel"><h2>Submission Trades</h2>{trade_table}</div>
    </section>
    {figure_html}
  </main>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def _write_markdown(payload: dict[str, object], output_path: Path) -> None:
    final_rows = payload.get("final_products", [])
    trade_rows = payload.get("trade_summary", [])
    edge_rows = payload.get("edge_summary", [])
    portfolio = payload.get("portfolio_summary", {})

    lines = [
        f"# Round 3 Log Analysis - {payload.get('submission_id', 'unknown')}",
        "",
        f"Source: `{payload.get('source_path')}`",
        f"Loaded: `{', '.join(payload.get('loaded_paths', []))}`",
        f"Status: `{payload.get('status')}`  |  Round: `{payload.get('round')}`  |  Final profit: `{_fmt(payload.get('profit'), 2)}`",
        "",
        "## Final Products",
        _markdown_table(
            ["Product", "Kind", "PnL", "Mid", "Position"],
            [
                [
                    str(row.get("product")),
                    str(row.get("kind")),
                    _fmt(row.get("pnl"), 2),
                    _fmt(row.get("mid"), 2),
                    _fmt(row.get("position")),
                ]
                for row in final_rows
            ],
        ),
        "",
        "## Submission Trades",
        _markdown_table(
            ["Product", "Trades", "Buy Qty", "Sell Qty", "Net Qty", "M100", "M500", "M1000"],
            [
                [
                    str(row.get("product")),
                    _fmt(row.get("trade_count")),
                    _fmt(row.get("buy_qty")),
                    _fmt(row.get("sell_qty")),
                    _fmt(row.get("net_qty")),
                    _fmt(row.get("markout_100"), 2),
                    _fmt(row.get("markout_500"), 2),
                    _fmt(row.get("markout_1000"), 2),
                ]
                for row in trade_rows
                if int(row.get("trade_count", 0)) > 0
            ],
        ),
        "",
        "## Option Edge Summary",
        _markdown_table(
            ["Strike", "Samples", "Mean IV %", "Mean Edge", "Mean Abs Edge", "Fair > Mid", "Final Pos"],
            [
                [
                    _fmt(row.get("strike")),
                    _fmt(row.get("samples")),
                    _fmt(row.get("mean_iv_pct"), 3),
                    _fmt(row.get("mean_edge"), 3),
                    _fmt(row.get("mean_abs_edge"), 3),
                    _fmt(row.get("fair_gt_mid_ratio"), 3),
                    _fmt(row.get("final_position")),
                ]
                for row in edge_rows
            ],
        ),
        "",
        "## Portfolio Greeks",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Samples", _fmt(portfolio.get("samples"))],
                ["Avg abs net delta", _fmt(portfolio.get("avg_abs_net_delta"), 2)],
                ["Max abs net delta", _fmt(portfolio.get("max_abs_net_delta"), 2)],
                ["Avg abs net gamma", _fmt(portfolio.get("avg_abs_net_gamma"), 4)],
                ["Max abs net gamma", _fmt(portfolio.get("max_abs_net_gamma"), 4)],
                ["Avg abs net vega", _fmt(portfolio.get("avg_abs_net_vega"), 2)],
                ["Max abs net vega", _fmt(portfolio.get("max_abs_net_vega"), 2)],
                ["Max gross option position", _fmt(portfolio.get("max_gross_option_position"))],
            ],
        ),
        "",
        "## Generated Plots",
    ]
    for plot_path in payload.get("plots", []):
        lines.append(f"- `{plot_path}`")
    lines.append("")
    lines.append("Notes:")
    lines.append("- TTE uses the live Round 3 convention: 5.0 days at timestamp 0.")
    lines.append("- Smile fair values use a quadratic fit in log-moneyness when at least 3 valid IV points are available.")
    lines.append("- Markouts are signed from the submission perspective: positive means the fill moved in our favor.")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def analyze_round3_log(
    log_path: str | Path,
    *,
    outdir: str | Path = "artifacts/analysis/round_3_logs",
    group: str | None = None,
    sample_step: int = 100,
    make_plots: bool = False,
    make_html: bool = True,
    write_sidecars: bool = False,
) -> dict[str, object]:
    log = load_official_log(log_path)
    activities = _activities_for_round3(log)
    trades = _submission_trades(log)
    marked_trades = _trade_markouts(activities, trades)
    mid = _pivot_activities(activities, "mid_price")
    positions = _position_matrix(mid.index, trades)
    option_metrics, exposures = _option_metrics(mid, positions, max(100, int(sample_step)))

    group_name = group or log.analysis_group
    output_dir = Path(outdir) / group_name
    output_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "submission_id": log.submission_id,
        "source_path": str(log.source_path),
        "loaded_paths": [str(path) for path in log.loaded_paths],
        "status": log.status,
        "round": log.round_label,
        "profit": log.profit,
        "final_products": _final_product_summary(activities, positions),
        "trade_summary": _trade_summary(trades, marked_trades),
        "edge_summary": _edge_summary(option_metrics),
        "portfolio_summary": _portfolio_summary(exposures),
        "plots": [],
    }

    if make_plots:
        plot_paths = [
            _plot_equity_and_pnl(log, activities, output_dir),
            _plot_delta_one(activities, trades, positions, output_dir),
            _plot_option_chain(option_metrics, output_dir),
            _plot_greeks(exposures, output_dir),
            _plot_iv_heatmap(option_metrics, output_dir),
        ]
        payload["plots"] = [str(path) for path in plot_paths]

    if make_html:
        html_path = output_dir / f"{log.submission_id}_r3_report.html"
        _write_html_report(payload, log, activities, trades, option_metrics, exposures, html_path)
        payload["html_path"] = str(html_path)

    if write_sidecars:
        json_path = output_dir / f"{log.submission_id}_r3_analysis.json"
        md_path = output_dir / f"{log.submission_id}_r3_analysis.md"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _write_markdown(payload, md_path)
        payload["json_path"] = str(json_path)
        payload["markdown_path"] = str(md_path)
    return payload


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Round 3 official logs with option-aware diagnostics")
    parser.add_argument("--log", required=True, help="Path to an official Round 3 JSON or LOG file")
    parser.add_argument("--outdir", default="artifacts/analysis/round_3_logs")
    parser.add_argument("--group", default=None, help="Subfolder under --outdir; defaults to the log analysis group")
    parser.add_argument("--sample-step", type=int, default=100, help="Timestamp sampling step for option metrics")
    parser.add_argument("--png", "--png-plots", dest="png_plots", action="store_true", help="Also write the legacy static PNG plots")
    parser.add_argument("--no-plots", action="store_true", help="Do not write legacy static PNG plots")
    parser.add_argument("--no-html", action="store_true", help="Do not write the single-file Plotly HTML report")
    parser.add_argument("--sidecars", action="store_true", help="Also write JSON/Markdown sidecar summaries")
    parser.add_argument("--symbol", action="append", help="Accepted for compatibility; Round 3 analysis always uses all products")
    parser.add_argument("--edge", type=float, default=1.0, help="Accepted for compatibility with scripts/analyze_log.py")
    parser.add_argument("--plotly", action="store_true", help="Accepted for compatibility; Round 3 output is static PNG")
    parser.add_argument("--backtest-json", help="Accepted for compatibility; not used by the Round 3 log analyzer")
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = analyze_round3_log(
        args.log,
        outdir=args.outdir,
        group=args.group,
        sample_step=args.sample_step,
        make_plots=args.png_plots and not args.no_plots,
        make_html=not args.no_html,
        write_sidecars=args.sidecars,
    )

    portfolio = payload.get("portfolio_summary", {})
    final_total = sum(
        float(row.get("pnl") or 0.0)
        for row in payload.get("final_products", [])
    )
    if payload.get("html_path"):
        print(f"Wrote {payload['html_path']}")
    if payload.get("markdown_path"):
        print(f"Wrote {payload['markdown_path']}")
    if payload.get("json_path"):
        print(f"Wrote {payload['json_path']}")
    print(
        "Round 3 summary: "
        f"official_profit={_fmt(payload.get('profit'), 2)}, "
        f"sum_product_pnl={_fmt(final_total, 2)}, "
        f"avg_abs_delta={_fmt(portfolio.get('avg_abs_net_delta'), 2)}, "
        f"max_abs_delta={_fmt(portfolio.get('max_abs_net_delta'), 2)}, "
        f"max_gross_option_pos={_fmt(portfolio.get('max_gross_option_position'))}"
    )
    for plot_path in payload.get("plots", []):
        print(f"saved {plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
