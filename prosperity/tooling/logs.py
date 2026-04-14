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
      {"product": "EMERALDS", "chunk_end": 49900, "log": [[...], ...]}

    Supported per-tick formats currently seen in the repo:
      [timestamp, bid, ask]
      [timestamp, reservation, bid, ask]
      [timestamp, bid, ask, extra_1, extra_2, ...]

    Multiple products printing at the same timestamp are concatenated by IMC
    into a single lambdaLog string (with or without newlines), so we use
    raw_decode to walk through back-to-back JSON objects robustly.
    """
    decoder = json.JSONDecoder()
    rows = []

    def _append_quote_row(product: str, tick: list[object], columns: list[object] | None = None) -> None:
        if len(tick) < 3:
            return

        if columns:
            normalized_columns = [str(column) for column in columns]
            mapped = {
                name: (tick[index] if index < len(tick) else None)
                for index, name in enumerate(normalized_columns)
            }

            timestamp = mapped.get("timestamp")
            bid_price = mapped.get("bid_price", mapped.get("bid"))
            ask_price = mapped.get("ask_price", mapped.get("ask"))
            reservation = mapped.get("reservation")

            if timestamp is None or bid_price is None or ask_price is None:
                return

            row = {
                "timestamp": int(float(timestamp)),
                "product": product,
                "reservation": float(reservation) if reservation is not None else None,
                "bid_price": int(float(bid_price)),
                "ask_price": int(float(ask_price)),
            }
            for key, value in mapped.items():
                if key in {"timestamp", "bid", "ask", "bid_price", "ask_price", "reservation"}:
                    continue
                row[key] = value
            rows.append(row)
            return

        timestamp = int(tick[0])
        reservation = None
        bid_price = None
        ask_price = None

        if len(tick) == 3:
            bid_price = tick[1]
            ask_price = tick[2]
        else:
            try:
                maybe_reservation = float(tick[1]) if tick[1] is not None else None
                maybe_bid = float(tick[2]) if tick[2] is not None else None
                maybe_ask = float(tick[3]) if tick[3] is not None else None
            except (TypeError, ValueError):
                maybe_reservation = maybe_bid = maybe_ask = None

            if (
                maybe_reservation is not None
                and maybe_bid is not None
                and maybe_ask is not None
                and maybe_bid <= maybe_reservation <= maybe_ask
            ):
                reservation = maybe_reservation
                bid_price = tick[2]
                ask_price = tick[3]
            else:
                bid_price = tick[1]
                ask_price = tick[2]

        if bid_price is None or ask_price is None:
            return

        rows.append({
            "timestamp": timestamp,
            "product": product,
            "reservation": float(reservation) if reservation is not None else None,
            "bid_price": int(bid_price),
            "ask_price": int(ask_price),
        })

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
            trace = obj.get("trace")
            if trace is not None and trace != "quote_trace":
                continue
            columns = obj.get("columns")
            for tick in obj.get("log", []):
                _append_quote_row(product, tick, columns if isinstance(columns, list) else None)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "product", "reservation", "bid_price", "ask_price"])
    frame = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    base_columns = ["timestamp", "product", "reservation", "bid_price", "ask_price"]
    extra_columns = [column for column in frame.columns if column not in base_columns]
    return frame[base_columns + extra_columns]


def _parse_taker_fills(runtime_logs: pd.DataFrame) -> pd.DataFrame:
    """Extract taker fill entries logged by log_taker_fill (trace='taker_fills').

    Returns DataFrame with columns: timestamp, product, side, price, quantity.
    Note: timestamps here are the detection tick (T+1), not the execution tick (T).
    """
    decoder = json.JSONDecoder()
    rows = []
    for _, entry in runtime_logs.iterrows():
        text = str(entry.get("lambdaLog", "") or "").strip()
        if not text:
            continue
        pos = 0
        while pos < len(text):
            while pos < len(text) and text[pos] in " \t\r\n":
                pos += 1
            if pos >= len(text):
                break
            try:
                obj, consumed = decoder.raw_decode(text, pos)
                pos += consumed
            except json.JSONDecodeError:
                next_brace = text.find("{", pos + 1)
                if next_brace == -1:
                    break
                pos = next_brace
                continue
            if not isinstance(obj, dict) or obj.get("trace") != "taker_fills":
                continue
            product = obj.get("product")
            if not product:
                continue
            for tick in obj.get("log", []):
                if len(tick) < 4:
                    continue
                try:
                    rows.append({
                        "timestamp": int(tick[0]),
                        "product": product,
                        "side": str(tick[1]).upper(),
                        "price": int(tick[2]),
                        "quantity": int(tick[3]),
                    })
                except (TypeError, ValueError):
                    continue
    if not rows:
        return pd.DataFrame(columns=["timestamp", "product", "side", "price", "quantity"])
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


def official_position_path(log: OfficialLog, symbol: str) -> pd.DataFrame:
    submission_trades = _submission_trades(log.trades, symbol)
    if submission_trades.empty:
        return pd.DataFrame(columns=["timestamp", "position"])
    frame = submission_trades.sort_values("timestamp").copy()
    frame["position"] = frame["signed_quantity"].cumsum()
    return frame[["timestamp", "position"]]


def _compute_activity_features(activities: pd.DataFrame) -> pd.DataFrame:
    features = activities.copy()
    features["microprice"] = (
        features["bid_price_1"] * features["ask_volume_1"] + features["ask_price_1"] * features["bid_volume_1"]
    ) / (features["bid_volume_1"] + features["ask_volume_1"]).clip(lower=1)
    features["fair"] = features["microprice"].ewm(span=25, adjust=False).mean()
    features["spread"] = features["ask_price_1"] - features["bid_price_1"]
    return features


def official_quote_summary(log: OfficialLog, symbol: str) -> dict:
    lambda_df = _parse_lambda_logs(log.runtime_logs)
    lambda_sym = lambda_df[lambda_df["product"] == symbol].copy() if not lambda_df.empty else pd.DataFrame()
    submission_trades = _submission_trades(log.trades, symbol)

    if lambda_sym.empty:
        return {
            "symbol": symbol,
            "quoted_tick_count": 0,
            "bid_quote_ticks": 0,
            "ask_quote_ticks": 0,
            "avg_quoted_spread": None,
            "buy_fill_count": int((submission_trades.get("side", pd.Series(dtype=str)) == "BUY").sum()) if not submission_trades.empty else 0,
            "sell_fill_count": int((submission_trades.get("side", pd.Series(dtype=str)) == "SELL").sum()) if not submission_trades.empty else 0,
            "buy_filled_qty": int(submission_trades.loc[submission_trades.get("side", pd.Series(dtype=str)) == "BUY", "quantity"].sum()) if not submission_trades.empty else 0,
            "sell_filled_qty": int(submission_trades.loc[submission_trades.get("side", pd.Series(dtype=str)) == "SELL", "quantity"].sum()) if not submission_trades.empty else 0,
            "buy_fill_rate_per_tick": None,
            "sell_fill_rate_per_tick": None,
            "buy_qty_per_tick": None,
            "sell_qty_per_tick": None,
        }

    lambda_sym = lambda_sym.sort_values("timestamp").copy()
    spread_series = (lambda_sym["ask_price"] - lambda_sym["bid_price"]).where(
        lambda_sym["ask_price"].notna() & lambda_sym["bid_price"].notna()
    )
    bid_quote_ticks = int(lambda_sym["bid_price"].notna().sum())
    ask_quote_ticks = int(lambda_sym["ask_price"].notna().sum())
    quoted_tick_count = int((lambda_sym["bid_price"].notna() | lambda_sym["ask_price"].notna()).sum())

    buy_trades = submission_trades.loc[submission_trades["side"] == "BUY"] if not submission_trades.empty else pd.DataFrame()
    sell_trades = submission_trades.loc[submission_trades["side"] == "SELL"] if not submission_trades.empty else pd.DataFrame()
    buy_fill_count = int(len(buy_trades))
    sell_fill_count = int(len(sell_trades))
    buy_filled_qty = int(buy_trades["quantity"].sum()) if not buy_trades.empty else 0
    sell_filled_qty = int(sell_trades["quantity"].sum()) if not sell_trades.empty else 0

    return {
        "symbol": symbol,
        "quoted_tick_count": quoted_tick_count,
        "bid_quote_ticks": bid_quote_ticks,
        "ask_quote_ticks": ask_quote_ticks,
        "avg_quoted_spread": float(spread_series.dropna().mean()) if spread_series.notna().any() else None,
        "buy_fill_count": buy_fill_count,
        "sell_fill_count": sell_fill_count,
        "buy_filled_qty": buy_filled_qty,
        "sell_filled_qty": sell_filled_qty,
        "buy_fill_rate_per_tick": (buy_fill_count / bid_quote_ticks) if bid_quote_ticks else None,
        "sell_fill_rate_per_tick": (sell_fill_count / ask_quote_ticks) if ask_quote_ticks else None,
        "buy_qty_per_tick": (buy_filled_qty / bid_quote_ticks) if bid_quote_ticks else None,
        "sell_qty_per_tick": (sell_filled_qty / ask_quote_ticks) if ask_quote_ticks else None,
    }


def _markout_horizons() -> list[int]:
    return [1, 2, 5, 10]


def official_trade_markouts(log: OfficialLog, symbol: str) -> pd.DataFrame:
    activities = log.activities.loc[log.activities["product"] == symbol].copy()
    if activities.empty:
        return pd.DataFrame()

    activities = _compute_activity_features(activities.sort_values("timestamp"))
    submission_trades = _submission_trades(log.trades, symbol)
    if submission_trades.empty:
        return pd.DataFrame()

    timestamps = activities["timestamp"].astype(int).tolist()
    timestamp_index = {timestamp: index for index, timestamp in enumerate(timestamps)}
    mid_by_timestamp = dict(zip(timestamps, ((activities["bid_price_1"] + activities["ask_price_1"]) / 2.0).tolist()))

    rows = []
    horizons = _markout_horizons()

    for _, trade in submission_trades.iterrows():
        timestamp = int(trade["timestamp"])
        side = str(trade["side"]).upper()
        sign = 1 if side == "BUY" else -1
        index = timestamp_index.get(timestamp)
        if index is None:
            continue

        row = trade.to_dict()
        row["counterparty"] = (
            str(trade.get("seller") or "").strip() if side == "BUY"
            else str(trade.get("buyer") or "").strip()
        ) or "UNKNOWN"
        row["mid_price"] = mid_by_timestamp.get(timestamp)

        for horizon in horizons:
            key = f"markout_{horizon}"
            future_index = index + horizon
            if future_index >= len(timestamps):
                row[key] = None
                row[f"{key}_qty"] = 0
                continue
            future_mid = mid_by_timestamp.get(timestamps[future_index])
            if future_mid is None:
                row[key] = None
                row[f"{key}_qty"] = 0
                continue
            row[key] = (future_mid - float(trade["price"])) * sign
            row[f"{key}_qty"] = int(trade["quantity"])
        rows.append(row)

    return pd.DataFrame(rows)


def official_market_trade_flow(log: OfficialLog, symbol: str) -> pd.DataFrame:
    trades = log.trades.loc[log.trades.get("symbol", pd.Series(dtype=str)) == symbol].copy() if not log.trades.empty else pd.DataFrame()
    activities = log.activities.loc[log.activities["product"] == symbol].copy() if not log.activities.empty else pd.DataFrame()
    if trades.empty:
        return pd.DataFrame(columns=["timestamp", "price", "quantity", "side", "signed_quantity", "source"])
    if activities.empty:
        frame = trades.sort_values("timestamp").copy()
        frame["side"] = "UNKNOWN"
        frame["signed_quantity"] = 0
        frame["source"] = "market"
        return frame[["timestamp", "price", "quantity", "side", "signed_quantity", "source"]]

    activities = _compute_activity_features(activities.sort_values("timestamp"))
    activity_by_timestamp = {
        int(row["timestamp"]): row
        for _, row in activities.iterrows()
    }

    rows = []
    for _, trade in trades.iterrows():
        timestamp = int(trade["timestamp"])
        price = float(trade["price"])
        quantity = int(trade["quantity"])
        buyer = str(trade.get("buyer") or "")
        seller = str(trade.get("seller") or "")
        snapshot = activity_by_timestamp.get(timestamp)

        if buyer == "SUBMISSION":
            side = "BUY"
            source = "submission"
        elif seller == "SUBMISSION":
            side = "SELL"
            source = "submission"
        elif snapshot is None:
            side = "UNKNOWN"
            source = "market"
        else:
            bid = float(snapshot["bid_price_1"])
            ask = float(snapshot["ask_price_1"])
            mid = float((bid + ask) / 2.0)
            if price >= ask:
                side = "BUY"
            elif price <= bid:
                side = "SELL"
            elif price > mid:
                side = "BUY"
            elif price < mid:
                side = "SELL"
            else:
                side = "UNKNOWN"
            source = "market"

        signed_quantity = quantity if side == "BUY" else -quantity if side == "SELL" else 0
        rows.append({
            "timestamp": timestamp,
            "price": price,
            "quantity": quantity,
            "side": side,
            "signed_quantity": signed_quantity,
            "source": source,
        })

    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def participant_aware_summary(log: OfficialLog, symbol: str) -> dict:
    trades = official_trade_markouts(log, symbol)
    horizons = _markout_horizons()
    if trades.empty:
        return {
            "symbol": symbol,
            "trade_count": 0,
            "traded_volume": 0,
            "mean_markout_by_horizon": {str(h): None for h in horizons},
            "participants": [],
        }

    mean_markout_by_horizon = {}
    for horizon in horizons:
        column = f"markout_{horizon}"
        valid = trades.dropna(subset=[column])
        if valid.empty:
            mean_markout_by_horizon[str(horizon)] = None
            continue
        qty = valid["quantity"].clip(lower=0)
        mean_markout_by_horizon[str(horizon)] = float((valid[column] * qty).sum() / qty.sum()) if qty.sum() else None

    participants = []
    for counterparty, group in trades.groupby("counterparty"):
        participant = {
            "counterparty": counterparty,
            "trade_count": int(len(group)),
            "traded_volume": int(group["quantity"].sum()),
            "buy_qty": int(group.loc[group["side"] == "BUY", "quantity"].sum()),
            "sell_qty": int(group.loc[group["side"] == "SELL", "quantity"].sum()),
        }
        for horizon in horizons:
            column = f"markout_{horizon}"
            valid = group.dropna(subset=[column])
            qty = valid["quantity"].clip(lower=0)
            participant[f"mean_markout_{horizon}"] = (
                float((valid[column] * qty).sum() / qty.sum()) if not valid.empty and qty.sum() else None
            )
        participants.append(participant)

    participants.sort(key=lambda row: (-row["traded_volume"], row["counterparty"]))
    return {
        "symbol": symbol,
        "trade_count": int(len(trades)),
        "traded_volume": int(trades["quantity"].sum()),
        "mean_markout_by_horizon": mean_markout_by_horizon,
        "participants": participants,
    }


def plot_symbol_review(log: OfficialLog, symbol: str, output_dir: str | Path, edge: float = 1.0, group: str | None = None) -> Path:
    symbol_activities = log.activities.loc[log.activities["product"] == symbol].copy()
    if symbol_activities.empty:
        raise ValueError(f"No activity rows found for product {symbol}")

    symbol_activities = _compute_activity_features(symbol_activities.sort_values("timestamp"))
    symbol_trades = _submission_trades(log.trades, symbol)

    # Strategy-side features (fair_value, trend_ticks, residual_z, inv_target ...)
    strategy_quotes = _parse_lambda_logs(log.runtime_logs)
    strategy_quotes = strategy_quotes.loc[strategy_quotes["product"] == symbol].copy()

    buy_opportunities = symbol_activities["ask_price_1"] <= symbol_activities["fair"] - edge
    sell_opportunities = symbol_activities["bid_price_1"] >= symbol_activities["fair"] + edge

    figure, (price_ax, pos_ax, cash_ax, exec_ax) = plt.subplots(
        4,
        1,
        figsize=(16, 14),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1, 1, 1]},
    )

    price_ax.plot(symbol_activities["timestamp"], symbol_activities["bid_price_1"], label="Best bid", color="#0b7285")
    price_ax.plot(symbol_activities["timestamp"], symbol_activities["ask_price_1"], label="Best ask", color="#c92a2a")
    price_ax.plot(symbol_activities["timestamp"], symbol_activities["fair"], label="Fair value (EWM microprice)", color="#2b8a3e")

    # Overlay strategy's internal fair value (block-OLS regression) if logged.
    if not strategy_quotes.empty and "fair_value" in strategy_quotes.columns:
        reg_fv = pd.to_numeric(strategy_quotes["fair_value"], errors="coerce")
        mask = reg_fv.notna()
        if mask.any():
            price_ax.plot(
                strategy_quotes.loc[mask, "timestamp"],
                reg_fv.loc[mask],
                label="Strategy fair (block-OLS reg)",
                color="#9c36b5",
                linewidth=1.3,
                linestyle="--",
            )

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

        sorted_trades = symbol_trades.sort_values("timestamp").reset_index(drop=True)
        inventory = sorted_trades["signed_quantity"].cumsum()
        # Cash: SELL adds price*qty, BUY subtracts price*qty.
        cash_delta = -sorted_trades["price"] * sorted_trades["signed_quantity"]
        cash_running = cash_delta.cumsum()

        # Extend steps to the end of the price panel so flat-position regions
        # after the last trade stay visible.
        end_ts = float(symbol_activities["timestamp"].max())
        inv_ts = pd.concat([sorted_trades["timestamp"], pd.Series([end_ts])], ignore_index=True)
        inv_vals = pd.concat([inventory, pd.Series([inventory.iloc[-1]])], ignore_index=True)
        cash_vals = pd.concat([cash_running, pd.Series([cash_running.iloc[-1]])], ignore_index=True)

        pos_ax.plot(inv_ts, inv_vals, color="#1864ab", linewidth=1.4, drawstyle="steps-post")
        pos_ax.fill_between(inv_ts, 0, inv_vals, color="#1864ab", alpha=0.15, step="post")
        pos_ax.axhline(0, color="#adb5bd", linewidth=1)
        max_abs_pos = float(inventory.abs().max() or 1.0)
        pos_ax.text(
            0.01, 0.92,
            f"end={int(inventory.iloc[-1])}  max|pos|={int(max_abs_pos)}",
            transform=pos_ax.transAxes, fontsize=9, color="#1864ab",
        )

        cash_ax.plot(inv_ts, cash_vals, color="#e8590c", linewidth=1.4, drawstyle="steps-post")
        cash_ax.fill_between(inv_ts, 0, cash_vals, color="#e8590c", alpha=0.12, step="post")
        cash_ax.axhline(0, color="#adb5bd", linewidth=1)
        cash_ax.text(
            0.01, 0.92,
            f"end_cash={cash_running.iloc[-1]:,.0f}",
            transform=cash_ax.transAxes, fontsize=9, color="#e8590c",
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

    pos_ax.set_ylabel("Inventory")
    pos_ax.grid(alpha=0.15)

    cash_ax.set_ylabel("Cash balance")
    cash_ax.grid(alpha=0.15)

    exec_ax.axhline(0, color="#adb5bd", linewidth=1)
    exec_ax.set_ylabel("Signed qty")
    exec_ax.set_xlabel("Timestamp")
    exec_ax.grid(alpha=0.15)

    group_name = group if group is not None else log.analysis_group
    group_dir = Path(output_dir) / group_name if group_name else Path(output_dir)
    output_path = group_dir / f"{log.submission_id}_{symbol}_review.png"
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
    participant_preview = {}
    for symbol in sorted(submission_trades["symbol"].dropna().unique()):
        participant_summary = participant_aware_summary(log, symbol)
        top_participants = participant_summary["participants"][:2]
        if top_participants:
            participant_preview[symbol] = [
                {
                    "counterparty": participant["counterparty"],
                    "volume": participant["traded_volume"],
                    "markout_1": participant.get("mean_markout_1"),
                }
                for participant in top_participants
            ]
    return (
        f"{prefix} trade_count={len(submission_trades)} "
        f"traded_volume={traded_volume} per_symbol={per_symbol} "
        f"top_counterparties={participant_preview}"
    )


def run_cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Prosperity official JSON / LOG files")
    parser.add_argument("--log", required=True, help="Path to an official JSON or LOG file")
    parser.add_argument("--backtest-json", help="Optional local backtest JSON to auto-reconcile against (auto-discovery is attempted from artifacts/)")
    parser.add_argument("--symbol", action="append", help="Product symbol to plot, can be passed multiple times")
    parser.add_argument("--outdir", default="artifacts/analysis", help="Directory that will receive generated plots")
    parser.add_argument("--group", default=None, help="Override subfolder name under --outdir (default: parent folder of log)")
    parser.add_argument("--edge", type=float, default=1.0, help="Opportunity threshold around fair value")
    args = parser.parse_args(list(argv) if argv is not None else None)

    log = load_official_log(args.log)
    symbols = args.symbol or sorted(log.activities["product"].dropna().unique())

    print(summarize_log(log))
    backtest_json_path = args.backtest_json
    if backtest_json_path is None:
        from prosperity.tooling.reconcile import discover_backtest_json

        discovered = discover_backtest_json(log)
        if discovered is not None:
            backtest_json_path = str(discovered)
            print(f"Auto-discovered backtest JSON: {backtest_json_path}")

    if backtest_json_path:
        from prosperity.tooling.reconcile import reconcile_backtest_to_official, summarize_reconcile_report

        backtest_data = json.loads(Path(backtest_json_path).read_text(encoding="utf-8"))
        report = reconcile_backtest_to_official(backtest_data, log)
        print(summarize_reconcile_report(report))

    for symbol in symbols:
        quote_summary = official_quote_summary(log, symbol)
        if quote_summary.get("quoted_tick_count"):
            print(
                f"{symbol} quote_summary="
                f"ticks={quote_summary['quoted_tick_count']} "
                f"bid_fill_rate={quote_summary.get('buy_fill_rate_per_tick')} "
                f"ask_fill_rate={quote_summary.get('sell_fill_rate_per_tick')} "
                f"avg_spread={quote_summary.get('avg_quoted_spread')}"
            )
        participant_summary = participant_aware_summary(log, symbol)
        top_participants = participant_summary["participants"][:5]
        if top_participants:
            compact = [
                (
                    participant["counterparty"],
                    participant["traded_volume"],
                    participant.get("mean_markout_1"),
                )
                for participant in top_participants
            ]
            print(f"{symbol} participant_summary={compact}")
        output_path = plot_symbol_review(log, symbol, args.outdir, edge=args.edge, group=args.group)
        print(f"saved {output_path}")

    return 0
