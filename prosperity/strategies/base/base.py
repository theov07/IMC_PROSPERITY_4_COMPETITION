"""Base strategy interface for all trading strategies."""

from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot, snapshot_from_order_depth


class BaseStrategy(ABC):
    """Abstract base for all product strategies.

    Each strategy receives the full TradingState but is responsible for
    producing orders for ONE product at a time.
    """

    def __init__(self, product: str, params: Dict[str, Any]):
        self.product = product
        self.params = params

    # ------------------------------------------------------------------
    def on_tick(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        """Called every iteration for this product.

        Returns:
            orders: list of Order objects to send
            conversions: integer conversion request (0 if none)
        """
        self._memory = memory  # available to all helper methods via self._memory

        order_depth = state.order_depths.get(self.product)
        if order_depth is None:
            return [], 0

        position = state.position.get(self.product, 0)
        book = snapshot_from_order_depth(self.product, order_depth)

        orders, conversions = self.compute_orders(
            state=state,
            book=book,
            order_depth=order_depth,
            position=position,
            memory=memory,
        )

        # Alpha overlay used by champion v5: OBI size tilt
        orders = self._apply_obi_size_tilt(state, position, orders, book, memory)
        # Position-skewed ask/bid (force unwind when position > threshold)
        orders = self._apply_position_skew(state, position, orders, book, memory)

        return orders, conversions

    def _apply_position_skew(
        self,
        state: TradingState,
        position: int,
        orders: List[Order],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> List[Order]:
        """Skew quotes more aggressively to unwind when position is over threshold.

        Fixes R3 stuck-long-+300 issue on options.
        When position > +threshold: shift SELL orders DOWN by `skew_offset` (more aggressive ask
                                    → faster fills → unwind long).
        When position < -threshold: shift BUY orders UP by `skew_offset` (more aggressive bid).

        Params:
          pos_skew_enabled    : turn on (default False — must opt-in per product)
          pos_skew_threshold  : abs position to fire (default 100)
          pos_skew_offset     : ticks to shift on the unwind side (default 1)
        """
        if not bool(self.params.get("pos_skew_enabled", False)):
            return orders

        threshold = int(self.params.get("pos_skew_threshold", 100))
        offset = int(self.params.get("pos_skew_offset", 1))

        if abs(position) < threshold:
            return orders

        adjusted: List[Order] = []
        best_bid = book.best_bid
        best_ask = book.best_ask
        for o in orders:
            new_price = int(o.price)
            if position > 0 and o.quantity < 0:
                # Long → make ask more aggressive (lower)
                new_price = int(o.price) - offset
                # Don't cross the bid
                if best_bid is not None and new_price <= best_bid:
                    new_price = int(best_bid) + 1
            elif position < 0 and o.quantity > 0:
                # Short → make bid more aggressive (higher)
                new_price = int(o.price) + offset
                # Don't cross the ask
                if best_ask is not None and new_price >= best_ask:
                    new_price = int(best_ask) - 1
            adjusted.append(Order(o.symbol, new_price, o.quantity))

        memory["_pos_skew_active"] = 1
        return adjusted

    @abstractmethod
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        """Produce orders and conversion request for this product."""
        ...

    # ------------------------------------------------------------------
    # Shared price utilities (call from any strategy)
    # ------------------------------------------------------------------
    def _microprice(self, book: "BookSnapshot") -> float:
        """Volume-weighted microprice using all available book levels.

        bid_vwap = Σ(price × vol) / Σvol  across all bid levels
        ask_vwap = same for asks
        microprice = (bid_vwap × ask_total + ask_vwap × bid_total) / (bid_total + ask_total)

        One side empty OR both sides empty → returns the previous microprice
        stored in self._memory["_microprice_last"] (or 0.0 on the very first tick).

        Stores result in self._memory["_microprice_last"].
        Requires self._memory to be set (done automatically by on_tick).
        """
        bid_total = sum(v for _, v in book.bid_levels)
        ask_total = sum(v for _, v in book.ask_levels)

        prev = self._memory.get("_microprice_last", 0.0)

        if bid_total == 0 or ask_total == 0:
            # One or both sides empty: can't compute a meaningful cross-side price
            return float(prev)

        bid_vwap = sum(p * v for p, v in book.bid_levels) / bid_total
        ask_vwap = sum(p * v for p, v in book.ask_levels) / ask_total
        result = (bid_vwap * ask_total + ask_vwap * bid_total) / (bid_total + ask_total)

        self._memory["_microprice_last"] = result
        return result

    def _smooth_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        """EWMA smoother for any price series (mid, microprice, etc.).

        Params read from self.params:
          mid_smooth_window    — rolling window size (default 20; 0 = disabled)
          mid_smooth_half_life — EMA half-life in ticks (default window/2)

        Stores in memory: ``mid_smooth_buf``, ``mid_smoothed``.
        Returns the smoothed value (or the raw input when window <= 0 or too few samples).
        """
        window = int(self.params.get("mid_smooth_window", 20))
        if window <= 0:
            return mid
        half_life = float(self.params.get("mid_smooth_half_life", window / 2.0))
        buf = memory.setdefault("mid_smooth_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < 2:
            return mid
        alpha = 1.0 - 2.0 ** (-1.0 / half_life) if half_life > 0 else 1.0
        smoothed = buf[0]
        for p in buf[1:]:
            smoothed = alpha * p + (1.0 - alpha) * smoothed
        memory["mid_smoothed"] = smoothed
        return smoothed

    # ------------------------------------------------------------------
    # Shared volatility estimation (call from any strategy)
    # ------------------------------------------------------------------
    def _update_volatility(self, mid: float, memory: Dict[str, Any]) -> float:
        """Estimate realised volatility from mid-price returns with EWMA smoothing.

        Params read from self.params:
          sigma_window   — rolling window size for returns (default 50)
          sigma_default  — fallback when too few prices (default 1.0)
          sigma_half_life — EWMA half-life for smoothing (default 60)
          sigma_floor    — minimum returned value (default 0.5)

        Stores in memory: ``mid_history``, ``sigma_smoothed``.
        Returns the floored, smoothed sigma.
        """
        window = int(self.params.get("sigma_window", 50))
        prices = memory.setdefault("mid_history", [])
        prices.append(mid)
        if len(prices) > window + 1:
            prices[:] = prices[-(window + 1):]

        if len(prices) < 3:
            return float(self.params.get("sigma_default", 1.0))

        returns = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        n = len(returns)
        mean_r = sum(returns) / n
        var = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
        sigma_raw = math.sqrt(var) if var > 0 else float(self.params.get("sigma_default", 1.0))

        half_life = float(self.params.get("sigma_half_life", 60))
        alpha = 2.0 / (half_life + 1.0)
        sigma_prev = memory.get("sigma_smoothed", sigma_raw)
        sigma_smoothed = alpha * sigma_raw + (1.0 - alpha) * sigma_prev
        memory["sigma_smoothed"] = sigma_smoothed

        return max(sigma_smoothed, float(self.params.get("sigma_floor", 0.5)))

    # ------------------------------------------------------------------
    # Optional: expose named price features for the dashboard
    # ------------------------------------------------------------------
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        """Return a dict of named price-level features at the current tick.

        Override in concrete strategies to surface prices like reservation price,
        fair value, etc.  Keys become trace names in the dashboard.
        Default: no features.
        """
        return {}

    # ------------------------------------------------------------------
    # Helpers available to all strategies
    # ------------------------------------------------------------------
    def runtime_trace_enabled(self) -> bool:
        enabled = self.params.get("runtime_trace_enabled")
        if enabled is not None:
            return bool(enabled)
        return not bool(os.environ.get("INTERNAL_BACKTEST"))

    def log_quote_snapshot(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        bid_price: int | float | None,
        ask_price: int | float | None,
        extras: Dict[str, Any] | None = None,
    ) -> None:
        """Accumulate and flush a lightweight quote trace for official IMC logs.

        The trace format is intentionally small and common across quoting
        strategies so the dashboard can render our own bid/ask from runtime logs:
          {
            "product": "...",
            "trace": "quote_trace",
            "chunk_end": 49900,
            "columns": ["timestamp", "bid_price", "ask_price", ...],
            "log": [[...], [...]]
          }

        Strategies may append extra per-tick diagnostics through ``extras`` as
        long as they keep a stable schema across ticks.
        """
        if not self.params.get("quote_trace_enabled", False) or not self.runtime_trace_enabled():
            return

        row: Dict[str, Any] = {
            "timestamp": int(state.timestamp),
            "bid_price": bid_price,
            "ask_price": ask_price,
        }
        if extras:
            row.update(extras)

        columns = memory.setdefault("_quote_trace_columns", list(row.keys()))
        for key in row.keys():
            if key not in columns:
                columns.append(key)

        rows = memory.setdefault("_quote_trace_rows", [])
        rows.append(row)

        flush_ts = int(self.params.get("log_flush_ts", 10000))
        last_tick_ts = self.params.get("last_ts_value")
        if last_tick_ts is None:
            last_tick_ts = int(self.params.get("total_ticks", 200000)) - 100
        else:
            last_tick_ts = int(last_tick_ts)

        end_of_sim = int(state.timestamp) >= last_tick_ts
        checkpoint = flush_ts > 0 and (int(state.timestamp) % flush_ts) == (flush_ts - 100)
        if not (end_of_sim or checkpoint):
            return

        print(json.dumps({
            "product": self.product,
            "trace": "quote_trace",
            "chunk_end": int(state.timestamp),
            "columns": columns,
            "log": [[row.get(column) for column in columns] for row in rows],
        }))
        memory["_quote_trace_rows"] = []

    def log_taker_fill(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        side: str,
        price: int,
        quantity: int,
        gap_exploit: bool = False,
    ) -> None:
        """Accumulate a taker fill and flush when the buffer is full enough.

        Flush conditions (in priority order):
          1. Deferred flag was set last tick → flush now.
          2. Timestamp is the second-to-last of the day → flush as end-of-day cleanup.
          3. Buffer reached 20 fills AND we are NOT at a quote-flush timestamp → flush.
          4. Buffer reached 20 fills AND we ARE at a quote-flush timestamp → set deferred
             flag; the flush will fire on the very next tick instead.

        Log format emitted to stdout:
          {"product": "...", "trace": "taker_fills", "chunk_end": ts,
           "log": [[ts, side, price, qty], ...]}           # regular taker
           "log": [[ts, side, price, qty, 1], ...]}         # gap exploit (5th element=1)
        """
        if not self.runtime_trace_enabled():
            return

        taker_log = memory.setdefault("_taker_log", [])
        entry = [int(state.timestamp), side, price, quantity]
        if gap_exploit:
            entry.append(1)
        taker_log.append(entry)

        flush_ts = int(self.params.get("log_flush_ts", 10000))
        ts_increment = int(self.params.get("ts_increment", 100))
        last_ts = int(self.params.get("last_ts_value", 199900))
        second_to_last = last_ts - ts_increment

        is_quote_flush = flush_ts > 0 and (int(state.timestamp) % flush_ts) == (flush_ts - 100)
        deferred = memory.get("_taker_flush_deferred", False)

        # If threshold hit exactly on a quote-flush ts, defer to the next tick.
        if len(taker_log) >= 20 and is_quote_flush and not deferred:
            memory["_taker_flush_deferred"] = True
            return

        should_flush = (
            deferred
            or int(state.timestamp) >= second_to_last
            or (len(taker_log) >= 20 and not is_quote_flush)
        )
        if not should_flush:
            return

        print(json.dumps({
            "product": self.product,
            "trace": "taker_fills",
            "chunk_end": int(state.timestamp),
            "log": taker_log,
        }))
        memory["_taker_log"] = []
        memory["_taker_flush_deferred"] = False

    def position_limit(self) -> int:
        return self.params.get("position_limit", 20)

    def buy_capacity(self, position: int) -> int:
        return max(0, self.position_limit() - position)

    def sell_capacity(self, position: int) -> int:
        return max(0, self.position_limit() + position)

    # ------------------------------------------------------------------
    # Trend gate (skip mean-rev BUY in downtrend, mean-rev SELL in uptrend)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Order Book Imbalance (OBI) SIZE tilt — adjust own quote SIZES (not prices).
    # Avoids spread cost from price tilt. Captures alpha through inventory shift.
    # ------------------------------------------------------------------
    def _apply_obi_size_tilt(
        self,
        state: TradingState,
        position: int,
        orders: List[Order],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> List[Order]:
        """When L3 OBI is extreme, increase the size of orders going in the predicted direction.

        Bullish OBI (>+threshold):
          - Multiply BUY orders by `obi_size_boost_factor` (e.g. 1.5x) — accumulate long
          - Reduce SELL order sizes by `obi_size_reduce_factor` (e.g. 0.5x) — keep long longer

        Bearish OBI (<-threshold): mirror.

        Params:
          obi_size_enabled         : turn on (default False)
          obi_size_levels          : aggregation levels (default 3)
          obi_size_threshold       : abs OBI to fire (default 0.005)
          obi_size_boost_factor    : multiplier on favored side (default 1.5)
          obi_size_reduce_factor   : multiplier on opposed side (default 0.7)
        """
        if not bool(self.params.get("obi_size_enabled", False)):
            return orders

        levels = int(self.params.get("obi_size_levels", 3))
        threshold = float(self.params.get("obi_size_threshold", 0.005))
        boost = float(self.params.get("obi_size_boost_factor", 1.5))
        reduce = float(self.params.get("obi_size_reduce_factor", 0.7))

        bid_total = sum(v for _, v in (book.bid_levels or [])[:levels])
        ask_total = sum(v for _, v in (book.ask_levels or [])[:levels])
        total = bid_total + ask_total
        if total == 0:
            return orders
        obi = (bid_total - ask_total) / total
        memory["_obi_size"] = obi

        if abs(obi) < threshold:
            return orders

        bullish = obi > 0
        adjusted: List[Order] = []
        for o in orders:
            if o.quantity > 0:  # BUY
                factor = boost if bullish else reduce
            elif o.quantity < 0:  # SELL
                factor = reduce if bullish else boost
            else:
                adjusted.append(o)
                continue
            new_qty = int(o.quantity * factor)
            # Respect position limits
            if new_qty > 0:
                cap = max(0, self.position_limit() - position)
                new_qty = min(new_qty, cap) if cap >= 0 else new_qty
            elif new_qty < 0:
                cap = max(0, self.position_limit() + position)
                new_qty = max(new_qty, -cap)
            if new_qty != 0:
                adjusted.append(Order(o.symbol, o.price, new_qty))

        memory["_obi_size_dir"] = "BULL" if bullish else "BEAR"
        return adjusted

    def _counterparty_signal(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> float:
        """Counterparty-flow weighted signal.

        Maintains a rolling buffer of (timestamp, trader_id, signed_qty) for the last
        `cp_window_ts` timestamp units. Signed qty = +qty when trader is buyer, -qty
        when trader is seller. Aggregates per trader, applies a per-trader weight,
        returns weighted sum.

        Default weights (from R4 D1+D2+D3 lead-lag analysis on VELVET):
          Mark 55 = +1.0  (high-vol MM, +0.14 rho with next-50-tick return, 60% hit rate)
          Mark 67 = +1.0  (directional buyer, +0.12 rho, 54% hit rate)
          Mark 01 = -1.0  (MM, -0.17 rho — FADE its flow)
          Mark 14 = -1.0  (MM, -0.15 rho — FADE)
        Other traders default to 0 weight.

        Params:
          cp_window_ts        : rolling window in timestamp units (default 10000 = 100 ticks)
          cp_trader_weights   : dict trader_id -> weight (default = R4 VELVET weights)

        Returns: weighted signed signal (units = contracts).
        """
        window_ts = int(self.params.get("cp_window_ts", 10000))
        weights = self.params.get("cp_trader_weights", {
            "Mark 55": +1.0, "Mark 67": +1.0,
            "Mark 01": -1.0, "Mark 14": -1.0,
        })

        ts_now = int(getattr(state, "timestamp", 0))

        # Append this tick's trades to rolling buffer
        buf = memory.setdefault("_cp_buf", [])  # list of [ts, trader, signed_qty]
        try:
            mt = state.market_trades
            trades = (mt or {}).get(self.product, []) or []
        except Exception:
            trades = []
        for t in trades:
            buyer = getattr(t, "buyer", None) or ""
            seller = getattr(t, "seller", None) or ""
            qty = float(getattr(t, "quantity", 0))
            if qty <= 0:
                continue
            if buyer:
                buf.append([ts_now, buyer, qty])
            if seller:
                buf.append([ts_now, seller, -qty])

        # Drop old entries
        cutoff = ts_now - window_ts
        if buf and buf[0][0] < cutoff:
            i = 0
            while i < len(buf) and buf[i][0] < cutoff:
                i += 1
            del buf[:i]

        # Aggregate per trader, apply weights
        signal = 0.0
        per_trader = {}
        for _, trader, signed in buf:
            per_trader[trader] = per_trader.get(trader, 0.0) + signed
        for trader, net in per_trader.items():
            w = weights.get(trader, 0.0)
            signal += w * net

        memory["_cp_signal"] = signal
        memory["_cp_per_trader"] = per_trader
        return signal
