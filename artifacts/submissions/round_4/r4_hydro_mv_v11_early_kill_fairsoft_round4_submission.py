from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Optional, Set, Tuple
from typing import Any, Dict, List, Tuple
from typing import Dict
from typing import Dict, List, Optional, Set, Tuple
from typing import List, Tuple
import json
import math

# ── prosperity/market.py ──────────────────────────────────────────────────────────

PriceLevel = Tuple[int, int]


@dataclass(frozen=True)
class BookSnapshot:
    symbol: str
    bid_levels: List[PriceLevel]
    ask_levels: List[PriceLevel]
    best_bid: int | None
    best_bid_volume: int
    best_ask: int | None
    best_ask_volume: int
    mid_price: float | None
    microprice: float | None
    spread: int | None
    imbalance: float | None


def _sorted_bid_levels(order_depth: OrderDepth) -> List[PriceLevel]:
    return sorted(order_depth.buy_orders.items(), key=lambda item: item[0], reverse=True)


def _sorted_ask_levels(order_depth: OrderDepth) -> List[PriceLevel]:
    return sorted(((price, -volume) for price, volume in order_depth.sell_orders.items()), key=lambda item: item[0])


def snapshot_from_order_depth(symbol: str, order_depth: OrderDepth) -> BookSnapshot:
    bid_levels = _sorted_bid_levels(order_depth)
    ask_levels = _sorted_ask_levels(order_depth)

    best_bid = bid_levels[0][0] if bid_levels else None
    best_bid_volume = bid_levels[0][1] if bid_levels else 0
    best_ask = ask_levels[0][0] if ask_levels else None
    best_ask_volume = ask_levels[0][1] if ask_levels else 0

    mid_price = None
    microprice = None
    spread = None
    imbalance = None

    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2.0

        total_top = best_bid_volume + best_ask_volume
        if total_top > 0:
            microprice = (
                best_bid * best_ask_volume + best_ask * best_bid_volume
            ) / total_top
            imbalance = (best_bid_volume - best_ask_volume) / total_top

    return BookSnapshot(
        symbol=symbol,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        best_bid=best_bid,
        best_bid_volume=best_bid_volume,
        best_ask=best_ask,
        best_ask_volume=best_ask_volume,
        mid_price=mid_price,
        microprice=microprice,
        spread=spread,
        imbalance=imbalance,
    )


# ── prosperity/persistence.py ─────────────────────────────────────────────────────

def load_state(raw_state: str) -> Dict[str, Any]:
    if not raw_state:
        return {}
    try:
        loaded = json.loads(raw_state)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def dump_state(state: Dict[str, Any]) -> str:
    return json.dumps(state, separators=(",", ":"))


# ── prosperity/strategies/base/base.py ────────────────────────────────────────────

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

        return self.compute_orders(
            state=state,
            book=book,
            order_depth=order_depth,
            position=position,
            memory=memory,
        )

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
        return not bool(False)

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


# ── prosperity/strategies/round_4/hydro_mv_v5_best.py ─────────────────────────────

# ── prosperity/market.py ──────────────────────────────────────────────────────────

PriceLevel = Tuple[int, int]


@dataclass(frozen=True)
class BookSnapshot:
    symbol: str
    bid_levels: List[PriceLevel]
    ask_levels: List[PriceLevel]
    best_bid: int | None
    best_bid_volume: int
    best_ask: int | None
    best_ask_volume: int
    mid_price: float | None
    microprice: float | None
    spread: int | None
    imbalance: float | None


def _sorted_bid_levels(order_depth: OrderDepth) -> List[PriceLevel]:
    return sorted(order_depth.buy_orders.items(), key=lambda item: item[0], reverse=True)


def _sorted_ask_levels(order_depth: OrderDepth) -> List[PriceLevel]:
    return sorted(((price, -volume) for price, volume in order_depth.sell_orders.items()), key=lambda item: item[0])


def snapshot_from_order_depth(symbol: str, order_depth: OrderDepth) -> BookSnapshot:
    bid_levels = _sorted_bid_levels(order_depth)
    ask_levels = _sorted_ask_levels(order_depth)

    best_bid = bid_levels[0][0] if bid_levels else None
    best_bid_volume = bid_levels[0][1] if bid_levels else 0
    best_ask = ask_levels[0][0] if ask_levels else None
    best_ask_volume = ask_levels[0][1] if ask_levels else 0

    mid_price = None
    microprice = None
    spread = None
    imbalance = None

    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2.0

        total_top = best_bid_volume + best_ask_volume
        if total_top > 0:
            microprice = (
                best_bid * best_ask_volume + best_ask * best_bid_volume
            ) / total_top
            imbalance = (best_bid_volume - best_ask_volume) / total_top

    return BookSnapshot(
        symbol=symbol,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        best_bid=best_bid,
        best_bid_volume=best_bid_volume,
        best_ask=best_ask,
        best_ask_volume=best_ask_volume,
        mid_price=mid_price,
        microprice=microprice,
        spread=spread,
        imbalance=imbalance,
    )


# ── prosperity/persistence.py ─────────────────────────────────────────────────────

def load_state(raw_state: str) -> Dict[str, Any]:
    if not raw_state:
        return {}
    try:
        loaded = json.loads(raw_state)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def dump_state(state: Dict[str, Any]) -> str:
    return json.dumps(state, separators=(",", ":"))


# ── prosperity/strategies/base/base.py ────────────────────────────────────────────

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

        return self.compute_orders(
            state=state,
            book=book,
            order_depth=order_depth,
            position=position,
            memory=memory,
        )

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
        return not bool(False)

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


# ── prosperity/strategies/round_4/tibo/hydro_mv_v5.py ─────────────────────────────

class HydroMVV5(BaseStrategy):

    # ── AR model (from v4) ────────────────────────────────────────────────

    def _update_ar(
        self, raw_mid: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        ms_hl    = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms  = memory.get("_mid_smooth")
        mid_s    = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        anchor_fixed = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.02))
        drift_bound  = float(self.params.get("anchor_drift_bound", 1.5))
        anchor_ema   = float(memory.get("_anchor_ema", anchor_fixed))
        if anchor_alpha > 0:
            anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
            if drift_bound > 0:
                anchor_ema = max(anchor_fixed - drift_bound,
                                 min(anchor_fixed + drift_bound, anchor_ema))
        memory["_anchor_ema"] = anchor_ema

        ar_hl    = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta    = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom   = float(memory.get("_ar_momentum", 0.0))
        ar_mom   = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        ar_gain    = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev = mid_s - fair_value
        dev_hl    = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s     = float(memory.get("_dev_smooth", raw_dev))
        dev_s     = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s
        memory["_dev_raw"]    = raw_dev
        return mid_s, fair_value, dev_s

    # ── Mark 14 tracking ─────────────────────────────────────────────────

    def _update_m14(self, state: TradingState, memory: Dict[str, Any]) -> int:
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:    net += trade.quantity
            elif trade.seller == trader: net -= trade.quantity
        signal = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_signal"] = signal
        return signal

    # ── Sizing ────────────────────────────────────────────────────────────

    def _passive_sizes(self, position: int) -> Tuple[float, float]:
        limit   = self.position_limit()
        base    = float(self.params.get("maker_size_base_pct", 0.15)) * limit
        inv_bias = self.params.get("use_inventory_bias", True)
        if inv_bias and limit > 0:
            bid_size = base * (1.0 - position / limit)
            ask_size = base * (1.0 + position / limit)
        else:
            bid_size = ask_size = base
        return max(0.0, bid_size), max(0.0, ask_size)

    # ── Feature A: Passive quoting ────────────────────────────────────────

    def _passive_quotes(
        self,
        book: BookSnapshot,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        dev: float,
    ) -> List[Order]:
        if not self.params.get("passive_quoting", True):
            return []

        bid_price = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price = (book.best_ask - 1) if book.best_ask is not None else None

        # Feature E: AR quote bias — shift quote prices toward fair value
        if self.params.get("use_ar_quote_bias", False) and bid_price and ask_price:
            bias_ticks = int(self.params.get("ar_quote_bias_ticks", 2))
            if dev > 0:   # price above fair → make ask more aggressive
                ask_price = max(book.best_bid + 1 if book.best_bid else ask_price,
                                ask_price - bias_ticks)
            elif dev < 0: # price below fair → make bid more aggressive
                bid_price = min(book.best_ask - 1 if book.best_ask else bid_price,
                                bid_price + bias_ticks)

        # Guard: don't cross
        if bid_price is not None and ask_price is not None and bid_price >= ask_price:
            bid_price = ask_price - 1

        # Hard stop: don't quote accumulating side near position limit
        limit    = self.position_limit()
        hard_pct = float(self.params.get("pct_kept_for_takers", 0.2))
        if abs(position) >= limit * (1.0 - hard_pct):
            if position > 0: bid_size  = 0.0
            else:            ask_size  = 0.0

        orders: List[Order] = []
        qty_bid = min(buy_cap,  int(bid_size))
        qty_ask = min(sell_cap, int(ask_size))
        if qty_bid > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price,  qty_bid))
        if qty_ask > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -qty_ask))
        return orders

    # ── Feature B: AR taker orders ────────────────────────────────────────

    def _ar_takers(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        fair_value: float,
        dev: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        if not self.params.get("use_ar_taker", False):
            return [], buy_cap, sell_cap, set(), set()

        take_edge = float(self.params.get("ar_taker_edge", 1.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.3))
        orders: List[Order] = []
        buy_px:  Set[int] = set()
        sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fair_value - take_edge or buy_cap <= 0:
                break
            avail = -order_depth.sell_orders[ask_p]
            qty   = min(avail, buy_cap, max(1, int(bid_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fair_value + take_edge or sell_cap <= 0:
                break
            avail = order_depth.buy_orders[bid_p]
            qty   = min(avail, sell_cap, max(1, int(ask_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, buy_px, sell_px

    # ── Feature B2: Anchor guard (like v201's _use_anchor) ───────────────
    # Disable AR taker when price is trending AWAY from anchor.
    # This prevents accumulating bad positions when price is trending.

    def _guard_allows_taker(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> bool:
        if not self.params.get("use_anchor_guard", False):
            return True  # guard off → always allow
        anchor    = float(self.params.get("anchor_price", 10000))
        prev_mid  = memory.get("_guard_prev_mid", raw_mid)
        memory["_guard_prev_mid"] = raw_mid
        raw_delta = raw_mid - float(prev_mid)
        alpha     = float(self.params.get("guard_trend_alpha", 0.3))
        trend_ema = float(memory.get("_guard_trend_ema", raw_delta))
        trend_ema = alpha * raw_delta + (1.0 - alpha) * trend_ema
        memory["_guard_trend_ema"] = trend_ema
        dist      = raw_mid - anchor
        threshold = float(self.params.get("guard_reversion_threshold", 3.0))
        max_dist  = float(self.params.get("guard_max_dist", 80.0))
        # reverting: dist × trend ≤ -threshold (price moving back toward anchor)
        reverting = abs(dist) <= max_dist and (dist * trend_ema <= -threshold)
        near      = abs(dist) <= float(self.params.get("guard_near_band", 0.5))
        # also stop taker if position is already far in the trending direction
        inv_dist  = float(self.params.get("guard_inventory_dist", 40.0))
        wrong_way = (position > 0 and dist < -inv_dist) or (position < 0 and dist > inv_dist)
        guard_on  = (near or reverting) and not wrong_way
        memory["_guard_on"] = int(guard_on)
        return guard_on

    # ── Feature C: Gap exploit ────────────────────────────────────────────

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        if not self.params.get("use_gap_exploit", False):
            return [], buy_cap, sell_cap, None, None

        gap_min     = float(self.params.get("gap_trigger_min", 8))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))
        limit       = self.position_limit()
        gap_max_vol = int(gap_vol_pct * limit)

        all_bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        all_asks = sorted(order_depth.sell_orders.keys())
        if all_bids: memory["_last_best_bid"] = all_bids[0]
        if all_asks: memory["_last_best_ask"] = all_asks[0]
        last_bid = memory.get("_last_best_bid")
        last_ask = memory.get("_last_best_ask")

        rem_bids = [p for p in all_bids if p not in taker_sell_px]
        rem_asks = [p for p in all_asks if p not in taker_buy_px]

        orders:    List[Order] = []
        gap_swept_bids: Set[int] = set()
        gap_swept_asks: Set[int] = set()

        if gap_min > 0 and gap_max_vol > 0:
            bid_gap_ok = False
            bid1 = bid1_vol = None
            if len(rem_bids) >= 2:
                bid1, bid2 = rem_bids[0], rem_bids[1]
                bid1_vol   = order_depth.buy_orders[bid1]
                bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol
            streak = memory.get("_gap_bid_streak", 0)
            streak = streak + 1 if bid_gap_ok else 0
            memory["_gap_bid_streak"] = streak
            if streak >= gap_confirm and bid_gap_ok and sell_cap > 0:
                qty = min(bid1_vol, sell_cap, int(ask_size))
                if qty > 0:
                    orders.append(Order(self.product, bid1, -qty))
                    sell_cap -= qty
                    if qty >= bid1_vol: gap_swept_bids.add(bid1)

            ask_gap_ok = False
            ask1 = ask1_vol = None
            if len(rem_asks) >= 2:
                ask1, ask2 = rem_asks[0], rem_asks[1]
                ask1_vol   = -order_depth.sell_orders[ask1]
                ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol
            streak = memory.get("_gap_ask_streak", 0)
            streak = streak + 1 if ask_gap_ok else 0
            memory["_gap_ask_streak"] = streak
            if streak >= gap_confirm and ask_gap_ok and buy_cap > 0:
                qty = min(ask1_vol, buy_cap, int(bid_size))
                if qty > 0:
                    orders.append(Order(self.product, ask1, qty))
                    buy_cap -= qty
                    if qty >= ask1_vol: gap_swept_asks.add(ask1)

        final_bids = [p for p in rem_bids if p not in gap_swept_bids]
        final_asks = [p for p in rem_asks if p not in gap_swept_asks]
        shift = float(self.params.get("OB_cleared_shift", 8))
        new_bid = (final_bids[0] + 1) if final_bids else (
            (last_bid - int(shift)) if last_bid else None)
        new_ask = (final_asks[0] - 1) if final_asks else (
            (last_ask + int(shift)) if last_ask else None)

        return orders, buy_cap, sell_cap, new_bid, new_ask

    # ── Feature D: M14 gate ───────────────────────────────────────────────

    def _apply_m14_gate(
        self,
        orders: List[Order],
        signal: int,
        position: int,
    ) -> List[Order]:
        if not self.params.get("use_m14_gate", False) or signal == 0:
            return orders
        factor = float(self.params.get("m14_agree_factor", 2.0))
        limit  = self.position_limit()
        if signal > 0:
            cap = self.buy_capacity(position)
            return [
                Order(self.product, o.price,
                      min(cap, max(1, int(o.quantity * factor))))
                for o in orders if o.quantity > 0
            ]
        else:
            cap = self.sell_capacity(position)
            return [
                Order(self.product, o.price,
                      -min(cap, max(1, int(abs(o.quantity) * factor))))
                for o in orders if o.quantity < 0
            ]

    # ── Main entry ────────────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        mid = book.mid_price
        if mid is None:
            return [], 0

        mid_s, fair_value, dev = self._update_ar(float(mid), memory)
        sigma  = self._update_volatility(float(mid), memory)
        signal = self._update_m14(state, memory)

        # Store book for next-tick references
        if book.best_bid is not None: memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None: memory["_prev_best_ask"] = book.best_ask

        limit    = self.position_limit()
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_size, ask_size = self._passive_sizes(position)

        # Feature B2: guard check — skip AR taker when price trending away
        guard_ok = self._guard_allows_taker(float(mid), position, memory)

        # Feature B: AR taker orders (fire first, consume capacity)
        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = (
            self._ar_takers(book, order_depth, fair_value, dev,
                            bid_size, ask_size, buy_cap, sell_cap)
            if guard_ok else ([], buy_cap, sell_cap, set(), set())
        )

        # Feature C: Gap exploit (may adjust bid_price, ask_price)
        gap_orders, buy_cap, sell_cap, gap_bid, gap_ask = self._gap_exploit(
            order_depth, memory, bid_size, ask_size, buy_cap, sell_cap,
            taker_buy_px, taker_sell_px,
        )

        # Feature A: Passive quoting (use gap-adjusted prices if available)
        if gap_bid is not None:
            book_bid_override = gap_bid
        else:
            book_bid_override = book.best_bid
        if gap_ask is not None:
            book_ask_override = gap_ask
        else:
            book_ask_override = book.best_ask

        # Build a temporary book-like object for passive quoting
        class _FakeBook:
            best_bid = book_bid_override
            best_ask = book_ask_override

        passive_orders = self._passive_quotes(
            _FakeBook(), bid_size, ask_size, buy_cap, sell_cap, position, dev,
        )

        # Combine
        all_orders = taker_orders + gap_orders + passive_orders

        # Feature D: M14 gate (applied to passive orders only, like v201)
        passive_gated = self._apply_m14_gate(passive_orders, signal, position)
        all_orders    = taker_orders + gap_orders + passive_gated

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":   position,
                "deviation":  round(dev, 3),
                "fair_value": round(fair_value, 3),
                "m14_signal": signal,
                "bid_size":   int(bid_size),
                "ask_size":   int(ask_size),
                "sigma":      round(sigma, 4),
            },
        )
        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value")) is not None: out["FairValue"] = float(v)
        if (v := memory.get("_dev_smooth")) is not None: out["DevSmooth"] = float(v)
        if (v := memory.get("_m14_signal")) is not None: out["M14Signal"] = float(v)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'anchor_alpha': 0.02,
                   'anchor_drift_bound': 1.5,
                   'anchor_price': 10000,
                   'ar_gain': 8.0,
                   'ar_smooth_half_life': 5,
                   'ar_taker_edge': 12.0,
                   'ar_taker_size_pct': 0.3,
                   'dev_smooth_half_life': 5,
                   'informed_trader_name': 'Mark 14',
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size_base_pct': 0.25,
                   'mid_smooth_half_life': 20,
                   'passive_quoting': True,
                   'pct_kept_for_takers': 0.2,
                   'position_limit': 200,
                   'strategy': 'hydro_mv_v5',
                   'use_anchor_guard': False,
                   'use_ar_quote_bias': False,
                   'use_ar_taker': True,
                   'use_gap_exploit': False,
                   'use_inventory_bias': True,
                   'use_m14_gate': False}}

STRATEGY_CLASSES = {"hydro_mv_v5": HydroMVV5}

# ── Trader ────────────────────────────────────────────────────────────────────

class Trader:
    def __init__(self):
        self.strategies = {}
        for symbol, cfg in PRODUCTS.items():
            strat_name = cfg["strategy"]
            params = {k: v for k, v in cfg.items() if k != "strategy"}
            cls = STRATEGY_CLASSES[strat_name]
            self.strategies[symbol] = cls(product=symbol, params=params)

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        product_memories = saved.setdefault("products", {})
        shared = {"timestamp": state.timestamp}
        result = {}
        total_conversions = 0
        for product, strategy in self.strategies.items():
            if product not in state.order_depths:
                continue
            memory = product_memories.setdefault(product, {})
            memory["_shared"] = shared
            orders, conversions = strategy.on_tick(state, memory)
            result[product] = orders
            total_conversions += conversions
        for memory in product_memories.values():
            if isinstance(memory, dict):
                memory.pop("_shared", None)
        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)


# ── prosperity/strategies/round_4/hydro_mv_v6_invaware.py ─────────────────────────

class R4HydroMVV6InvAwareStrategy(HydroMVV5):
    """HYDRO v6: v5 core + trader-aware fair shift + inventory-aware taker edge.

    Key findings from the research loop:
    - The v5 passive core is strong and should remain intact.
    - Hard reversion guards and passive unwind degrade this family.
    - A small counterparty fair shift helps, but only when kept subtle.
    - The real new alpha comes from making AR takers more selective when our
      inventory is already loaded in that direction.
    """

    def _update_m14(self, state: TradingState, memory: Dict[str, object]) -> float:
        decay = float(self.params.get("trader_signal_decay", 0.78))
        alpha = float(self.params.get("trader_signal_alpha", 0.45))
        qty_norm = max(1e-9, float(self.params.get("trader_qty_norm", 10.0)))
        clip = max(1e-9, float(self.params.get("trader_signal_clip", 6.0)))
        buy_weights = self.params.get(
            "trader_buy_weights",
            {"Mark 14": 1.0, "Mark 38": -1.0},
        )
        sell_weights = self.params.get(
            "trader_sell_weights",
            {"Mark 14": -1.0, "Mark 38": 1.0},
        )

        raw = 0.0
        for trade in state.market_trades.get(self.product, []):
            raw += float(buy_weights.get(trade.buyer, 0.0)) * (trade.quantity / qty_norm)
            raw += float(sell_weights.get(trade.seller, 0.0)) * (trade.quantity / qty_norm)

        prev = float(memory.get("_m14_signal", 0.0))
        signal = decay * prev + alpha * raw
        signal = max(-clip, min(clip, signal))
        memory["_m14_signal"] = signal
        return signal

    def _inventory_limit(self) -> int:
        return max(1, int(self.params.get("working_position_limit", self.position_limit())))

    def _trader_signal_effect(
        self,
        signal: float,
        *,
        threshold_key: str,
        use_sign_key: str,
    ) -> float:
        threshold = float(self.params.get(threshold_key, 0.0))
        if abs(signal) < threshold:
            return 0.0
        if self.params.get(use_sign_key, False):
            return 1.0 if signal > 0 else -1.0
        return signal

    @staticmethod
    def _signal_conflicts_core(signal: float, dev: float) -> bool:
        return signal != 0.0 and dev != 0.0 and (signal * dev) > 0.0

    def _apply_trader_passive_skew(
        self,
        bid_size: float,
        ask_size: float,
        signal: float,
        dev: float,
    ) -> Tuple[float, float]:
        skew_per_unit = float(self.params.get("trader_passive_skew_per_unit", 0.0))
        if skew_per_unit <= 0.0:
            return bid_size, ask_size

        effect = self._trader_signal_effect(
            signal,
            threshold_key="trader_passive_skew_threshold",
            use_sign_key="trader_passive_skew_use_sign",
        )
        if effect == 0.0:
            return bid_size, ask_size

        skew = min(
            float(self.params.get("trader_passive_skew_max", 0.35)),
            abs(effect) * skew_per_unit,
        )
        if self._signal_conflicts_core(signal, dev):
            skew *= float(self.params.get("trader_passive_skew_conflict_mult", 1.0))
        if skew <= 0.0:
            return bid_size, ask_size

        if effect > 0.0:
            return bid_size * (1.0 + skew), ask_size * max(0.0, 1.0 - skew)
        return bid_size * max(0.0, 1.0 - skew), ask_size * (1.0 + skew)

    def _apply_inventory_taker_block(
        self,
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        block_ratio = float(self.params.get("inventory_same_side_taker_block_ratio", 0.0))
        if block_ratio <= 0.0:
            return buy_cap, sell_cap

        limit = self._inventory_limit()
        abs_ratio = abs(position) / limit
        if abs_ratio < block_ratio:
            return buy_cap, sell_cap

        if position > 0:
            buy_cap = 0
        elif position < 0:
            sell_cap = 0
        return buy_cap, sell_cap

    def _apply_inventory_live_fair_shift(
        self,
        mid_s: float,
        fair_value: float,
        position: int,
        memory: Dict[str, object],
    ) -> float:
        limit = self._inventory_limit()
        if limit <= 0 or position == 0:
            memory["_fair_defense_shift"] = 0.0
            return fair_value

        inv_ratio = min(1.0, abs(position) / limit)
        activation_ratio = float(self.params.get("inventory_fair_activation_ratio", 0.0))
        if inv_ratio < activation_ratio:
            memory["_fair_defense_shift"] = 0.0
            return fair_value

        gap_frac = float(self.params.get("inventory_fair_pull_fraction", 0.0))
        mom_gain = float(self.params.get("inventory_fair_ar_mom_cancel", 0.0))
        if gap_frac <= 0.0 and mom_gain <= 0.0:
            memory["_fair_defense_shift"] = 0.0
            return fair_value

        ar_mom = float(memory.get("_ar_momentum", 0.0))
        shift = 0.0
        if position < 0:
            adverse_gap = max(0.0, mid_s - fair_value)
            adverse_mom = max(0.0, ar_mom)
            shift += inv_ratio * gap_frac * adverse_gap
            shift += inv_ratio * mom_gain * adverse_mom
        else:
            adverse_gap = max(0.0, fair_value - mid_s)
            adverse_mom = max(0.0, -ar_mom)
            shift -= inv_ratio * gap_frac * adverse_gap
            shift -= inv_ratio * mom_gain * adverse_mom

        memory["_fair_defense_shift"] = shift
        return fair_value + shift

    def _apply_inventory_same_side_taker_kill(
        self,
        position: int,
        mid_s: float,
        fair_value: float,
        dev: float,
        buy_cap: int,
        sell_cap: int,
        memory: Dict[str, object],
    ) -> Tuple[int, int]:
        limit = self._inventory_limit()
        if limit <= 0 or position == 0:
            memory["_taker_kill_on"] = 0.0
            return buy_cap, sell_cap

        short_ratio = float(self.params.get("inventory_short_taker_kill_ratio", 0.0))
        long_ratio = float(self.params.get("inventory_long_taker_kill_ratio", short_ratio))
        dev_threshold = float(self.params.get("inventory_taker_kill_dev_threshold", 0.0))
        mom_threshold = float(self.params.get("inventory_taker_kill_mom_threshold", 0.0))
        if short_ratio <= 0.0 and long_ratio <= 0.0:
            memory["_taker_kill_on"] = 0.0
            return buy_cap, sell_cap

        inv_ratio = min(1.0, abs(position) / limit)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        kill_on = 0.0
        if position < 0 and short_ratio > 0.0 and inv_ratio >= short_ratio:
            if dev >= dev_threshold and ar_mom >= mom_threshold and mid_s >= fair_value:
                sell_cap = 0
                kill_on = -1.0
        elif position > 0 and long_ratio > 0.0 and inv_ratio >= long_ratio:
            if (-dev) >= dev_threshold and (-ar_mom) >= mom_threshold and mid_s <= fair_value:
                buy_cap = 0
                kill_on = 1.0

        memory["_taker_kill_on"] = kill_on
        return buy_cap, sell_cap

    def _apply_inventory_passive_repricing(
        self,
        orders: List[Order],
        position: int,
        *,
        best_bid: Optional[int],
        best_ask: Optional[int],
    ) -> List[Order]:
        if not orders:
            return orders

        limit = self._inventory_limit()
        pos_ratio = position / limit
        abs_ratio = abs(pos_ratio)

        soft_stop_ratio = float(self.params.get("inventory_passive_soft_stop_ratio", 0.0))
        shift_per_full = float(self.params.get("inventory_quote_shift_ticks_per_full", 0.0))
        shift_max = int(self.params.get("inventory_quote_shift_max_ticks", 0))
        unwind_ratio = float(self.params.get("inventory_passive_unwind_ratio", 0.0))
        unwind_ticks = int(self.params.get("inventory_passive_unwind_extra_ticks", 0))

        reservation_shift = 0
        if shift_per_full > 0.0:
            reservation_shift = int(round(-pos_ratio * shift_per_full))
            if shift_max > 0:
                reservation_shift = max(-shift_max, min(shift_max, reservation_shift))

        adjusted: List[Order] = []
        for order in orders:
            if (
                soft_stop_ratio > 0.0
                and abs_ratio >= soft_stop_ratio
                and ((position > 0 and order.quantity > 0) or (position < 0 and order.quantity < 0))
            ):
                continue

            price = int(order.price + reservation_shift)
            if unwind_ticks > 0 and unwind_ratio > 0.0 and abs_ratio >= unwind_ratio:
                if position > 0 and order.quantity < 0:
                    price -= unwind_ticks
                elif position < 0 and order.quantity > 0:
                    price += unwind_ticks

            if order.quantity > 0 and best_ask is not None:
                price = min(price, best_ask - 1)
            if order.quantity < 0 and best_bid is not None:
                price = max(price, best_bid + 1)

            adjusted.append(Order(self.product, price, order.quantity))

        bid_order = next((order for order in adjusted if order.quantity > 0), None)
        ask_order = next((order for order in adjusted if order.quantity < 0), None)
        if bid_order is not None and ask_order is not None and bid_order.price >= ask_order.price:
            if position > 0:
                ask_order.price = bid_order.price + 1
            else:
                bid_order.price = ask_order.price - 1

        return adjusted

    def _passive_sizes(self, position: int) -> Tuple[float, float]:
        official_limit = max(1, self.position_limit())
        inventory_limit = self._inventory_limit()
        base = float(self.params.get("maker_size_base_pct", 0.15)) * official_limit
        if not self.params.get("use_inventory_bias", True):
            return max(0.0, base), max(0.0, base)

        inv_ratio = min(1.0, abs(position) / inventory_limit)
        remaining = max(0.0, 1.0 - inv_ratio)
        same_side_power = float(self.params.get("inventory_same_side_power", 1.0))
        opposite_side_boost = float(self.params.get("inventory_opposite_side_boost", 1.0))
        opposite_side_cap_mult = float(self.params.get("inventory_opposite_side_cap_mult", 2.0))

        same_side_mult = remaining ** same_side_power if same_side_power > 0.0 else remaining
        opposite_side_mult = 1.0 + opposite_side_boost * (1.0 - same_side_mult)
        opposite_side_mult = min(opposite_side_mult, opposite_side_cap_mult)

        if position > 0:
            bid_size = base * same_side_mult
            ask_size = base * opposite_side_mult
        elif position < 0:
            bid_size = base * opposite_side_mult
            ask_size = base * same_side_mult
        else:
            bid_size = ask_size = base

        return max(0.0, bid_size), max(0.0, ask_size)

    def _ar_takers(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        mid_s: float,
        fair_value: float,
        dev: float,
        signal: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        if not self.params.get("use_ar_taker", False):
            return [], buy_cap, sell_cap, set(), set()

        base_edge = float(self.params.get("ar_taker_edge", 1.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.3))
        inv_shift = float(self.params.get("inventory_taker_edge_shift", 0.0))

        position = int(getattr(self, "_position_live", 0))
        limit = self._inventory_limit()
        inv_strength = min(1.0, abs(position) / limit)

        buy_edge = base_edge
        sell_edge = base_edge
        if inv_shift > 0.0 and inv_strength > 0.0:
            if position > 0:
                buy_edge += inv_shift * inv_strength
                sell_edge = max(0.5, sell_edge - inv_shift * inv_strength)
            elif position < 0:
                sell_edge += inv_shift * inv_strength
                buy_edge = max(0.5, buy_edge - inv_shift * inv_strength)

        trader_edge_per_unit = float(self.params.get("trader_taker_edge_per_unit", 0.0))
        if trader_edge_per_unit > 0.0:
            trader_effect = self._trader_signal_effect(
                signal,
                threshold_key="trader_taker_edge_threshold",
                use_sign_key="trader_taker_edge_use_sign",
            )
            if trader_effect != 0.0:
                trader_shift = abs(trader_effect) * trader_edge_per_unit
                if self._signal_conflicts_core(signal, dev):
                    trader_shift *= float(self.params.get("trader_taker_edge_conflict_mult", 1.0))
                if trader_effect > 0.0:
                    buy_edge = max(0.5, buy_edge - trader_shift)
                    sell_edge += trader_shift
                else:
                    sell_edge = max(0.5, sell_edge - trader_shift)
                    buy_edge += trader_shift

        buy_cap, sell_cap = self._apply_inventory_taker_block(position, buy_cap, sell_cap)
        buy_cap, sell_cap = self._apply_inventory_same_side_taker_kill(
            position,
            mid_s,
            fair_value,
            dev,
            buy_cap,
            sell_cap,
            memory=self._memory if hasattr(self, "_memory") else {},
        )

        orders: List[Order] = []
        buy_px: Set[int] = set()
        sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fair_value - buy_edge or buy_cap <= 0:
                break
            avail = -order_depth.sell_orders[ask_p]
            qty = min(avail, buy_cap, max(1, int(bid_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fair_value + sell_edge or sell_cap <= 0:
                break
            avail = order_depth.buy_orders[bid_p]
            qty = min(avail, sell_cap, max(1, int(ask_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, buy_px, sell_px

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, object],
    ) -> Tuple[List[Order], int]:
        mid = book.mid_price
        if mid is None:
            return [], 0

        mid_s, fair_value, dev = self._update_ar(float(mid), memory)
        sigma = self._update_volatility(float(mid), memory)
        signal = self._update_m14(state, memory)
        self._position_live = position

        fair_value = self._apply_inventory_live_fair_shift(mid_s, fair_value, position, memory)
        memory["_fair_value"] = fair_value

        fair_shift = float(self.params.get("trader_fair_shift_per_unit", 0.0))
        if fair_shift:
            fair_effect = signal
            if self._signal_conflicts_core(signal, dev):
                fair_effect *= float(self.params.get("trader_fair_shift_conflict_mult", 1.0))
            fair_value += fair_shift * fair_effect
            memory["_fair_value"] = fair_value

        if book.best_bid is not None:
            memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_prev_best_ask"] = book.best_ask

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        base_bid_size, base_ask_size = self._passive_sizes(position)
        bid_size, ask_size = self._apply_trader_passive_skew(base_bid_size, base_ask_size, signal, dev)

        guard_ok = self._guard_allows_taker(float(mid), position, memory)
        if guard_ok:
            taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._ar_takers(
                book,
                order_depth,
                mid_s,
                fair_value,
                dev,
                signal,
                base_bid_size,
                base_ask_size,
                buy_cap,
                sell_cap,
            )
        else:
            taker_orders, taker_buy_px, taker_sell_px = [], set(), set()

        gap_orders, buy_cap, sell_cap, gap_bid, gap_ask = self._gap_exploit(
            order_depth,
            memory,
            base_bid_size,
            base_ask_size,
            buy_cap,
            sell_cap,
            taker_buy_px,
            taker_sell_px,
        )

        class _FakeBook:
            best_bid = gap_bid if gap_bid is not None else book.best_bid
            best_ask = gap_ask if gap_ask is not None else book.best_ask

        passive_orders = self._passive_quotes(
            _FakeBook(),
            bid_size,
            ask_size,
            buy_cap,
            sell_cap,
            position,
            dev,
        )
        passive_orders = self._apply_inventory_passive_repricing(
            passive_orders,
            position,
            best_bid=_FakeBook.best_bid,
            best_ask=_FakeBook.best_ask,
        )

        passive_gated = self._apply_m14_gate(
            passive_orders,
            1 if signal > 0 else (-1 if signal < 0 else 0),
            position,
        )
        all_orders = taker_orders + gap_orders + passive_gated

        taker_sold = sum(-order.quantity for order in taker_orders if order.quantity < 0)
        taker_bought = sum(order.quantity for order in taker_orders if order.quantity > 0)
        anchor_val = float(memory.get("_anchor_ema", memory.get("_fair_base", fair_value)))
        memory["_viz_position"] = float(position)
        memory["_viz_bid_size"] = float(bid_size)
        memory["_viz_ask_size"] = float(ask_size)
        memory["_viz_taker_sell"] = float(taker_sold)
        memory["_viz_taker_buy"] = float(taker_bought)
        memory["_viz_anchor"] = anchor_val

        extras = {
            "position": position,
            "Position": position,
            "mid": round(float(mid), 2),
            "fair_value": round(fair_value, 3),
            "FairValue": round(fair_value, 3),
            "Anchor": round(anchor_val, 3),
            "deviation": round(dev, 3),
            "DevSmooth": round(dev, 3),
            "ar_mom": round(float(memory.get("_ar_momentum", 0.0)), 4),
            "guard": int(guard_ok),
            "Guard": int(guard_ok),
            "m14_signal": round(signal, 3),
            "M14Signal": round(signal, 3),
            "taker_sell": taker_sold,
            "taker_buy": taker_bought,
            "bid_size": int(bid_size),
            "ask_size": int(ask_size),
            "sigma": round(sigma, 4),
        }
        if (fair_base := memory.get("_fair_base")) is not None:
            extras["FairBase"] = round(float(fair_base), 3)
        if (confidence := memory.get("_anchor_confidence")) is not None:
            extras["AnchorConfidence"] = round(float(confidence), 4)
        if (drift := memory.get("_anchor_drift_ewma")) is not None:
            extras["AnchorDriftEwma"] = round(float(drift), 4)
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=None,
            ask_price=None,
            extras=extras,
        )
        return all_orders, 0

    def feature_prices(self, memory: Dict[str, object]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value")) is not None:
            out["FairValue"] = float(v)
        if (v := memory.get("_dev_smooth")) is not None:
            out["DevSmooth"] = float(v)
        if (v := memory.get("_m14_signal")) is not None:
            out["M14Signal"] = float(v)
        if (v := memory.get("_anchor_ema")) is not None:
            out["Anchor"] = float(v)
        if (v := memory.get("_ar_momentum")) is not None:
            out["ar_mom"] = float(v)
        if (v := memory.get("_guard_on")) is not None:
            out["guard"] = float(v)
        if (v := memory.get("_viz_position")) is not None:
            out["Position"] = float(v)
        if (v := memory.get("_viz_bid_size")) is not None:
            out["bid_size"] = float(v)
        if (v := memory.get("_viz_ask_size")) is not None:
            out["ask_size"] = float(v)
        if (v := memory.get("_viz_taker_sell")) is not None:
            out["taker_sell"] = float(v)
        if (v := memory.get("_viz_taker_buy")) is not None:
            out["taker_buy"] = float(v)
        if (v := memory.get("_fair_base")) is not None:
            out["FairBase"] = float(v)
        if (v := memory.get("_anchor_confidence")) is not None:
            out["AnchorConfidence"] = float(v)
        if (v := memory.get("_anchor_drift_ewma")) is not None:
            out["AnchorDriftEwma"] = float(v)
        if (v := memory.get("_fair_defense_shift")) is not None:
            out["FairDefenseShift"] = float(v)
        if (v := memory.get("_taker_kill_on")) is not None:
            out["TakerKillOn"] = float(v)
        return out


# ── prosperity/strategies/round_4/hydro_mv_v9_adaptive_fair.py ────────────────────

class R4HydroMVV9AdaptiveFairStrategy(R4HydroMVV6InvAwareStrategy):
    """HYDRO v9: v8 core + confidence-weighted fair that tracks persistent drift.

    The baseline v8 fair stays tightly anchored near 10000, which is great when
    HYDRO mean-reverts around the anchor but can become too directional when the
    market trends away for a long time. v9 keeps the same MM core and trader
    overlays, but makes the anchor "softer":

    - when smoothed drift versus 10000 is small, fair stays mostly anchored
    - when drift persists, fair partially follows the market
    - a floor on anchor confidence preserves the profitable mean-reversion core
    """

    def _update_ar(
        self,
        raw_mid: float,
        memory: Dict[str, object],
    ) -> tuple[float, float, float]:
        ms_hl = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        ar_hl = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        ar_mom = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        anchor_fixed = float(self.params.get("anchor_price", 10000.0))
        drift = mid_s - anchor_fixed
        drift_alpha = float(self.params.get("adaptive_drift_alpha", 0.004))
        prev_drift = float(memory.get("_anchor_drift_ewma", 0.0))
        drift_ewma = drift_alpha * drift + (1.0 - drift_alpha) * prev_drift
        memory["_anchor_drift_ewma"] = drift_ewma

        mean_rev = float(self.params.get("adaptive_mean_rev", 4.0))
        trend = float(self.params.get("adaptive_trend", 50.0))
        abs_drift = abs(drift_ewma)
        if abs_drift <= mean_rev:
            confidence = 1.0
        elif abs_drift >= trend:
            confidence = 0.0
        else:
            confidence = 1.0 - (abs_drift - mean_rev) / max(1e-9, trend - mean_rev)

        confidence = max(
            float(self.params.get("adaptive_conf_min", 0.45)),
            min(float(self.params.get("adaptive_conf_max", 1.0)), confidence),
        )
        memory["_anchor_confidence"] = confidence

        fair_base = confidence * anchor_fixed + (1.0 - confidence) * mid_s
        memory["_anchor_ema"] = fair_base
        memory["_fair_base"] = fair_base

        ar_gain = float(self.params.get("ar_gain", 7.0))
        fair_value = fair_base - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev = mid_s - fair_value
        dev_hl = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s = float(memory.get("_dev_smooth", raw_dev))
        dev_s = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s
        memory["_dev_raw"] = raw_dev
        return mid_s, fair_value, dev_s

    def feature_prices(self, memory: Dict[str, object]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (v := memory.get("_fair_base")) is not None:
            out["FairBase"] = float(v)
        if (v := memory.get("_anchor_confidence")) is not None:
            out["AnchorConfidence"] = float(v)
        if (v := memory.get("_anchor_drift_ewma")) is not None:
            out["AnchorDriftEwma"] = float(v)
        return out


# ── prosperity/strategies/round_4/hydro_mv_v10_live_defensive.py ──────────────────

class R4HydroMVV10LiveDefensiveStrategy(R4HydroMVV9AdaptiveFairStrategy):
    """HYDRO v10: v9 adaptive fair plus a very late same-side taker airbag.

    Research finding:
    - The dominant live failure mode was not passive quoting itself, but
      aggressive same-side takers that kept pressing inventory into a trend.
    - Fully reactive fair-following kills the historical edge.
    - The best compromise is therefore:
      - keep the v9 adaptive anchor/fair engine,
      - add a modest inventory-triggered fair pull,
      - and only disable same-side takers at near-limit inventory in an
        adverse-trend regime.

    v10 is intentionally conservative: the taker kill-switch should behave like
    an airbag, not like a primary signal.
    """


# ── prosperity/strategies/round_4/hydro_mv_v11_early_kill_fairsoft.py ─────────────

class R4HydroMVV11EarlyKillFairSoftStrategy(R4HydroMVV10LiveDefensiveStrategy):
    """HYDRO v11: v10 with earlier taker airbag and a slightly softer fair.

    Design goal:
    - v10 was too late to matter in the problematic live regime; the first real
      order-level behavior change happened only once inventory was already very
      short.
    - v11 keeps the same core engine, but activates the same-side taker airbag
      earlier and lets fair follow persistent drift a bit more when inventory is
      already loaded.

    This remains intentionally conservative:
    - no hard inventory clamp,
    - no full fair-following,
    - no timestamp-specific behavior.
    """

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'adaptive_conf_min': 0.5,
                   'adaptive_drift_alpha': 0.005,
                   'adaptive_mean_rev': 4.0,
                   'adaptive_trend': 50.0,
                   'anchor_price': 10000,
                   'ar_gain': 7.0,
                   'ar_smooth_half_life': 5,
                   'ar_taker_edge': 12.0,
                   'ar_taker_size_pct': 0.3,
                   'dev_smooth_half_life': 5,
                   'informed_trader_name': 'Mark 14',
                   'inventory_fair_activation_ratio': 0.5,
                   'inventory_fair_ar_mom_cancel': 3.0,
                   'inventory_fair_pull_fraction': 0.18,
                   'inventory_long_taker_kill_ratio': 0.9,
                   'inventory_opposite_side_boost': 1.0,
                   'inventory_opposite_side_cap_mult': 2.0,
                   'inventory_same_side_power': 1.5,
                   'inventory_short_taker_kill_ratio': 0.9,
                   'inventory_taker_edge_shift': 4.0,
                   'inventory_taker_kill_dev_threshold': 8.0,
                   'inventory_taker_kill_mom_threshold': 0.1,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'maker_size_base_pct': 0.3,
                   'mid_smooth_half_life': 18,
                   'passive_quoting': True,
                   'pct_kept_for_takers': 0.2,
                   'position_limit': 200,
                   'strategy': 'r4_hydro_mv_v11_early_kill_fairsoft',
                   'tighten_ticks': 1,
                   'trader_buy_weights': {'Mark 14': 1.0, 'Mark 38': -1.0},
                   'trader_fair_shift_per_unit': 1.1,
                   'trader_qty_norm': 10.0,
                   'trader_sell_weights': {'Mark 14': -1.0, 'Mark 38': 1.0},
                   'trader_signal_alpha': 0.45,
                   'trader_signal_clip': 6.0,
                   'trader_signal_decay': 0.93,
                   'ts_increment': 100,
                   'use_anchor_guard': False,
                   'use_ar_quote_bias': False,
                   'use_ar_taker': True,
                   'use_gap_exploit': False,
                   'use_inventory_bias': True,
                   'use_m14_gate': False,
                   'working_position_limit': 200}}

STRATEGY_CLASSES = {"r4_hydro_mv_v11_early_kill_fairsoft": R4HydroMVV11EarlyKillFairSoftStrategy}

# ── Trader ────────────────────────────────────────────────────────────────────

class Trader:
    def __init__(self):
        self.strategies = {}
        for symbol, cfg in PRODUCTS.items():
            strat_name = cfg["strategy"]
            params = {k: v for k, v in cfg.items() if k != "strategy"}
            cls = STRATEGY_CLASSES[strat_name]
            self.strategies[symbol] = cls(product=symbol, params=params)

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        product_memories = saved.setdefault("products", {})
        shared = {"timestamp": state.timestamp}
        result = {}
        total_conversions = 0
        for product, strategy in self.strategies.items():
            if product not in state.order_depths:
                continue
            memory = product_memories.setdefault(product, {})
            memory["_shared"] = shared
            orders, conversions = strategy.on_tick(state, memory)
            result[product] = orders
            total_conversions += conversions
        for memory in product_memories.values():
            if isinstance(memory, dict):
                memory.pop("_shared", None)
        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)
