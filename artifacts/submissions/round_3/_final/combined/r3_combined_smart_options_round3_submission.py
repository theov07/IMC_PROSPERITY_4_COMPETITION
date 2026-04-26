from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from datamodel import TradingState
from typing import Any, Dict
from typing import Any, Dict, List, Optional
from typing import Any, Dict, List, Optional, Tuple
from typing import Any, Dict, List, Tuple
from typing import Any, Mapping
from typing import List, Sequence, Tuple, Optional
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


# ── prosperity/strategies/round_1/naive_tight_mm.py ───────────────────────────────

class NaiveTightMarketMakerStrategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        maker_size = int(self.params.get("maker_size", 10))
        tighten_ticks = int(self.params.get("tighten_ticks", 1))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_price = None
        ask_price = None

        if book.best_bid is not None:
            bid_price = book.best_bid
        if book.best_ask is not None:
            ask_price = book.best_ask

        if book.best_bid is not None and book.best_ask is not None:
            spread = book.best_ask - book.best_bid
            if spread >= 2:
                bid_price = min(book.best_bid + tighten_ticks, book.best_ask - 0.1)
                ask_price = max(book.best_ask - tighten_ticks, book.best_bid + 0.1)

        if bid_price is not None and buy_cap > 0:
            orders.append(Order(self.product, bid_price, min(maker_size, buy_cap)))

        if ask_price is not None and sell_cap > 0:
            orders.append(Order(self.product, ask_price, -min(maker_size, sell_cap)))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread

        # ── Per-tick log accumulation ──
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
        )

        return orders, 0


# ── prosperity/options/time.py ────────────────────────────────────────────────────

DEFAULT_TIMESTAMP_UNITS_PER_DAY = 1_000_000.0
DEFAULT_TS_INCREMENT = 100.0
MIN_TTE_DAYS = 0.01


def timestamp_units_per_day_from_params(params: Mapping[str, Any]) -> float:
    """Resolve how many raw timestamp units make one Prosperity day."""

    explicit = params.get("timestamp_units_per_day")
    if explicit is not None:
        return max(float(explicit), 1.0)

    ticks_per_day = float(params.get("ticks_per_day", DEFAULT_TIMESTAMP_UNITS_PER_DAY / DEFAULT_TS_INCREMENT))
    ts_increment = float(params.get("ts_increment", DEFAULT_TS_INCREMENT))
    return max(ticks_per_day * ts_increment, 1.0)


def time_to_expiry_days(
    timestamp: int | float,
    initial_tte_days: int | float,
    *,
    timestamp_units_per_day: int | float = DEFAULT_TIMESTAMP_UNITS_PER_DAY,
    min_tte_days: int | float = MIN_TTE_DAYS,
) -> float:
    """Return remaining option TTE in days at a raw IMC timestamp."""

    elapsed_days = max(float(timestamp), 0.0) / max(float(timestamp_units_per_day), 1.0)
    return max(float(min_tte_days), float(initial_tte_days) - elapsed_days)


def resolve_initial_tte_days(
    trader_data: str,
    default_tte_days: int | float,
    historical_tte_by_day: Mapping[Any, Any] | None = None,
) -> float:
    """Use backtest day metadata when present, otherwise return live default."""

    if not historical_tte_by_day or not trader_data:
        return float(default_tte_days)

    try:
        loaded = json.loads(trader_data)
    except Exception:
        return float(default_tte_days)
    if not isinstance(loaded, dict):
        return float(default_tte_days)

    meta = loaded.get("_backtest")
    if not isinstance(meta, dict) or "day" not in meta:
        return float(default_tte_days)

    day = meta.get("day")
    candidate_keys = [day, str(day)]
    try:
        candidate_keys.append(int(day))
    except (TypeError, ValueError):
        pass

    for key in candidate_keys:
        if key in historical_tte_by_day:
            try:
                return float(historical_tte_by_day[key])
            except (TypeError, ValueError):
                return float(default_tte_days)

    return float(default_tte_days)


# ── prosperity/options/black_scholes.py ───────────────────────────────────────────

# ── Normal CDF and PDF (pure Python, Abramowitz & Stegun approx) ──────────────

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _norm_cdf(x: float) -> float:
    # math.erf gives enough precision for option pricing
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ── d1 / d2 helpers ───────────────────────────────────────────────────────────

def _d1_d2(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0):
    """Return (d1, d2). Returns (None, None) if inputs invalid (T<=0 or sigma<=0)."""
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return None, None
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return d1, d2


# ── Call pricing and greeks ───────────────────────────────────────────────────

def call_price(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """European call price. Returns intrinsic value if T<=0 or sigma<=0."""
    if T <= 0.0 or sigma <= 0.0:
        return max(0.0, S - K)
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return max(0.0, S - K)
    return S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def call_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """dC/dS. Approaches 1 deep ITM, 0 deep OTM, 0.5 ATM-ish."""
    if T <= 0.0 or sigma <= 0.0:
        return 1.0 if S > K else (0.0 if S < K else 0.5)
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.5
    return math.exp(-q * T) * _norm_cdf(d1)


def call_gamma(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """d2C/dS2. Peaks near ATM with short T."""
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    return math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def call_vega(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """dC/dsigma. Per 1.0 change in sigma (i.e. not %). Peaks near ATM."""
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    return S * math.exp(-q * T) * _norm_pdf(d1) * math.sqrt(T)


def call_theta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """dC/dt. Per 1 day of time decay. Usually negative for long calls."""
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    term1 = -S * _norm_pdf(d1) * sigma * math.exp(-q * T) / (2.0 * math.sqrt(T))
    term2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
    term3 = q * S * math.exp(-q * T) * _norm_cdf(d1)
    return term1 + term2 + term3


# ── Put pricing (via put-call parity) ─────────────────────────────────────────

def put_price(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """European put price."""
    c = call_price(S, K, T, sigma, r, q)
    return c - S * math.exp(-q * T) + K * math.exp(-r * T)


def put_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """dP/dS = call_delta - e^(-q*T)."""
    return call_delta(S, K, T, sigma, r, q) - math.exp(-q * T)


# ── prosperity/options/implied_vol.py ─────────────────────────────────────────────

# ── Newton-Raphson implied vol (call) ─────────────────────────────────────────

def call_implied_vol(
    target_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    *,
    sigma_init: float = 0.02,
    tol: float = 1e-5,
    max_iter: int = 30,
    sigma_min: float = 1e-5,
    sigma_max: float = 5.0,
) -> float | None:
    """Invert Black-Scholes to get sigma from a call price.

    Returns None if convergence fails or target price is outside no-arbitrage bounds.
    """
    import math

    if T <= 0.0 or S <= 0.0 or K <= 0.0:
        return None
    # No-arbitrage bounds: max(S e^-qT - K e^-rT, 0) <= C <= S e^-qT
    lower_bound = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
    upper_bound = S * math.exp(-q * T)
    if target_price < lower_bound - 1e-6 or target_price > upper_bound + 1e-6:
        return None

    # Newton-Raphson first
    sigma = sigma_init
    for _ in range(max_iter):
        price = call_price(S, K, T, sigma, r, q)
        diff = price - target_price
        if abs(diff) < tol:
            return sigma
        vega = call_vega(S, K, T, sigma, r, q)
        if vega < 1e-10:
            break  # switch to bisection
        sigma -= diff / vega
        if sigma < sigma_min or sigma > sigma_max:
            break  # switch to bisection

    # Bisection fallback
    lo, hi = sigma_min, sigma_max
    p_lo = call_price(S, K, T, lo, r, q)
    p_hi = call_price(S, K, T, hi, r, q)
    if p_lo > target_price or p_hi < target_price:
        return None
    for _ in range(max_iter * 2):
        mid = 0.5 * (lo + hi)
        p_mid = call_price(S, K, T, mid, r, q)
        if abs(p_mid - target_price) < tol:
            return mid
        if p_mid < target_price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ── Put implied vol (reuse put-call parity + call IV) ─────────────────────────

def put_implied_vol(
    target_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    **kwargs,
) -> float | None:
    """Invert BS to get sigma from a put price via put-call parity."""
    import math

    # Put = Call - S e^-qT + K e^-rT  ->  equivalent call price
    call_target = target_price + S * math.exp(-q * T) - K * math.exp(-r * T)
    return call_implied_vol(call_target, S, K, T, r, q, **kwargs)


# ── prosperity/options/smile.py ───────────────────────────────────────────────────

def _solve_normal_eqs(X_cols: List[List[float]], y: List[float]) -> Optional[List[float]]:
    """Ordinary least squares: solve (X^T X) beta = X^T y for small matrices.

    X_cols is a list of columns (each column is a list of same length n).
    Returns beta as list[float] or None if singular.
    """
    n = len(y)
    d = len(X_cols)
    if n < d:
        return None
    # Build X^T X (d x d) and X^T y (d)
    XtX = [[0.0] * d for _ in range(d)]
    Xty = [0.0] * d
    for i in range(d):
        for j in range(d):
            s = 0.0
            for k in range(n):
                s += X_cols[i][k] * X_cols[j][k]
            XtX[i][j] = s
        s = 0.0
        for k in range(n):
            s += X_cols[i][k] * y[k]
        Xty[i] = s
    # Solve d x d via Gauss-Jordan
    M = [row[:] + [Xty[i]] for i, row in enumerate(XtX)]  # augmented
    for i in range(d):
        # Partial pivot
        max_row = i
        for r in range(i + 1, d):
            if abs(M[r][i]) > abs(M[max_row][i]):
                max_row = r
        M[i], M[max_row] = M[max_row], M[i]
        if abs(M[i][i]) < 1e-12:
            return None
        pivot = M[i][i]
        for c in range(d + 1):
            M[i][c] /= pivot
        for r in range(d):
            if r != i:
                factor = M[r][i]
                for c in range(d + 1):
                    M[r][c] -= factor * M[i][c]
    return [M[i][d] for i in range(d)]


# ── Smile fit ─────────────────────────────────────────────────────────────────

def fit_smile_poly(
    strikes: Sequence[float],
    vols: Sequence[float],
    S: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    *,
    degree: int = 2,
    min_points: int = 3,
) -> Optional[List[float]]:
    """Fit polynomial smile sigma(m) = sum(a_i * m^i) where m = ln(K/F).

    Args:
        strikes: iterable of strike prices
        vols:    iterable of matching implied vols (skip None values)
        S, T, r, q: BS inputs to compute forward F = S * e^((r-q)*T)
        degree: polynomial degree (2 = quadratic smile, default)
        min_points: require at least this many valid (K, vol) pairs

    Returns:
        list of coefficients [a0, a1, ..., a_degree], or None if fit failed.
    """
    F = S * math.exp((r - q) * T)
    ms: List[float] = []
    sigs: List[float] = []
    for K, v in zip(strikes, vols):
        if v is None or v <= 0.0 or K <= 0.0:
            continue
        ms.append(math.log(K / F))
        sigs.append(float(v))
    if len(ms) < max(min_points, degree + 1):
        return None
    # Build design matrix columns [1, m, m^2, ...]
    cols: List[List[float]] = []
    for d in range(degree + 1):
        cols.append([m ** d for m in ms])
    return _solve_normal_eqs(cols, sigs)


def smile_predict(
    K: float,
    coeffs: Sequence[float],
    S: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
) -> float:
    """Evaluate smile sigma at strike K using fitted polynomial."""
    F = S * math.exp((r - q) * T)
    m = math.log(K / F)
    sig = 0.0
    for i, a in enumerate(coeffs):
        sig += a * (m ** i)
    return max(1e-5, sig)


def average_vol(vols: Sequence[Optional[float]]) -> Optional[float]:
    """Robust average of a list of implied vols (ignore None/invalid)."""
    valid = [v for v in vols if v is not None and v > 0.0]
    if not valid:
        return None
    return sum(valid) / len(valid)


# ── prosperity/options/coordinator.py ─────────────────────────────────────────────

# ── Module-level state (safe in Prosperity single-threaded sandbox) ───────────

_STATE: Dict[str, Any] = {
    "ts": None,          # int — timestamp of current tick
    "smile": None,       # List[float] or None — last computed smile coeffs
    "spot": {},          # dict: underlying_symbol -> float mid
    "positions": {},     # dict: product -> int position (published by strategies)
}


def _ensure_current_tick(ts: int) -> None:
    """Clear per-tick caches if the timestamp has advanced."""
    if _STATE["ts"] != ts:
        _STATE["ts"] = ts
        _STATE["smile"] = None
        _STATE["spot"] = {}
        _STATE["positions"] = {}


# ── Spot ──────────────────────────────────────────────────────────────────────

def get_spot(state: TradingState, *, underlying: str) -> Optional[float]:
    """Return mid-price of the underlying, caching the result for this tick."""
    ts = int(state.timestamp)
    _ensure_current_tick(ts)
    cached = _STATE["spot"].get(underlying)
    if cached is not None:
        return cached
    od = state.order_depths.get(underlying)
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    bb = max(od.buy_orders.keys())
    ba = min(od.sell_orders.keys())
    spot = 0.5 * (bb + ba)
    _STATE["spot"][underlying] = spot
    return spot


# ── Smile ─────────────────────────────────────────────────────────────────────

def get_smile(
    state: TradingState,
    *,
    strikes: List[int],
    strike_prefix: str,
    S: float,
    T: float,
    sigma_floor: float,
    sigma_cap: float,
    prior_vol: float,
    degree: int = 2,
) -> Optional[List[float]]:
    """Return smile coefficients fitted across all strikes at this tick.

    Fits once per tick. Subsequent calls in the same tick return the cached
    result regardless of which strike asked.

    Args:
        state: current TradingState (for order_depths)
        strikes: iterable of strike prices to consider
        strike_prefix: e.g. "VEV_" so "VEV_5000" resolves from strike 5000
        S, T: spot + time to expiry for BS
        sigma_floor/sigma_cap: IV bounds for validity
        prior_vol: initial guess for IV solver
        degree: polynomial degree in log-moneyness (default 2)
    """
    ts = int(state.timestamp)
    _ensure_current_tick(ts)
    if _STATE["smile"] is not None:
        return _STATE["smile"]

    valid_strikes: List[float] = []
    valid_vols: List[float] = []
    for K in strikes:
        sym = f"{strike_prefix}{K}"
        od = state.order_depths.get(sym)
        if not od or not od.buy_orders or not od.sell_orders:
            continue
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        mid = 0.5 * (bb + ba)
        iv = call_implied_vol(mid, S, float(K), T, sigma_init=prior_vol)
        if iv is not None and sigma_floor <= iv <= sigma_cap:
            valid_strikes.append(float(K))
            valid_vols.append(iv)

    coeffs: Optional[List[float]] = None
    if len(valid_strikes) >= 3:
        coeffs = fit_smile_poly(valid_strikes, valid_vols, S, T, degree=degree)

    _STATE["smile"] = coeffs
    return coeffs


# ── Position registry (used by delta hedger) ──────────────────────────────────

def publish_position(ts: int, product: str, position: int) -> None:
    """Record current position for `product`. Called by each strategy per tick."""
    _ensure_current_tick(ts)
    _STATE["positions"][product] = int(position)


def get_positions(ts: int) -> Dict[str, int]:
    """Return snapshot of published positions for the given tick (dict copy)."""
    _ensure_current_tick(ts)
    return dict(_STATE["positions"])


# ── Debug / introspection ─────────────────────────────────────────────────────

def snapshot() -> Dict[str, Any]:
    """Return a shallow copy of current state (debug / testing)."""
    return {
        "ts": _STATE["ts"],
        "smile_present": _STATE["smile"] is not None,
        "spot_keys": list(_STATE["spot"].keys()),
        "positions": dict(_STATE["positions"]),
    }


def reset() -> None:
    """Clear all state. Intended for tests / between backtest runs."""
    _STATE["ts"] = None
    _STATE["smile"] = None
    _STATE["spot"] = {}
    _STATE["positions"] = {}


# ── prosperity/strategies/round_3/option_mm_bs.py ─────────────────────────────────

# Default strike set for the VEV voucher series (can be overridden via params).
_DEFAULT_VEV_STRIKES: List[int] = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


class OptionMMBSStrategy(BaseStrategy):
    """European call market-maker using Black-Scholes + volatility smile."""

    # ── Entry point ──────────────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        p = self._read_params(state)
        ts = int(state.timestamp)

        # Publish our current position to the coordinator so the hedger can read it.
        publish_position(ts, self.product, position)

        # 1. Resolve underlying spot (shared across all VEV_xxxx this tick).
        S = self._resolve_spot(state, memory, ts)
        if S is None:
            return [], 0

        # 2. Choose sigma to price this option: smile-fit / own IV / EWMA'd.
        own_mid = 0.5 * (book.best_bid + book.best_ask)
        sigma = self._resolve_sigma(
            state=state, memory=memory, own_mid=own_mid,
            S=S, K=p["K"], T=p["T"], ts=ts, params=p,
        )

        # 3. Compute BS fair value + inventory skew.
        fair = call_price(S, p["K"], p["T"], sigma)
        self._record_diagnostics(memory, fair=fair, sigma=sigma, T=p["T"], S=S, tte0=p["tte0"])
        if fair < p["min_quote_price"]:
            memory["_skipped"] = 1
            return [], 0
        fair_skewed = fair - p["inv_bias_per_unit"] * position

        # 4. Determine quote prices (two modes: penny-improve vs BS-edged).
        bid_px, ask_px = self._compute_quotes(book, fair_skewed, p)

        # 5. Taker + passive orders.
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        if p["enable_takers"]:
            taker_orders, buy_cap, sell_cap = self._fire_takers(
                fair_skewed, book, order_depth, buy_cap, sell_cap, p,
            )
            orders.extend(taker_orders)

        orders.extend(self._post_passive(bid_px, ask_px, buy_cap, sell_cap, p["maker_size"]))
        return orders, 0

    # ── Param loading ────────────────────────────────────────────────────────

    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        """Read + normalize all params once per tick."""
        params = self.params
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(params.get("tte_days_initial", 5.0)),
            params.get("historical_tte_by_day"),
        )
        ts = int(state.timestamp)
        ts_per_day = timestamp_units_per_day_from_params(params)
        T = time_to_expiry_days(ts, tte0, timestamp_units_per_day=ts_per_day)
        return {
            "K": float(params["strike"]),
            "tte0": tte0,
            "T": max(0.01, T),
            "prior_vol": float(params.get("prior_vol", 0.02)),
            "maker_edge": int(params.get("maker_edge", 2)),
            "maker_size": int(params.get("maker_size", 20)),
            "take_edge": float(params.get("take_edge", 3.0)),
            "take_size": int(params.get("take_size", 40)),
            "use_smile": bool(params.get("use_smile", True)),
            "iv_ewma_alpha": float(params.get("iv_ewma_alpha", 0.3)),
            "sigma_floor": float(params.get("sigma_floor", 0.005)),
            "sigma_cap": float(params.get("sigma_cap", 0.10)),
            "enable_takers": bool(params.get("enable_takers", True)),
            "penny_improve_around_mkt": bool(params.get("penny_improve_around_mkt", False)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "inv_bias_per_unit": float(params.get("inv_bias_per_unit", 0.02)),
            "underlying_symbol": params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
        }

    # ── Spot resolution (delegates to coordinator) ───────────────────────────

    def _resolve_spot(
        self, state: TradingState, memory: Dict[str, Any], ts: int,
    ) -> Optional[float]:
        """Return mid-price of the underlying via the cross-product coordinator."""
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        return get_spot(state, underlying=underlying)

    # ── Sigma resolution ─────────────────────────────────────────────────────

    def _resolve_sigma(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        own_mid: float,
        S: float,
        K: float,
        T: float,
        ts: int,
        params: Dict[str, Any],
    ) -> float:
        """Return sigma to use for BS pricing of this option at this tick."""
        # 1. EWMA-smooth our own implied vol (always compute, for diagnostics / fallback).
        iv_smooth = self._update_iv_ewma(own_mid, S, K, T, memory, params)
        # Share our IV for smile coordinator / observability.
        shared = self._shared(memory)
        shared.setdefault("vev_iv", {})[K] = iv_smooth

        # 2. Prefer smile-predicted sigma when enabled.
        if not params["use_smile"]:
            return iv_smooth
        smile = self._get_or_fit_smile(state, shared, S, T, ts, params)
        if smile is None:
            return iv_smooth
        sigma = smile_predict(K, smile, S, T)
        return max(params["sigma_floor"], min(params["sigma_cap"], sigma))

    def _update_iv_ewma(
        self,
        own_mid: float,
        S: float,
        K: float,
        T: float,
        memory: Dict[str, Any],
        params: Dict[str, Any],
    ) -> float:
        """Invert BS for our own option mid and EWMA-smooth it."""
        iv = call_implied_vol(own_mid, S, K, T, sigma_init=params["prior_vol"])
        prev = memory.get("_iv_ewma")
        valid = iv is not None and params["sigma_floor"] <= iv <= params["sigma_cap"]
        if not valid:
            return prev if prev is not None else params["prior_vol"]
        if prev is None:
            memory["_iv_ewma"] = iv
            return iv
        alpha = params["iv_ewma_alpha"]
        iv_new = alpha * iv + (1.0 - alpha) * prev
        memory["_iv_ewma"] = iv_new
        return iv_new

    def _get_or_fit_smile(
        self,
        state: TradingState,
        shared: Dict[str, Any],
        S: float,
        T: float,
        ts: int,
        params: Dict[str, Any],
    ) -> Optional[List[float]]:
        """Return smile coefficients via the cross-product coordinator.

        The coordinator caches the fit for the current tick so only one fit
        is performed regardless of which voucher triggers it first.
        """
        strikes = params.get("smile_strikes") or _DEFAULT_VEV_STRIKES
        strike_prefix = str(params.get("strike_prefix", "VEV_"))
        return get_smile(
            state,
            strikes=list(strikes),
            strike_prefix=strike_prefix,
            S=S,
            T=T,
            sigma_floor=params["sigma_floor"],
            sigma_cap=params["sigma_cap"],
            prior_vol=params["prior_vol"],
        )

    # (smile fitting delegated to prosperity.options.coordinator.get_smile)

    # ── Quote pricing ────────────────────────────────────────────────────────

    def _compute_quotes(
        self,
        book: BookSnapshot,
        fair_skewed: float,
        params: Dict[str, Any],
    ) -> Tuple[int, int]:
        """Return (bid_px, ask_px). Return -1 for a side to signal 'skip'."""
        if params["penny_improve_around_mkt"]:
            bid_px = book.best_bid + 1
            ask_px = book.best_ask - 1
        else:
            bid_px = int(round(fair_skewed - params["maker_edge"]))
            ask_px = int(round(fair_skewed + params["maker_edge"]))

        # Never post inside own book or cross the market
        if bid_px >= book.best_ask:
            bid_px = book.best_ask - 1
        if ask_px <= book.best_bid:
            ask_px = book.best_bid + 1
        bid_px = max(1, bid_px)       # floor (call options can't price below 1)
        ask_px = max(bid_px + 1, ask_px)

        # Skip markers if our theoretical quote would cross the market
        if bid_px > book.best_ask:
            bid_px = -1
        if ask_px < book.best_bid:
            ask_px = -1
        return bid_px, ask_px

    # ── Taker orders ─────────────────────────────────────────────────────────

    def _fire_takers(
        self,
        fair_skewed: float,
        book: BookSnapshot,
        order_depth: OrderDepth,
        buy_cap: int,
        sell_cap: int,
        params: Dict[str, Any],
    ) -> Tuple[List[Order], int, int]:
        """Aggressive buy/sell when market ask/bid is mispriced vs fair."""
        orders: List[Order] = []
        take_edge = params["take_edge"]
        take_size = params["take_size"]
        # Buy under fair: market ask < fair - take_edge
        if book.best_ask is not None and buy_cap > 0:
            if (fair_skewed - book.best_ask) >= take_edge:
                qty = -order_depth.sell_orders[book.best_ask]
                take_qty = min(qty, buy_cap, take_size)
                if take_qty > 0:
                    orders.append(Order(self.product, book.best_ask, take_qty))
                    buy_cap -= take_qty
        # Sell over fair: market bid > fair + take_edge
        if book.best_bid is not None and sell_cap > 0:
            if (book.best_bid - fair_skewed) >= take_edge:
                qty = order_depth.buy_orders[book.best_bid]
                take_qty = min(qty, sell_cap, take_size)
                if take_qty > 0:
                    orders.append(Order(self.product, book.best_bid, -take_qty))
                    sell_cap -= take_qty
        return orders, buy_cap, sell_cap

    # ── Passive orders ───────────────────────────────────────────────────────

    def _post_passive(
        self,
        bid_px: int,
        ask_px: int,
        buy_cap: int,
        sell_cap: int,
        maker_size: int,
    ) -> List[Order]:
        """Post one passive bid + one passive ask within remaining capacity."""
        orders: List[Order] = []
        if bid_px > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(maker_size, buy_cap)))
        if ask_px > 0 and sell_cap > 0:
            orders.append(Order(self.product, ask_px, -min(maker_size, sell_cap)))
        return orders

    # ── Utilities ────────────────────────────────────────────────────────────

    def _shared(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        """Return (creating if needed) the cross-product shared dict."""
        shared = memory.get("_shared")
        if not isinstance(shared, dict):
            shared = {}
            memory["_shared"] = shared
        return shared

    def _record_diagnostics(
        self,
        memory: Dict[str, Any],
        *,
        fair: float,
        sigma: float,
        T: float,
        S: float,
        tte0: float,
    ) -> None:
        """Write per-tick diagnostics to memory (consumed by feature_prices)."""
        memory["_bs_fair"] = fair
        memory["_sigma_use"] = sigma
        memory["_tte_days"] = T
        memory["_tte_initial_days"] = tte0
        memory["_spot"] = S

    # ── Dashboard feature hooks ──────────────────────────────────────────────

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (f := memory.get("_bs_fair")) is not None:
            out["BS_fair"] = f
        if (s := memory.get("_sigma_use")) is not None:
            out["sigma_pct"] = s * 100
        if (T := memory.get("_tte_days")) is not None:
            out["TTE_days"] = T
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'ema_alpha': 0.008,
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
                   'ts_increment': 100},
 'VELVETFRUIT_EXTRACT': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 20,
                         'position_limit': 40,
                         'strategy': 'naive_tight_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'VEV_4000': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 40,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 4000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_4500': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 24,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 4500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5000': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 24,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5100': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 24,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5100,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5200': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 24,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5200,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True}}

STRATEGY_CLASSES = {"hydrogel_smart_mm": HydrogelSmartMMStrategy, "naive_tight_mm": NaiveTightMarketMakerStrategy, "option_mm_bs": OptionMMBSStrategy}

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
