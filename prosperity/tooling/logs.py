from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd

from prosperity.tooling.data import dataframe_from_semicolon_text


def _read_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _payload_kind(payload: dict) -> str:
    if any(key in payload for key in ("profit", "status", "graphLog", "positions", "round")):
        return "summary"
    if any(key in payload for key in ("tradeHistory", "logs", "submissionId")):
        return "detail"
    return "generic"


def _discover_companion(path: Path) -> tuple[Path | None, dict | None]:
    for suffix in (".json", ".log"):
        candidate = path.with_suffix(suffix)
        if candidate == path or not candidate.exists():
            continue
        try:
            return candidate, _read_payload(candidate)
        except Exception:
            continue
    return None, None


def _discover_python_companion(path: Path) -> Path | None:
    candidate = path.with_suffix(".py")
    return candidate if candidate.exists() else None


def _normalize_numeric_columns(frame: pd.DataFrame, integer_columns: set[str] | None = None) -> pd.DataFrame:
    if frame.empty:
        return frame

    normalized = frame.copy()
    integer_columns = integer_columns or set()
    for column in normalized.columns:
        if column == "timestamp" or column in integer_columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0).astype(int)
        elif column in {"price", "value"}:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        elif column == "quantity":
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0).astype(int)
    return normalized


@dataclass
class OfficialLog:
    source_path: Path
    payload: dict
    summary_payload: dict | None
    detail_payload: dict | None
    companion_path: Path | None
    submission_source_path: Path | None
    activities: pd.DataFrame
    trades: pd.DataFrame
    graph: pd.DataFrame
    positions: pd.DataFrame
    runtime_logs: pd.DataFrame

    @property
    def submission_id(self) -> str:
        return str(self.payload.get("submissionId") or self.payload.get("round") or self.source_path.stem)

    @property
    def profit(self) -> float | None:
        profit = self.payload.get("profit")
        return float(profit) if profit is not None else None

    @property
    def status(self) -> str | None:
        status = self.payload.get("status")
        return str(status) if status is not None else None

    @property
    def round_label(self) -> str | None:
        round_value = self.payload.get("round")
        return str(round_value) if round_value is not None else None

    @property
    def loaded_paths(self) -> list[Path]:
        paths = [self.source_path]
        if self.companion_path is not None:
            paths.append(self.companion_path)
        if self.submission_source_path is not None:
            paths.append(self.submission_source_path)
        return paths

    @property
    def analysis_group(self) -> str:
        parent_name = self.source_path.parent.name.strip()
        if parent_name and parent_name.lower() not in {"official_logs", "analysis", "artifacts", "examples"}:
            return parent_name

        if self.submission_source_path is not None:
            stem = self.submission_source_path.stem.strip()
            if stem and not stem.isdigit():
                return stem

        return self.source_path.stem


def load_official_log(path: str | Path) -> OfficialLog:
    log_path = Path(path)
    primary_payload = _read_payload(log_path)
    companion_path, companion_payload = _discover_companion(log_path)
    submission_source_path = _discover_python_companion(log_path)

    payloads = [payload for payload in (primary_payload, companion_payload) if payload is not None]
    kinds = [(_payload_kind(payload), payload) for payload in payloads]

    summary_payload = next((payload for kind, payload in kinds if kind == "summary"), None)
    detail_payload = next((payload for kind, payload in kinds if kind == "detail"), None)

    if summary_payload is None:
        summary_payload = primary_payload
    if detail_payload is None and primary_payload is not summary_payload:
        detail_payload = primary_payload

    merged_payload = {}
    if detail_payload is not None:
        merged_payload.update(detail_payload)
    if summary_payload is not None:
        merged_payload.update(summary_payload)

    activities_text = (
        (summary_payload or {}).get("activitiesLog")
        or (detail_payload or {}).get("activitiesLog")
        or ""
    )
    graph_text = (
        (summary_payload or {}).get("graphLog")
        or (detail_payload or {}).get("graphLog")
        or ""
    )
    trade_rows = (
        (detail_payload or {}).get("trades")
        or (detail_payload or {}).get("tradeHistory")
        or (summary_payload or {}).get("trades")
        or (summary_payload or {}).get("tradeHistory")
        or []
    )
    positions_rows = (
        (summary_payload or {}).get("positions")
        or (detail_payload or {}).get("positions")
        or []
    )
    runtime_log_rows = (
        (detail_payload or {}).get("logs")
        or (summary_payload or {}).get("logs")
        or []
    )

    activities = _normalize_numeric_columns(dataframe_from_semicolon_text(activities_text))
    trades = _normalize_numeric_columns(pd.DataFrame(trade_rows))
    graph = _normalize_numeric_columns(dataframe_from_semicolon_text(graph_text))
    positions = _normalize_numeric_columns(pd.DataFrame(positions_rows), integer_columns={"quantity"})
    runtime_logs = _normalize_numeric_columns(pd.DataFrame(runtime_log_rows))

    return OfficialLog(
        source_path=log_path,
        payload=merged_payload,
        summary_payload=summary_payload,
        detail_payload=detail_payload,
        companion_path=companion_path,
        submission_source_path=submission_source_path,
        activities=activities,
        trades=trades,
        graph=graph,
        positions=positions,
        runtime_logs=runtime_logs,
    )


def _parse_lambda_logs(runtime_logs: pd.DataFrame) -> pd.DataFrame:
    """Extract strategy log entries printed via json.dumps from lambdaLog fields.

    Each flush produces one JSON object per product per chunk:
      {"product": "EMERALDS", "chunk_end": 49900, "log": [[ts, reservation, bid, ask], ...]}

    Multiple products printing at the same timestamp are concatenated by IMC
    into a single lambdaLog string (with or without newlines), so we use
    raw_decode to walk through back-to-back JSON objects robustly.
    """
    decoder = json.JSONDecoder()
    rows = []
    for _, entry in runtime_logs.iterrows():
        text = str(entry.get("lambdaLog", "") or "").strip()
        if not text:
            continue
        pos = 0
        while pos < len(text):
            # Skip whitespace / newlines between objects
            while pos < len(text) and text[pos] in " \t\r\n":
                pos += 1
            if pos >= len(text):
                break
            try:
                obj, consumed = decoder.raw_decode(text, pos)
                pos += consumed
            except json.JSONDecodeError:
                # Not valid JSON at this position — skip to next '{'
                next_brace = text.find("{", pos + 1)
                if next_brace == -1:
                    break
                pos = next_brace
                continue
            if not isinstance(obj, dict):
                continue
            product = obj.get("product")
            if not product:
                continue
            for tick in obj.get("log", []):
                if len(tick) == 3:
                    # Format: [timestamp, bid_price, ask_price] (no reservation)
                    rows.append({
                        "timestamp": int(tick[0]),
                        "product": product,
                        "reservation": None,
                        "bid_price": int(tick[1]),
                        "ask_price": int(tick[2]),
                    })
                elif len(tick) >= 4:
                    # Format: [timestamp, reservation, bid_price, ask_price]
                    rows.append({
                        "timestamp": int(tick[0]),
                        "product": product,
                        "reservation": float(tick[1]),
                        "bid_price": int(tick[2]),
                        "ask_price": int(tick[3]),
                    })
    if not rows:
        return pd.DataFrame(columns=["timestamp", "product", "reservation", "bid_price", "ask_price"])
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


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

    output_path = Path(output_dir) / log.analysis_group / f"{log.submission_id}_{symbol}_review.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return output_path


def summarize_log(log: OfficialLog) -> str:
    buyer_submission = log.trades.get("buyer", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    seller_submission = log.trades.get("seller", pd.Series(dtype=str)).fillna("") == "SUBMISSION"
    submission_trades = log.trades.loc[buyer_submission | seller_submission].copy()

    prefix = (
        f"submission={log.submission_id} final_profit={log.profit} status={log.status} "
        f"loaded={[path.name for path in log.loaded_paths]}"
    )

    if submission_trades.empty:
        return f"{prefix} trade_count=0"

    traded_volume = int(submission_trades["quantity"].sum())
    per_symbol = submission_trades.groupby("symbol")["quantity"].agg(["count", "sum"]).to_dict("index")
    return (
        f"{prefix} trade_count={len(submission_trades)} "
        f"traded_volume={traded_volume} per_symbol={per_symbol}"
    )


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Prosperity official JSON / LOG files")
    parser.add_argument("--log", required=True, help="Path to an official JSON or LOG file")
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
