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


# ── prosperity/strategies/round_3/hydrogel_follow_mm.py ───────────────────────────

class HydrogelFollowMMStrategy(BaseStrategy):
    """Trend-follow MM with aggressive mean-revert unwind."""

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

        # ── Dual EMA + variance on fast residual ─────────────────────────
        alpha_f = 2.0 / (p["ema_fast"] + 1)
        alpha_s = 2.0 / (p["ema_slow"] + 1)
        ema_fast_prev = memory.get("_ema_fast", mid)
        ema_slow_prev = memory.get("_ema_slow", mid)
        var_prev = memory.get("_ewma_var", 0.0)
        tick_count = memory.get("_tick_count", 0) + 1

        delta_f = mid - ema_fast_prev
        new_fast = ema_fast_prev + alpha_f * delta_f
        new_slow = ema_slow_prev + alpha_s * (mid - ema_slow_prev)
        new_var = (1 - alpha_f) * (var_prev + alpha_f * delta_f * delta_f)
        std = (new_var ** 0.5) if new_var > 0 else 0.0

        z = (mid - new_fast) / std if std > 1e-6 else 0.0
        trend = (new_fast - new_slow) / std if std > 1e-6 else 0.0

        memory["_ema_fast"] = new_fast
        memory["_ema_slow"] = new_slow
        memory["_ewma_var"] = new_var
        memory["_tick_count"] = tick_count
        memory["_z"] = z
        memory["_trend"] = trend

        warmup = (tick_count < p["min_samples"]) or (std < 1e-6)
        effective_trend = 0.0 if warmup else trend
        effective_z = 0.0 if warmup else z

        # ── Regime ──────────────────────────────────────────────────────
        t_thr = p["trend_threshold"]
        if effective_trend > t_thr:
            regime = "up_trend"
        elif effective_trend < -t_thr:
            regime = "down_trend"
        else:
            regime = "flat"
        memory["_regime"] = regime

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        # ── Quote prices (penny-improve inside the spread) ──────────────
        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])

        # ── Sizing by regime ────────────────────────────────────────────
        bid_size, ask_size = self._quote_sizes(
            regime, effective_trend, effective_z, position, p
        )
        quote_bid_price = None
        quote_ask_price = None
        quote_bid_size = 0
        quote_ask_size = 0

        # ── Hard position cap ───────────────────────────────────────────
        hard_cap = p["hard_pos_cap"]
        if position >= hard_cap:
            bid_size = 0
        if position <= -hard_cap:
            ask_size = 0

        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            quote_bid_price = bid_price
            quote_bid_size = qty
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            quote_ask_price = ask_price
            quote_ask_size = qty
            sell_cap -= qty

        # ── Aggressive unwind taker ─────────────────────────────────────
        # Only fires when we have an established position (|pos| > min_pos_for_take)
        # AND one of: trend flipped, z extreme take-profit, z extreme stop-loss.
        # Flat regime with small position = no takers (avoid whipsaw).
        min_pos_take = p["min_pos_for_take"]
        if p["enable_taker"] and not warmup and abs(position) >= min_pos_take:
            take = self._take_order(
                state, book, position, effective_z, effective_trend, regime,
                memory, buy_cap, sell_cap, p,
            )
            if take is not None:
                orders.append(take)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=quote_bid_price,
            ask_price=quote_ask_price,
            extras={
                "bid_size": quote_bid_size,
                "ask_size": quote_ask_size,
                "mid": round(mid, 4),
                "ema_fast": round(new_fast, 4),
                "ema_slow": round(new_slow, 4),
                "zscore": round(effective_z, 6),
                "trend": round(effective_trend, 6),
                "regime": {"flat": 0, "up_trend": 1, "down_trend": 2}.get(regime, -1),
                "position": position,
            },
        )
        return orders, 0

    # ── Quote prices (penny-improve) ────────────────────────────────────

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, book.best_bid + 1)
        return bid, ask

    # ── Regime-based sizing ─────────────────────────────────────────────

    def _quote_sizes(
        self,
        regime: str,
        trend: float,
        z: float,
        position: int,
        p: Dict[str, Any],
    ) -> Tuple[int, int]:
        maker = p["maker_size"]
        min_m = p["min_maker_size"]
        boost_max = p["follow_boost_max"]
        boost_per = p["follow_boost_per_trend"]

        bid_size = maker
        ask_size = maker

        if regime == "up_trend":
            # Follow up: grow BID, minimise ASK (but keep tiny for accidental rip)
            bid_size = maker + min(boost_max, int(abs(trend) * boost_per))
            ask_size = min_m
        elif regime == "down_trend":
            ask_size = maker + min(boost_max, int(abs(trend) * boost_per))
            bid_size = min_m
        else:
            # Flat → pure passive MM (symmetric). NO one-side z-mean-rev here
            # because on slow drift days (e.g. day 2), fast_EMA lags and z
            # persistently signals "cheap" while mid keeps dropping — we'd
            # keep buying into the drop. Let inventory skew handle recentering.
            bid_size = maker
            ask_size = maker

        # ── Inventory skew ONLY in flat regime ──────────────────────────
        # In trend regime we WANT to grow inventory with the trend.
        if regime == "flat":
            reduce = p["inventory_reduce_per_unit"]
            unwind = p["inventory_unwind_per_unit"]
            unwind_boost = p["unwind_boost_max"]
            if position > 0:
                bid_size = max(0, bid_size - int(position * reduce))
                ask_size += min(unwind_boost, int(position * unwind))
            elif position < 0:
                ask_size = max(0, ask_size - int(-position * reduce))
                bid_size += min(unwind_boost, int(-position * unwind))

        if 0 < bid_size < min_m:
            bid_size = min_m
        if 0 < ask_size < min_m:
            ask_size = min_m
        return max(0, bid_size), max(0, ask_size)

    # ── Aggressive unwind taker ─────────────────────────────────────────

    def _take_order(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        z: float,
        trend: float,
        regime: str,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        cooldown = p["take_cooldown_ts"]
        last_ts = int(memory.get("_last_take_ts", -10 ** 9))
        if int(state.timestamp) - last_ts < cooldown:
            return None

        flip_thr = p["flip_threshold"]
        tp_z = p["tp_z"]
        stop_z = p["stop_z"]
        unwind_size = p["unwind_take_size"]

        # (A) Trend-flip stop: position adverse to trend direction
        if position > 0 and trend < -flip_thr and sell_cap > 0:
            qty = min(unwind_size, position, sell_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "flip_stop_long"
                return Order(self.product, int(book.best_bid), -qty)
        if position < 0 and trend > flip_thr and buy_cap > 0:
            qty = min(unwind_size, -position, buy_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "flip_stop_short"
                return Order(self.product, int(book.best_ask), qty)

        # (B) Mean-revert take-profit: position extended, z signals reversion
        # If long and price rich (z>+tp_z) → take profit via hitting bid.
        # If short and price cheap (z<-tp_z) → take profit via hitting ask.
        if position > 0 and z > tp_z and sell_cap > 0:
            qty = min(unwind_size, position, sell_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "tp_long"
                return Order(self.product, int(book.best_bid), -qty)
        if position < 0 and z < -tp_z and buy_cap > 0:
            qty = min(unwind_size, -position, buy_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "tp_short"
                return Order(self.product, int(book.best_ask), qty)

        # (C) Stop-loss on extreme adverse z (position wrong side very far)
        # long and z < -stop_z → price collapsed below EMA → cut losses
        if position > 0 and z < -stop_z and sell_cap > 0:
            qty = min(unwind_size, position, sell_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "stop_long"
                return Order(self.product, int(book.best_bid), -qty)
        if position < 0 and z > stop_z and buy_cap > 0:
            qty = min(unwind_size, -position, buy_cap)
            if qty > 0:
                memory["_last_take_ts"] = int(state.timestamp)
                memory["_last_take_reason"] = "stop_short"
                return Order(self.product, int(book.best_ask), qty)
        return None

    # ── Params ──────────────────────────────────────────────────────────

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "ema_fast": int(params.get("ema_fast", 500)),
            "ema_slow": int(params.get("ema_slow", 2000)),
            "trend_threshold": float(params.get("trend_threshold", 1.0)),
            "flat_z_threshold": float(params.get("flat_z_threshold", 1.5)),
            "maker_size": int(params.get("maker_size", 20)),
            "min_maker_size": int(params.get("min_maker_size", 2)),
            "follow_boost_max": int(params.get("follow_boost_max", 10)),
            "follow_boost_per_trend": int(params.get("follow_boost_per_trend", 4)),
            "flat_boost_max": int(params.get("flat_boost_max", 8)),
            "flat_boost_per_z": int(params.get("flat_boost_per_z", 3)),
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.30)),
            "unwind_boost_max": int(params.get("unwind_boost_max", 20)),
            "tighten_ticks": int(params.get("tighten_ticks", 1)),
            "enable_taker": bool(params.get("enable_taker", True)),
            "flip_threshold": float(params.get("flip_threshold", 0.8)),
            "tp_z": float(params.get("tp_z", 1.2)),
            "stop_z": float(params.get("stop_z", 2.5)),
            "unwind_take_size": int(params.get("unwind_take_size", 4)),
            "take_cooldown_ts": int(params.get("take_cooldown_ts", 500)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 35)),
            "min_pos_for_take": int(params.get("min_pos_for_take", 8)),
            "min_samples": int(params.get("min_samples", 200)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ema_fast", "_ema_slow", "_z", "_trend"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = v
        if (r := memory.get("_regime")) is not None:
            out["regime_code"] = {"flat": 0, "up_trend": 1, "down_trend": 2}.get(r, -1)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'ema_fast': 500,
                   'ema_slow': 2000,
                   'enable_taker': True,
                   'flat_boost_max': 0,
                   'flat_boost_per_z': 0,
                   'flat_z_threshold': 1.5,
                   'flip_threshold': 1.2,
                   'follow_boost_max': 10,
                   'follow_boost_per_trend': 4,
                   'hard_pos_cap': 30,
                   'inventory_reduce_per_unit': 0.4,
                   'inventory_unwind_per_unit': 0.3,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 20,
                   'min_maker_size': 2,
                   'min_pos_for_take': 8,
                   'min_samples': 200,
                   'position_limit': 200,
                   'quote_trace_enabled': True,
                   'stop_z': 3.5,
                   'strategy': 'hydrogel_follow_mm',
                   'take_cooldown_ts': 2500,
                   'tighten_ticks': 1,
                   'tp_z': 2.0,
                   'trend_threshold': 1.2,
                   'ts_increment': 100,
                   'unwind_boost_max': 20,
                   'unwind_take_size': 3}}

STRATEGY_CLASSES = {"hydrogel_follow_mm": HydrogelFollowMMStrategy}

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
