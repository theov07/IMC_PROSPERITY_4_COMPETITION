from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Tuple
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


# ── prosperity/strategies/round_3/hydro_reversion_mm.py ───────────────────────────

class R3HydroReversionMMStrategy(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.mid_price is None:
            return [], 0

        mid = float(book.mid_price)
        ema, fast_ema = self._update_emas(mid, memory)
        deviation = mid - ema
        trend = fast_ema - ema  # positive = uptrend, negative = downtrend
        prev_trend = float(memory.get("prev_trend", trend))
        trend_change = trend - prev_trend
        realized, unrealized = self._update_inventory_pnl(state, mid, position, memory)
        risk = self._risk_context(int(state.timestamp), position, trend, trend_change, realized, unrealized, memory)
        eod = self._eod_context(int(state.timestamp))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        bid_price, ask_price = self._quote_prices(book)
        bid_price, ask_price = self._apply_risk_quote_prices(position, bid_price, ask_price, book, risk)
        bid_size, ask_size = self._quote_sizes(position, deviation, trend)
        bid_size, ask_size = self._apply_risk_quote_controls(position, bid_size, ask_size, risk)
        bid_size, ask_size = self._apply_eod_quote_controls(position, bid_size, ask_size, eod)

        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            sell_cap -= qty

        take_order = self._take_order(state, book, position, deviation, trend, memory, buy_cap, sell_cap, risk)
        if take_order is not None:
            orders.append(take_order)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price if bid_size > 0 else None,
            ask_price=ask_price if ask_size > 0 else None,
            extras={
                "ema": round(ema, 2),
                "dev": round(deviation, 2),
                "trend": round(trend, 2),
                "trend_change": round(trend_change, 2),
                "realized": round(realized, 2),
                "unrealized": round(unrealized, 2),
                "risk": int(risk is not None),
                "risk_cap": risk["target_position"] if risk is not None else None,
                "eod_cap": eod["position_cap"] if eod is not None else None,
                "bid_size": bid_size,
                "ask_size": ask_size,
            },
        )
        memory["dev"] = deviation
        memory["prev_trend"] = trend
        return orders, 0

    def _update_emas(self, mid: float, memory: Dict[str, Any]) -> tuple[float, float]:
        slow_alpha = float(self.params.get("ema_alpha", 0.008))
        fast_alpha = float(self.params.get("fast_ema_alpha", 0.03))
        ema = memory.get("ema")
        fast_ema = memory.get("fast_ema")
        ema = mid if ema is None else slow_alpha * mid + (1.0 - slow_alpha) * float(ema)
        fast_ema = mid if fast_ema is None else fast_alpha * mid + (1.0 - fast_alpha) * float(fast_ema)
        memory["ema"] = ema
        memory["fast_ema"] = fast_ema
        return ema, fast_ema

    def _quote_prices(self, book: BookSnapshot) -> tuple[int, int]:
        tighten = int(self.params.get("tighten_ticks", 1))
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(int(book.best_bid) + tighten, int(book.best_ask) - 1)
            ask = max(int(book.best_ask) - tighten, int(book.best_bid) + 1)
        return bid, ask

    def _apply_risk_quote_prices(
        self,
        position: int,
        bid_price: int,
        ask_price: int,
        book: BookSnapshot,
        risk: Dict[str, float] | None,
    ) -> tuple[int, int]:
        if risk is None or book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price

        tighten = int(self.params.get("risk_unwind_tighten_ticks", 4))
        leave_gap = int(self.params.get("risk_unwind_leave_gap_ticks", 1))

        if position < 0:
            bid_ceiling = int(book.best_ask) - leave_gap
            if bid_ceiling < int(book.best_bid):
                bid_ceiling = int(book.best_bid)
            bid_price = min(int(book.best_bid) + tighten, bid_ceiling)
        elif position > 0:
            ask_floor = int(book.best_bid) + leave_gap
            if ask_floor > int(book.best_ask):
                ask_floor = int(book.best_ask)
            ask_price = max(int(book.best_ask) - tighten, ask_floor)

        return bid_price, ask_price

    def _quote_sizes(self, position: int, deviation: float, trend: float) -> tuple[int, int]:
        maker = int(self.params.get("maker_size", 24))
        min_size = int(self.params.get("min_maker_size", 3))
        quote_threshold = float(self.params.get("quote_threshold", 6.0))
        signal_boost = int(self.params.get("max_signal_size_boost", 12))
        trend_guard = float(self.params.get("trend_guard", 8.0))
        # Position gate: don't fire directional signal if already too far in that direction
        pos_gate = int(self.params.get("signal_pos_gate", 12))
        reduce_per_unit = float(self.params.get("inventory_reduce_per_unit", 0.40))
        unwind_per_unit = float(self.params.get("inventory_unwind_per_unit", 0.30))
        unwind_boost = int(self.params.get("max_unwind_boost", 20))

        bid_size = maker
        ask_size = maker
        # Symmetric trend guard: only fire mean-rev signal when market is NOT strongly trending
        # in either direction. Prevents false signals during V-shaped recoveries.
        if abs(trend) < trend_guard:
            if deviation > quote_threshold and position > -pos_gate:
                bid_size = 0
                ask_size = maker + min(signal_boost, int(abs(deviation) // 4))
            elif deviation < -quote_threshold and position < pos_gate:
                ask_size = 0
                bid_size = maker + min(signal_boost, int(abs(deviation) // 4))

        if position > 0:
            bid_size = max(0, bid_size - int(position * reduce_per_unit))
            ask_size += min(unwind_boost, int(position * unwind_per_unit))
        elif position < 0:
            ask_size = max(0, ask_size - int(-position * reduce_per_unit))
            bid_size += min(unwind_boost, int(-position * unwind_per_unit))

        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size
        return max(0, bid_size), max(0, ask_size)

    def _update_inventory_pnl(
        self,
        state: TradingState,
        mid: float,
        position: int,
        memory: Dict[str, Any],
    ) -> tuple[float, float]:
        tracked_pos = int(memory.get("tracked_pos", 0))
        avg_cost = float(memory.get("avg_cost", 0.0))
        realized = float(memory.get("realized_pnl", 0.0))

        for trade in state.own_trades.get(self.product, []):
            qty = int(trade.quantity)
            price = float(trade.price)

            if trade.buyer == "SUBMISSION":
                if tracked_pos >= 0:
                    new_pos = tracked_pos + qty
                    avg_cost = ((avg_cost * tracked_pos) + (price * qty)) / new_pos if new_pos else 0.0
                    tracked_pos = new_pos
                else:
                    cover = min(qty, -tracked_pos)
                    realized += (avg_cost - price) * cover
                    tracked_pos += cover
                    remainder = qty - cover
                    if tracked_pos == 0:
                        avg_cost = 0.0
                    if remainder > 0:
                        tracked_pos = remainder
                        avg_cost = price
            elif trade.seller == "SUBMISSION":
                if tracked_pos <= 0:
                    new_abs_pos = (-tracked_pos) + qty
                    avg_cost = ((avg_cost * (-tracked_pos)) + (price * qty)) / new_abs_pos if new_abs_pos else 0.0
                    tracked_pos -= qty
                else:
                    close = min(qty, tracked_pos)
                    realized += (price - avg_cost) * close
                    tracked_pos -= close
                    remainder = qty - close
                    if tracked_pos == 0:
                        avg_cost = 0.0
                    if remainder > 0:
                        tracked_pos = -remainder
                        avg_cost = price

        if tracked_pos != position:
            tracked_pos = position
            if tracked_pos == 0:
                avg_cost = 0.0
            elif avg_cost == 0.0:
                avg_cost = mid

        if tracked_pos > 0:
            unrealized = (mid - avg_cost) * tracked_pos
        elif tracked_pos < 0:
            unrealized = (avg_cost - mid) * (-tracked_pos)
        else:
            unrealized = 0.0

        memory["tracked_pos"] = tracked_pos
        memory["avg_cost"] = avg_cost
        memory["realized_pnl"] = realized
        memory["unrealized_pnl"] = unrealized
        return realized, unrealized

    def _risk_context(
        self,
        timestamp: int,
        position: int,
        trend: float,
        trend_change: float,
        realized: float,
        unrealized: float,
        memory: Dict[str, Any],
    ) -> Dict[str, float] | None:
        threshold = self.params.get("risk_abs_position_threshold")
        if threshold is None:
            return None

        high_pos = int(threshold)
        if abs(position) < high_pos:
            memory["risk_peak_side"] = 0
            memory["risk_peak_unrealized"] = max(0.0, unrealized)
            memory["risk_peak_unrealized_ts"] = timestamp
            return None

        progress_threshold = float(self.params.get("risk_realized_progress_threshold", 8.0))
        anchor = float(memory.get("risk_realized_anchor", realized))
        anchor_ts = int(memory.get("risk_realized_anchor_ts", timestamp))
        if realized >= anchor + progress_threshold:
            anchor = realized
            anchor_ts = timestamp
        memory["risk_realized_anchor"] = anchor
        memory["risk_realized_anchor_ts"] = anchor_ts

        side = 1 if position > 0 else -1
        peak_side = int(memory.get("risk_peak_side", 0))
        peak_unrealized = float(memory.get("risk_peak_unrealized", max(0.0, unrealized)))
        peak_ts = int(memory.get("risk_peak_unrealized_ts", timestamp))
        if side != peak_side:
            peak_unrealized = max(0.0, unrealized)
            peak_ts = timestamp
            peak_side = side
        elif unrealized > peak_unrealized:
            peak_unrealized = unrealized
            peak_ts = timestamp
        memory["risk_peak_side"] = peak_side
        memory["risk_peak_unrealized"] = peak_unrealized
        memory["risk_peak_unrealized_ts"] = peak_ts

        active_until = int(memory.get("risk_active_until_ts", -10**9))
        target_position = int(self.params.get("risk_target_position", max(1, high_pos // 2)))
        if timestamp <= active_until and abs(position) > target_position:
            return {
                "target_position": target_position,
                "giveback": max(0.0, peak_unrealized - unrealized),
            }

        stall_ts = int(self.params.get("risk_realized_stall_ts", 4000))
        peak_min = float(self.params.get("risk_unrealized_peak_min", 150.0))
        giveback_threshold = float(self.params.get("risk_unrealized_giveback_threshold", 180.0))
        giveback_window_ts = int(self.params.get("risk_giveback_window_ts", 15000))
        adverse_trend_threshold = float(self.params.get("risk_adverse_trend_threshold", 2.0))
        trend_turn_threshold = float(self.params.get("risk_trend_turn_threshold", 1.2))
        force_giveback_threshold = float(self.params.get("risk_force_giveback_threshold", 300.0))
        hold_ts = int(self.params.get("risk_hold_ts", 6000))

        realized_stalled = timestamp - anchor_ts >= stall_ts
        giveback = peak_unrealized - unrealized
        quick_giveback = peak_unrealized >= peak_min and giveback >= giveback_threshold and timestamp - peak_ts <= giveback_window_ts
        adverse_trend = trend >= adverse_trend_threshold if position < 0 else trend <= -adverse_trend_threshold
        adverse_turn = trend_change >= trend_turn_threshold if position < 0 else trend_change <= -trend_turn_threshold

        if realized_stalled and quick_giveback and (adverse_trend or adverse_turn or giveback >= force_giveback_threshold):
            memory["risk_active_until_ts"] = timestamp + hold_ts
            memory["risk_last_trigger_ts"] = timestamp
            return {
                "target_position": target_position,
                "giveback": giveback,
            }

        return None

    def _apply_risk_quote_controls(
        self,
        position: int,
        bid_size: int,
        ask_size: int,
        risk: Dict[str, float] | None,
    ) -> tuple[int, int]:
        if risk is None:
            return bid_size, ask_size

        bonus = int(self.params.get("risk_unwind_size_bonus", 14))
        if position < 0:
            bid_size += bonus
            ask_size = 0
        elif position > 0:
            ask_size += bonus
            bid_size = 0
        return max(0, bid_size), max(0, ask_size)

    def _eod_context(self, timestamp: int) -> Dict[str, float] | None:
        start_ts = self.params.get("eod_start_ts")
        if start_ts is None:
            return None

        start = int(start_ts)
        end = int(self.params.get("eod_end_ts", start))
        if timestamp < start:
            return None

        if end <= start:
            progress = 1.0
        else:
            progress = min(1.0, max(0.0, (timestamp - start) / float(end - start)))

        start_cap = int(self.params.get("eod_start_pos_limit", self.params.get("signal_pos_gate", 12)))
        end_cap = int(self.params.get("eod_end_pos_limit", 0))
        cap = int(round(start_cap + (end_cap - start_cap) * progress))
        return {
            "progress": progress,
            "position_cap": max(0, cap),
        }

    def _apply_eod_quote_controls(
        self,
        position: int,
        bid_size: int,
        ask_size: int,
        eod: Dict[str, float] | None,
    ) -> tuple[int, int]:
        if eod is None:
            return bid_size, ask_size

        progress = float(eod["progress"])
        cap = int(eod["position_cap"])
        bonus = int(round(progress * float(self.params.get("eod_unwind_size_bonus", 12))))

        if position < 0:
            bid_size += bonus
            ask_size = int(round(ask_size * max(0.0, 1.0 - progress)))
            if -position >= cap:
                ask_size = 0
        elif position > 0:
            ask_size += bonus
            bid_size = int(round(bid_size * max(0.0, 1.0 - progress)))
            if position >= cap:
                bid_size = 0

        return max(0, bid_size), max(0, ask_size)

    def _take_order(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        deviation: float,
        trend: float,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        risk: Dict[str, float] | None,
    ) -> Order | None:
        if risk is not None:
            risk_take = self._risk_take_order(
                state=state,
                book=book,
                position=position,
                memory=memory,
                buy_cap=buy_cap,
                sell_cap=sell_cap,
                risk=risk,
            )
            if risk_take is not None:
                return risk_take

        eod = self._eod_context(int(state.timestamp))
        if eod is not None:
            eod_take = self._eod_take_order(
                state=state,
                book=book,
                position=position,
                memory=memory,
                buy_cap=buy_cap,
                sell_cap=sell_cap,
                eod=eod,
            )
            if eod_take is not None:
                return eod_take

        threshold = float(self.params.get("take_threshold", 12.0))
        trend_guard = float(self.params.get("trend_guard", 8.0))
        pos_gate = int(self.params.get("signal_pos_gate", 12))
        cooldown_ts = int(self.params.get("take_cooldown_ts", 2000))
        take_size = int(self.params.get("take_size", 1))
        last_take_ts = int(memory.get("last_take_ts", -10**9))

        if int(state.timestamp) - last_take_ts < cooldown_ts:
            return None

        if abs(trend) < trend_guard:
            if deviation > threshold and position > -pos_gate and sell_cap > 0:
                qty = min(take_size, sell_cap, pos_gate + position)
                if qty > 0:
                    memory["last_take_ts"] = int(state.timestamp)
                    return Order(self.product, int(book.best_bid), -qty)

            if deviation < -threshold and position < pos_gate and buy_cap > 0:
                qty = min(take_size, buy_cap, pos_gate - position)
                if qty > 0:
                    memory["last_take_ts"] = int(state.timestamp)
                    return Order(self.product, int(book.best_ask), qty)

        return None

    def _risk_take_order(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        risk: Dict[str, float],
    ) -> Order | None:
        take_size = int(self.params.get("risk_take_size", 0))
        if take_size <= 0:
            return None

        target_position = int(risk["target_position"])
        cooldown_ts = int(self.params.get("risk_take_cooldown_ts", 800))
        last_take_ts = int(memory.get("last_risk_take_ts", -10**9))

        if int(state.timestamp) - last_take_ts < cooldown_ts:
            return None

        if position < -target_position and buy_cap > 0:
            qty = min(take_size, buy_cap, -position - target_position)
            if qty > 0:
                memory["last_risk_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_ask), qty)

        if position > target_position and sell_cap > 0:
            qty = min(take_size, sell_cap, position - target_position)
            if qty > 0:
                memory["last_risk_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_bid), -qty)

        return None

    def _eod_take_order(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        eod: Dict[str, float],
    ) -> Order | None:
        cap = int(eod["position_cap"])
        if cap < 0:
            return None

        cooldown_ts = int(self.params.get("eod_take_cooldown_ts", 1000))
        take_size = int(self.params.get("eod_take_size", 1))
        excess_threshold = int(self.params.get("eod_take_excess_threshold", 0))
        last_take_ts = int(memory.get("last_eod_take_ts", -10**9))

        if int(state.timestamp) - last_take_ts < cooldown_ts:
            return None

        if position < -(cap + excess_threshold) and buy_cap > 0:
            qty = min(take_size, buy_cap, -position - cap)
            if qty > 0:
                memory["last_eod_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_ask), qty)

        if position > cap + excess_threshold and sell_cap > 0:
            qty = min(take_size, sell_cap, position - cap)
            if qty > 0:
                memory["last_eod_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_bid), -qty)

        return None

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if "ema" in memory:
            out["HydroEMA"] = float(memory["ema"])
        if "fast_ema" in memory:
            out["HydroFastEMA"] = float(memory["fast_ema"])
        if "dev" in memory:
            out["HydroDev"] = float(memory["dev"])
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'ema_alpha': 0.008,
                   'eod_end_pos_limit': 0,
                   'eod_end_ts': 99900,
                   'eod_start_pos_limit': 28,
                   'eod_start_ts': 85000,
                   'eod_take_cooldown_ts': 500,
                   'eod_take_size': 1,
                   'eod_unwind_size_bonus': 12,
                   'fast_ema_alpha': 0.03,
                   'inventory_reduce_per_unit': 0.4,
                   'inventory_unwind_per_unit': 0.3,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 20,
                   'max_signal_size_boost': 12,
                   'max_unwind_boost': 20,
                   'min_maker_size': 3,
                   'position_limit': 200,
                   'quote_threshold': 6.0,
                   'risk_abs_position_threshold': 20,
                   'risk_adverse_trend_threshold': 3.0,
                   'risk_force_giveback_threshold': 420.0,
                   'risk_giveback_window_ts': 18000,
                   'risk_hold_ts': 4000,
                   'risk_realized_progress_threshold': 10.0,
                   'risk_realized_stall_ts': 5000,
                   'risk_take_size': 0,
                   'risk_target_position': 14,
                   'risk_trend_turn_threshold': 1.6,
                   'risk_unrealized_giveback_threshold': 220.0,
                   'risk_unrealized_peak_min': 180.0,
                   'risk_unwind_leave_gap_ticks': 1,
                   'risk_unwind_size_bonus': 8,
                   'risk_unwind_tighten_ticks': 4,
                   'signal_pos_gate': 28,
                   'strategy': 'r3_hydro_reversion_mm',
                   'take_cooldown_ts': 3000,
                   'take_size': 1,
                   'take_threshold': 8.0,
                   'tighten_ticks': 1,
                   'trend_guard': 6.0,
                   'ts_increment': 100}}

STRATEGY_CLASSES = {"r3_hydro_reversion_mm": R3HydroReversionMMStrategy}

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
