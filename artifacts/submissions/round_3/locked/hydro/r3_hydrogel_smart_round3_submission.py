from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Optional, Tuple
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


# ── prosperity/strategies/round_3/hydrogel_smart_mm.py ────────────────────────────

class HydrogelSmartMMStrategy(BaseStrategy):
    """Theo's base + confirmed-reversal exit at extreme |dev|."""

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

        p = self._read_params()
        mid = float(book.mid_price)
        prev_mid = memory.get("_prev_mid", mid)
        memory["_prev_mid"] = mid

        # Track mid direction: +1 if mid > prev, -1 if <, 0 if flat
        if mid > prev_mid:
            tick_dir = 1
        elif mid < prev_mid:
            tick_dir = -1
        else:
            tick_dir = 0

        # Track consecutive same-direction ticks (used for reversal confirmation)
        prev_dir = int(memory.get("_dir", 0))
        if tick_dir != 0 and tick_dir == prev_dir:
            memory["_dir_streak"] = int(memory.get("_dir_streak", 0)) + 1
        elif tick_dir != 0 and tick_dir != prev_dir:
            memory["_dir_streak"] = 1
            memory["_dir"] = tick_dir
        # else flat tick, don't update streak
        if tick_dir != 0:
            memory["_dir"] = tick_dir
        dir_streak = int(memory.get("_dir_streak", 0))
        cur_dir = int(memory.get("_dir", 0))

        # Dual EMA + trend (Theo's)
        ema = memory.get("ema", mid)
        fast_ema = memory.get("fast_ema", mid)
        ema = p["ema_alpha"] * mid + (1 - p["ema_alpha"]) * ema
        fast_ema = p["fast_ema_alpha"] * mid + (1 - p["fast_ema_alpha"]) * fast_ema
        deviation = mid - ema
        trend = fast_ema - ema
        memory["ema"] = ema
        memory["fast_ema"] = fast_ema
        memory["_dev"] = deviation
        memory["_trend"] = trend

        # Track cumulative session range (for adaptive pos_gate)
        session_max = max(memory.get("_session_max", mid), mid)
        session_min = min(memory.get("_session_min", mid), mid)
        memory["_session_max"] = session_max
        memory["_session_min"] = session_min
        cum_range = session_max - session_min
        memory["_cum_range"] = cum_range

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._quote_sizes(position, deviation, trend, p, cum_range)

        # Léo's session-drift bias
        bias = self._session_drift_bias(state, p)
        if bias > 0:
            bid_size = max(0, bid_size - bias)
            ask_size = ask_size + bias if ask_size > 0 else ask_size
        elif bias < 0:
            bid_size = bid_size + (-bias)
            ask_size = max(0, ask_size + bias)
        memory["_session_bias"] = bias

        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            sell_cap -= qty

        # Theo's tiny passive taker (always available, fires on |dev|>=12)
        passive_take = self._passive_take_order(state, book, position, deviation, trend, memory, buy_cap, sell_cap, p)
        if passive_take is not None:
            orders.append(passive_take)
            # update buy_cap/sell_cap for confirmed-reversal taker below
            if passive_take.quantity > 0:
                buy_cap -= passive_take.quantity
            else:
                sell_cap += passive_take.quantity  # quantity is negative

        # Confirmed-reversal taker (NEW: only at extreme + reversing)
        cr_take = self._confirmed_reversal_take(
            state, book, position, deviation, trend, cur_dir, dir_streak,
            memory, buy_cap, sell_cap, p,
        )
        if cr_take is not None:
            orders.append(cr_take)

        memory["_dir_streak_log"] = dir_streak
        return orders, 0

    # ── Theo's quoting (unchanged) ───────────────────────────────────────

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, book.best_bid + 1)
        return bid, ask

    def _quote_sizes(
        self,
        position: int,
        deviation: float,
        trend: float,
        p: Dict[str, Any],
        cum_range: float = 0.0,
    ) -> Tuple[int, int]:
        maker = p["maker_size"]
        min_size = p["min_maker_size"]
        quote_thr = p["quote_threshold"]
        signal_boost = p["max_signal_size_boost"]
        trend_guard = p["trend_guard"]
        # Adaptive pos_gate: scale up when range is high (day 2-like)
        pos_gate = p["signal_pos_gate"]
        if p.get("adaptive_pos_gate", False):
            range_thr = p.get("adaptive_pos_gate_range_thr", 60.0)
            max_gate = p.get("adaptive_pos_gate_max", 18)
            if cum_range > range_thr:
                # Linear from pos_gate (at range_thr) to max_gate (at range_thr*1.5)
                full_thr = range_thr * 1.5
                if cum_range >= full_thr:
                    pos_gate = max_gate
                else:
                    frac = (cum_range - range_thr) / (full_thr - range_thr)
                    pos_gate = int(p["signal_pos_gate"] + frac * (max_gate - p["signal_pos_gate"]))
        reduce_per = p["inventory_reduce_per_unit"]
        unwind_per = p["inventory_unwind_per_unit"]
        unwind_boost = p["max_unwind_boost"]

        bid_size = maker
        ask_size = maker

        if abs(trend) < trend_guard:
            if deviation > quote_thr and position > -pos_gate:
                bid_size = 0
                ask_size = maker + min(signal_boost, int(abs(deviation) // 4))
            elif deviation < -quote_thr and position < pos_gate:
                ask_size = 0
                bid_size = maker + min(signal_boost, int(abs(deviation) // 4))

        if position > 0:
            bid_size = max(0, bid_size - int(position * reduce_per))
            ask_size += min(unwind_boost, int(position * unwind_per))
        elif position < 0:
            ask_size = max(0, ask_size - int(-position * reduce_per))
            bid_size += min(unwind_boost, int(-position * unwind_per))

        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size
        return max(0, bid_size), max(0, ask_size)

    def _session_drift_bias(self, state: TradingState, p: Dict[str, Any]) -> int:
        bias = int(p.get("session_drift_bias", 0))
        if bias == 0:
            return 0
        ts = int(state.timestamp)
        early = int(p["session_bias_strong_until_ts"])
        fade = int(p["session_bias_fade_until_ts"])
        if ts < early:
            return bias
        elif ts < fade:
            return int(bias * (1.0 - (ts - early) / (fade - early)))
        return 0

    # ── Theo's passive taker (size=1 base, fires on |dev|>=12) ───────────

    def _passive_take_order(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        deviation: float,
        trend: float,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        threshold = p["take_threshold"]
        trend_guard = p["trend_guard"]
        pos_gate = p["signal_pos_gate"]
        cooldown = p["take_cooldown_ts"]
        size = p["take_size"]
        last_ts = int(memory.get("last_take_ts", -10 ** 9))
        if int(state.timestamp) - last_ts < cooldown:
            return None
        if abs(trend) >= trend_guard:
            return None
        if deviation > threshold and position > -pos_gate and sell_cap > 0:
            qty = min(size, sell_cap, pos_gate + position)
            if qty > 0:
                memory["last_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_bid), -qty)
        if deviation < -threshold and position < pos_gate and buy_cap > 0:
            qty = min(size, buy_cap, pos_gate - position)
            if qty > 0:
                memory["last_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_ask), qty)
        return None

    # ── NEW: Confirmed-reversal taker ────────────────────────────────────

    def _confirmed_reversal_take(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        deviation: float,
        trend: float,
        cur_dir: int,
        dir_streak: int,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        """Fires when:
          - position is large enough to matter
          - |dev| is extreme (>= extreme_dev_threshold)
          - mid has reversed direction OPPOSITE to the position bias
            (mid going up while we're short → cover trigger)
          - dir_streak >= reversal_persist_ticks (confirmed, not transient)

        Bypasses trend_guard because reversal IS the trend flip.
        """
        if abs(position) < p["min_pos_for_reversal_take"]:
            return None

        extreme_thr = p["extreme_dev_threshold"]
        if abs(deviation) < extreme_thr:
            return None

        persist = p["reversal_persist_ticks"]
        if dir_streak < persist:
            return None

        cooldown = p["reversal_cooldown_ts"]
        last_ts = int(memory.get("_last_reversal_ts", -10 ** 9))
        ts_now = int(state.timestamp)
        if ts_now - last_ts < cooldown:
            return None

        # Reversal direction must be OPPOSITE to position bias
        # (long position + mid going DOWN → sell to cover) - but that's
        # the wrong direction for mean-rev. We want:
        # short position + mid going UP for 3+ ticks AND |dev|>extreme
        #   → fire BUY taker (cover the short before further rebound)
        # long position + mid going DOWN for 3+ ticks AND |dev|>extreme
        #   → fire SELL taker (close the long)
        size_max = p["reversal_take_max"]
        size_div = p["reversal_take_scale_div"]
        excess = abs(deviation) - extreme_thr
        size = min(size_max, p["reversal_take_base"] + int(excess / size_div))

        if position < 0 and cur_dir > 0 and deviation < -extreme_thr and buy_cap > 0:
            # Short + mid going UP at extreme low: rebound starting → COVER
            qty = min(size, buy_cap, -position)
            if qty > 0:
                memory["_last_reversal_ts"] = ts_now
                memory["_last_reversal_size"] = qty
                memory["_last_reversal_side"] = "BUY"
                return Order(self.product, int(book.best_ask), qty)
        if position > 0 and cur_dir < 0 and deviation > extreme_thr and sell_cap > 0:
            # Long + mid going DOWN at extreme high: drop starting → SELL
            qty = min(size, sell_cap, position)
            if qty > 0:
                memory["_last_reversal_ts"] = ts_now
                memory["_last_reversal_size"] = qty
                memory["_last_reversal_side"] = "SELL"
                return Order(self.product, int(book.best_bid), -qty)
        return None

    def _read_params(self) -> Dict[str, Any]:
        p = self.params
        return {
            # Theo's HYDRO base
            "ema_alpha": float(p.get("ema_alpha", 0.008)),
            "fast_ema_alpha": float(p.get("fast_ema_alpha", 0.03)),
            "maker_size": int(p.get("maker_size", 24)),
            "min_maker_size": int(p.get("min_maker_size", 3)),
            "quote_threshold": float(p.get("quote_threshold", 6.0)),
            "max_signal_size_boost": int(p.get("max_signal_size_boost", 12)),
            "trend_guard": float(p.get("trend_guard", 6.0)),
            "signal_pos_gate": int(p.get("signal_pos_gate", 12)),
            "inventory_reduce_per_unit": float(p.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(p.get("inventory_unwind_per_unit", 0.30)),
            "max_unwind_boost": int(p.get("max_unwind_boost", 20)),
            "tighten_ticks": int(p.get("tighten_ticks", 1)),
            "take_threshold": float(p.get("take_threshold", 12.0)),
            "take_size": int(p.get("take_size", 1)),
            "take_cooldown_ts": int(p.get("take_cooldown_ts", 2000)),
            # Confirmed-reversal taker (NEW)
            "extreme_dev_threshold": float(p.get("extreme_dev_threshold", 20.0)),
            "reversal_persist_ticks": int(p.get("reversal_persist_ticks", 3)),
            "min_pos_for_reversal_take": int(p.get("min_pos_for_reversal_take", 10)),
            "reversal_take_base": int(p.get("reversal_take_base", 3)),
            "reversal_take_max": int(p.get("reversal_take_max", 12)),
            "reversal_take_scale_div": float(p.get("reversal_take_scale_div", 4.0)),
            "reversal_cooldown_ts": int(p.get("reversal_cooldown_ts", 1000)),
            # Adaptive pos_gate (NEW v2)
            "adaptive_pos_gate": bool(p.get("adaptive_pos_gate", False)),
            "adaptive_pos_gate_range_thr": float(p.get("adaptive_pos_gate_range_thr", 60.0)),
            "adaptive_pos_gate_max": int(p.get("adaptive_pos_gate_max", 18)),
            # Léo's session drift bias
            "session_drift_bias": int(p.get("session_drift_bias", 4)),
            "session_bias_strong_until_ts": int(p.get("session_bias_strong_until_ts", 100_000)),
            "session_bias_fade_until_ts": int(p.get("session_bias_fade_until_ts", 300_000)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("ema", "fast_ema", "_dev", "_trend", "_session_bias",
                  "_dir_streak_log", "_last_reversal_size"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'adaptive_pos_gate': False,
                   'adaptive_pos_gate_max': 18,
                   'adaptive_pos_gate_range_thr': 60.0,
                   'ema_alpha': 0.008,
                   'extreme_dev_threshold': 22.0,
                   'fast_ema_alpha': 0.03,
                   'inventory_reduce_per_unit': 0.4,
                   'inventory_unwind_per_unit': 0.3,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 24,
                   'max_signal_size_boost': 12,
                   'max_unwind_boost': 20,
                   'min_maker_size': 3,
                   'min_pos_for_reversal_take': 8,
                   'position_limit': 200,
                   'quote_threshold': 6.0,
                   'reversal_cooldown_ts': 1000,
                   'reversal_persist_ticks': 3,
                   'reversal_take_base': 3,
                   'reversal_take_max': 12,
                   'reversal_take_scale_div': 4.0,
                   'session_bias_fade_until_ts': 300000,
                   'session_bias_strong_until_ts': 100000,
                   'session_drift_bias': 4,
                   'signal_pos_gate': 12,
                   'strategy': 'hydrogel_smart_mm',
                   'take_cooldown_ts': 2000,
                   'take_size': 1,
                   'take_threshold': 12.0,
                   'tighten_ticks': 1,
                   'trend_guard': 6.0,
                   'ts_increment': 100}}

STRATEGY_CLASSES = {"hydrogel_smart_mm": HydrogelSmartMMStrategy}

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
