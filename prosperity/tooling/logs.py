from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd

from prosperity.tooling.data import dataframe_from_semicolon_text


@dataclass
class OfficialLog:
    source_path: Path
    payload: dict
    activities: pd.DataFrame
    trades: pd.DataFrame
    graph: pd.DataFrame

    @property
    def submission_id(self) -> str:
        return str(self.payload.get("submissionId") or self.payload.get("round") or self.source_path.stem)

    @property
    def profit(self) -> float | None:
        profit = self.payload.get("profit")
        return float(profit) if profit is not None else None


def load_official_log(path: str | Path) -> OfficialLog:
    log_path = Path(path)
    payload = json.loads(log_path.read_text(encoding="utf-8"))

    activities = dataframe_from_semicolon_text(payload.get("activitiesLog", ""))
    trades = pd.DataFrame(payload.get("trades") or payload.get("tradeHistory") or [])
    graph = dataframe_from_semicolon_text(payload.get("graphLog", ""))

    for frame in (activities, trades, graph):
        if "timestamp" in frame.columns:
            frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce").fillna(0).astype(int)

    return OfficialLog(
        source_path=log_path,
        payload=payload,
        activities=activities,
        trades=trades,
        graph=graph,
    )


def _submission_trades(trades: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if trades.empty:
        return trades
    buyer_submission = trades.get("buyer", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    seller_submission = trades.get("seller", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    mask = (trades["symbol"] == symbol) & (buyer_submission | seller_submission)
    filtered = trades.loc[mask].copy()
    if filtered.empty:
        return filtered
    filtered["side"] = filtered["buyer"].fillna("").eq("SUBMISSION").map({True: "BUY", False: "SELL"})
    filtered["signed_quantity"] = filtered["quantity"] * filtered["side"].map({"BUY": 1, "SELL": -1})
    return filtered.sort_values("timestamp")


def _compute_activity_features(activities: pd.DataFrame) -> pd.DataFrame:
    features = activities.copy()
    features["microprice"] = (
        features["bid_price_1"] * features["ask_volume_1"] + features["ask_price_1"] * features["bid_volume_1"]
    ) / (features["bid_volume_1"] + features["ask_volume_1"]).clip(lower=1)
    features["fair"] = features["microprice"].ewm(span=25, adjust=False).mean()
    features["spread"] = features["ask_price_1"] - features["bid_price_1"]
    return features


def plot_symbol_review(log: OfficialLog, symbol: str, output_dir: str | Path, edge: float = 1.0) -> Path:
    symbol_activities = log.activities.loc[log.activities["product"] == symbol].copy()
    if symbol_activities.empty:
        raise ValueError(f"No activity rows found for product {symbol}")

    symbol_activities = _compute_activity_features(symbol_activities.sort_values("timestamp"))
    symbol_trades = _submission_trades(log.trades, symbol)

    buy_opportunities = symbol_activities["ask_price_1"] <= symbol_activities["fair"] - edge
    sell_opportunities = symbol_activities["bid_price_1"] >= symbol_activities["fair"] + edge

    figure, (price_ax, exec_ax) = plt.subplots(
        2,
        1,
        figsize=(16, 10),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    price_ax.plot(symbol_activities["timestamp"], symbol_activities["bid_price_1"], label="Best bid", color="#0b7285")
    price_ax.plot(symbol_activities["timestamp"], symbol_activities["ask_price_1"], label="Best ask", color="#c92a2a")
    price_ax.plot(symbol_activities["timestamp"], symbol_activities["fair"], label="Fair value (EWM microprice)", color="#2b8a3e")

    price_ax.scatter(
        symbol_activities.loc[buy_opportunities, "timestamp"],
        symbol_activities.loc[buy_opportunities, "ask_price_1"],
        label="Buy opportunities",
        s=18,
        color="#74c69d",
        alpha=0.35,
    )
    price_ax.scatter(
        symbol_activities.loc[sell_opportunities, "timestamp"],
        symbol_activities.loc[sell_opportunities, "bid_price_1"],
        label="Sell opportunities",
        s=18,
        color="#ff8787",
        alpha=0.35,
    )

    if not symbol_trades.empty:
        size_scale = symbol_trades["quantity"].clip(lower=1) * 18
        buy_trades = symbol_trades.loc[symbol_trades["side"] == "BUY"]
        sell_trades = symbol_trades.loc[symbol_trades["side"] == "SELL"]

        price_ax.scatter(
            buy_trades["timestamp"],
            buy_trades["price"],
            s=size_scale.loc[buy_trades.index],
            marker="^",
            color="#2f9e44",
            label="Submission buys",
            edgecolors="black",
            linewidths=0.3,
        )
        price_ax.scatter(
            sell_trades["timestamp"],
            sell_trades["price"],
            s=size_scale.loc[sell_trades.index],
            marker="v",
            color="#f03e3e",
            label="Submission sells",
            edgecolors="black",
            linewidths=0.3,
        )

        exec_colors = symbol_trades["side"].map({"BUY": "#2f9e44", "SELL": "#f03e3e"})
        exec_ax.bar(
            symbol_trades["timestamp"],
            symbol_trades["signed_quantity"],
            width=120,
            color=exec_colors,
            alpha=0.65,
            label="Signed execution quantity",
        )

    if not log.graph.empty:
        pnl_ax = exec_ax.twinx()
        pnl_ax.plot(log.graph["timestamp"], log.graph["value"], color="#495057", label="PnL graph", linewidth=1.4)
        pnl_ax.set_ylabel("PnL")
        pnl_ax.legend(loc="upper right")

    price_ax.set_title(f"{symbol} price path, trades, and opportunity markers")
    price_ax.set_ylabel("Price")
    price_ax.legend(loc="upper left", ncol=2)
    price_ax.grid(alpha=0.2)

    exec_ax.axhline(0, color="#adb5bd", linewidth=1)
    exec_ax.set_ylabel("Signed qty")
    exec_ax.set_xlabel("Timestamp")
    exec_ax.grid(alpha=0.15)

    output_path = Path(output_dir) / f"{log.submission_id}_{symbol}_review.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return output_path


def summarize_log(log: OfficialLog) -> str:
    buyer_submission = log.trades.get("buyer", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    seller_submission = log.trades.get("seller", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    submission_trades = log.trades.loc[buyer_submission | seller_submission].copy()

    if submission_trades.empty:
        return f"submission={log.submission_id} final_profit={log.profit} trade_count=0"

    traded_volume = int(submission_trades["quantity"].sum())
    per_symbol = submission_trades.groupby("symbol")["quantity"].agg(["count", "sum"]).to_dict("index")
    return (
        f"submission={log.submission_id} final_profit={log.profit} trade_count={len(submission_trades)} "
        f"traded_volume={traded_volume} per_symbol={per_symbol}"
    )


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Prosperity official JSON logs")
    parser.add_argument("--log", required=True, help="Path to the official JSON log")
    parser.add_argument("--symbol", action="append", help="Product symbol to plot, can be passed multiple times")
    parser.add_argument("--outdir", default="artifacts/analysis", help="Directory that will receive generated plots")
    parser.add_argument("--edge", type=float, default=1.0, help="Opportunity threshold around fair value")
    args = parser.parse_args(list(argv) if argv is not None else None)

    log = load_official_log(args.log)
    symbols = args.symbol or sorted(log.activities["product"].dropna().unique())

    print(summarize_log(log))
    for symbol in symbols:
        output_path = plot_symbol_review(log, symbol, args.outdir, edge=args.edge)
        print(f"saved {output_path}")

    return 0
