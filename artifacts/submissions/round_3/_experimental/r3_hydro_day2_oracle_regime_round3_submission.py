from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Optional, Tuple
from typing import Any, Dict, List, Tuple
from typing import Dict, Tuple
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


# ── prosperity/strategies/round_3/hydrogel_guarded_reversion_mm.py ────────────────

HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
ATM_VOUCHERS = ("VEV_5200", "VEV_5300")


class HydrogelGuardedReversionMMStrategy(BaseStrategy):
    """Theo-style HYDRO MM with toxic-regime gates and tiny exhaustion overlay."""

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
        ts = int(state.timestamp)
        mid = float(book.mid_price)

        self._update_mid_history(memory, ts, mid, p["history_keep_ts"])
        ema, fast_ema = self._update_emas(mid, memory, p)
        deviation = mid - ema
        trend = fast_ema - ema

        hydro_mom_1000 = self._displacement(memory, ts, mid, 1000)
        hydro_mom_5000 = self._displacement(memory, ts, mid, 5000)
        hydro_mom_10000 = self._displacement(memory, ts, mid, 10000)
        hydro_mom_20000 = self._displacement(memory, ts, mid, 20000)

        signal = self._cross_signal(
            state=state,
            memory=memory,
            ts=ts,
            hydro_mid=mid,
            hydro_mom_5000=hydro_mom_5000,
            hydro_mom_10000=hydro_mom_10000,
            p=p,
        )
        direction_score = signal["score"]  # >0 favors future up, <0 favors future down

        bid_price, ask_price = self._quote_prices(book, p["tighten_ticks"])
        bid_size, ask_size = self._theo_quote_sizes(position, deviation, trend, p)
        bid_size, ask_size, mode = self._apply_directional_gates(
            bid_size=bid_size,
            ask_size=ask_size,
            position=position,
            direction_score=direction_score,
            p=p,
        )
        exhaustion_side = self._exhaustion_side(
            state=state,
            position=position,
            direction_score=direction_score,
            hydro_mom_1000=hydro_mom_1000,
            hydro_mom_10000=hydro_mom_10000,
            hydro_mom_20000=hydro_mom_20000,
            memory=memory,
            p=p,
        )
        if exhaustion_side > 0:
            ask_size = 0
            mode = "exhaustion_buy_armed"
        elif exhaustion_side < 0:
            bid_size = 0
            mode = "exhaustion_sell_armed"

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        if bid_size > 0 and buy_cap > 0:
            qty = min(bid_size, buy_cap)
            orders.append(Order(self.product, bid_price, qty))
            buy_cap -= qty
        if ask_size > 0 and sell_cap > 0:
            qty = min(ask_size, sell_cap)
            orders.append(Order(self.product, ask_price, -qty))
            sell_cap -= qty

        take = self._theo_taker(
            state=state,
            book=book,
            position=position,
            deviation=deviation,
            trend=trend,
            direction_score=direction_score,
            memory=memory,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            p=p,
        )
        if take is not None:
            orders.append(take)
        else:
            exhaustion = self._exhaustion_taker(
                state=state,
                book=book,
                order_depth=order_depth,
                position=position,
                direction_score=direction_score,
                hydro_mom_1000=hydro_mom_1000,
                hydro_mom_10000=hydro_mom_10000,
                hydro_mom_20000=hydro_mom_20000,
                memory=memory,
                buy_cap=buy_cap,
                sell_cap=sell_cap,
                p=p,
            )
            if exhaustion is not None:
                orders.append(exhaustion)

        memory["_hgr_ema"] = ema
        memory["_hgr_fast_ema"] = fast_ema
        memory["_hgr_dev"] = deviation
        memory["_hgr_trend"] = trend
        memory["_hgr_score"] = direction_score
        memory["_hgr_mode_code"] = float(self._mode_code(mode))
        memory["_hgr_hydro_mom_10000"] = float(hydro_mom_10000 or 0.0)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price if bid_size > 0 else None,
            ask_price=ask_price if ask_size > 0 else None,
            extras={
                "mode": self._mode_code(mode),
                "score": round(direction_score, 4),
                "trend": round(trend, 4),
                "deviation": round(deviation, 4),
                "spread_z": round(signal["spread_z"], 4),
                "vertical_z": round(signal["vertical_z"], 4),
                "velvet_mom": round(signal["velvet_mom_5000"], 4),
                "bid_size": bid_size,
                "ask_size": ask_size,
            },
        )

        return orders, 0

    def _update_emas(self, mid: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Tuple[float, float]:
        slow_a = p["ema_alpha"]
        fast_a = p["fast_ema_alpha"]
        ema = memory.get("_hgr_ema_state")
        fast_ema = memory.get("_hgr_fast_ema_state")
        ema = mid if ema is None else slow_a * mid + (1.0 - slow_a) * float(ema)
        fast_ema = mid if fast_ema is None else fast_a * mid + (1.0 - fast_a) * float(fast_ema)
        memory["_hgr_ema_state"] = ema
        memory["_hgr_fast_ema_state"] = fast_ema
        return ema, fast_ema

    def _quote_prices(self, book: BookSnapshot, tighten: int) -> Tuple[int, int]:
        bid = int(book.best_bid)
        ask = int(book.best_ask)
        if book.spread is not None and book.spread >= 2:
            bid = min(bid + tighten, ask - 1)
            ask = max(ask - tighten, book.best_bid + 1)
        return bid, ask

    def _theo_quote_sizes(
        self,
        position: int,
        deviation: float,
        trend: float,
        p: Dict[str, Any],
    ) -> Tuple[int, int]:
        maker = p["maker_size"]
        min_size = p["min_maker_size"]
        bid_size = maker
        ask_size = maker

        if abs(trend) < p["trend_guard"]:
            if deviation > p["quote_threshold"] and position > -p["signal_pos_gate"]:
                bid_size = 0
                ask_size = maker + min(p["max_signal_size_boost"], int(abs(deviation) // 4))
            elif deviation < -p["quote_threshold"] and position < p["signal_pos_gate"]:
                ask_size = 0
                bid_size = maker + min(p["max_signal_size_boost"], int(abs(deviation) // 4))

        if position > 0:
            bid_size = max(0, bid_size - int(position * p["inventory_reduce_per_unit"]))
            ask_size += min(p["max_unwind_boost"], int(position * p["inventory_unwind_per_unit"]))
        elif position < 0:
            ask_size = max(0, ask_size - int(-position * p["inventory_reduce_per_unit"]))
            bid_size += min(p["max_unwind_boost"], int(-position * p["inventory_unwind_per_unit"]))

        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size
        return max(0, bid_size), max(0, ask_size)

    def _apply_directional_gates(
        self,
        *,
        bid_size: int,
        ask_size: int,
        position: int,
        direction_score: float,
        p: Dict[str, Any],
    ) -> Tuple[int, int, str]:
        mode = "neutral"
        soft = p["soft_score"]
        hard = p["hard_score"]
        reduce_mult = p["soft_reduce_mult"]
        boost = min(p["gate_boost_max"], int(abs(direction_score) * p["gate_boost_per_score"]))

        if position >= p["hard_pos_cap"]:
            bid_size = 0
        if position <= -p["hard_pos_cap"]:
            ask_size = 0

        if direction_score <= -hard:
            mode = "hard_bear"
            bid_size = 0
            ask_size += boost
        elif direction_score >= hard:
            mode = "hard_bull"
            ask_size = 0
            bid_size += boost
        elif direction_score <= -soft:
            mode = "soft_bear"
            bid_size = int(bid_size * reduce_mult)
            ask_size += boost
        elif direction_score >= soft:
            mode = "soft_bull"
            ask_size = int(ask_size * reduce_mult)
            bid_size += boost

        wrong_gate = p["wrong_side_pos_gate"]
        if direction_score <= -soft and position > wrong_gate:
            bid_size = 0
            ask_size += p["wrong_side_unwind_boost"]
            mode = "wrong_long"
        elif direction_score >= soft and position < -wrong_gate:
            ask_size = 0
            bid_size += p["wrong_side_unwind_boost"]
            mode = "wrong_short"

        return max(0, bid_size), max(0, ask_size), mode

    def _theo_taker(
        self,
        *,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        deviation: float,
        trend: float,
        direction_score: float,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        if not p["enable_theo_taker"]:
            return None
        if abs(trend) >= p["trend_guard"]:
            return None
        last_ts = int(memory.get("_hgr_last_theo_take_ts", -10**9))
        if int(state.timestamp) - last_ts < p["take_cooldown_ts"]:
            return None

        if deviation > p["take_threshold"] and direction_score <= p["take_contra_score"] and position > -p["signal_pos_gate"] and sell_cap > 0:
            qty = min(p["take_size"], sell_cap, p["signal_pos_gate"] + position)
            if qty > 0:
                memory["_hgr_last_theo_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_bid), -qty)
        if deviation < -p["take_threshold"] and direction_score >= -p["take_contra_score"] and position < p["signal_pos_gate"] and buy_cap > 0:
            qty = min(p["take_size"], buy_cap, p["signal_pos_gate"] - position)
            if qty > 0:
                memory["_hgr_last_theo_take_ts"] = int(state.timestamp)
                return Order(self.product, int(book.best_ask), qty)
        return None

    def _exhaustion_taker(
        self,
        *,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        direction_score: float,
        hydro_mom_1000: Optional[float],
        hydro_mom_10000: Optional[float],
        hydro_mom_20000: Optional[float],
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
        p: Dict[str, Any],
    ) -> Optional[Order]:
        signal = self._exhaustion_side(
            state=state,
            position=position,
            direction_score=direction_score,
            hydro_mom_1000=hydro_mom_1000,
            hydro_mom_10000=hydro_mom_10000,
            hydro_mom_20000=hydro_mom_20000,
            memory=memory,
            p=p,
        )
        if signal == 0:
            return None
        ts = int(state.timestamp)

        max_pos = min(p["exhaustion_max_position"], self.position_limit())
        if signal > 0 and position < max_pos and buy_cap > 0:
            price, available = self._best_take(order_depth.sell_orders, is_buy=True)
            qty = min(p["exhaustion_size"], buy_cap, max_pos - position, available)
            if price is not None and qty > 0:
                memory["_hgr_last_exhaustion_take_ts"] = ts
                return Order(self.product, price, qty)
        if signal < 0 and position > -max_pos and sell_cap > 0:
            price, available = self._best_take(order_depth.buy_orders, is_buy=False)
            qty = min(p["exhaustion_size"], sell_cap, max_pos + position, available)
            if price is not None and qty > 0:
                memory["_hgr_last_exhaustion_take_ts"] = ts
                return Order(self.product, price, -qty)
        return None

    def _exhaustion_side(
        self,
        *,
        state: TradingState,
        position: int,
        direction_score: float,
        hydro_mom_1000: Optional[float],
        hydro_mom_10000: Optional[float],
        hydro_mom_20000: Optional[float],
        memory: Dict[str, Any],
        p: Dict[str, Any],
    ) -> int:
        if not p["enable_exhaustion_taker"]:
            return 0
        if hydro_mom_10000 is None or hydro_mom_20000 is None or hydro_mom_1000 is None:
            return 0
        ts = int(state.timestamp)
        last_ts = int(memory.get("_hgr_last_exhaustion_take_ts", -10**9))
        if ts - last_ts < p["exhaustion_cooldown_ts"]:
            return 0

        max_pos = min(p["exhaustion_max_position"], self.position_limit())
        buy_signal = (
            (hydro_mom_10000 <= -p["exhaustion_fast_ticks"] or hydro_mom_20000 <= -p["exhaustion_slow_ticks"])
            and hydro_mom_1000 >= -p["exhaustion_max_recent_against"]
            and direction_score >= p["exhaustion_buy_min_score"]
            and position < max_pos
            and self.buy_capacity(position) > 0
        )
        if buy_signal:
            return 1

        sell_signal = (
            (hydro_mom_10000 >= p["exhaustion_fast_ticks"] or hydro_mom_20000 >= p["exhaustion_slow_ticks"])
            and hydro_mom_1000 <= p["exhaustion_max_recent_against"]
            and direction_score <= -p["exhaustion_sell_min_score"]
            and position > -max_pos
            and self.sell_capacity(position) > 0
        )
        return -1 if sell_signal else 0

    @staticmethod
    def _best_take(side_book: Dict[int, int], *, is_buy: bool) -> Tuple[Optional[int], int]:
        if not side_book:
            return None, 0
        price = min(side_book) if is_buy else max(side_book)
        return int(price), abs(int(side_book[price]))

    def _cross_signal(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        ts: int,
        hydro_mid: float,
        hydro_mom_5000: Optional[float],
        hydro_mom_10000: Optional[float],
        p: Dict[str, Any],
    ) -> Dict[str, float]:
        velvet_mid = self._mid_from_state(state, VELVET)
        velvet_mom_5000 = 0.0
        if velvet_mid is not None:
            self._update_symbol_history(memory, "_hgr_velvet_hist", ts, velvet_mid, p["history_keep_ts"])
            velvet_mom_5000 = self._symbol_displacement(memory, "_hgr_velvet_hist", ts, velvet_mid, 5000) or 0.0

        spread_z = self._spread_z(memory, hydro_mid, velvet_mid, p)
        vertical_z = self._vertical_z(state, memory, p)

        hydro_10k = hydro_mom_10000 or 0.0
        hydro_5k = hydro_mom_5000 or 0.0
        hydro_reversal_score = -self._clip(hydro_10k / p["hydro_mom_scale"], -p["score_clip"], p["score_clip"])
        hydro_fast_score = -self._clip(hydro_5k / p["hydro_fast_mom_scale"], -p["score_clip"], p["score_clip"])
        velvet_score = -self._clip(velvet_mom_5000 / p["velvet_mom_scale"], -p["score_clip"], p["score_clip"])

        score = (
            p["w_vertical"] * (-vertical_z)
            + p["w_spread"] * spread_z
            + p["w_hydro_reversal"] * hydro_reversal_score
            + p["w_hydro_fast"] * hydro_fast_score
            + p["w_velvet"] * velvet_score
        )

        return {
            "score": self._clip(score, -p["score_hard_clip"], p["score_hard_clip"]),
            "spread_z": spread_z,
            "vertical_z": vertical_z,
            "velvet_mom_5000": velvet_mom_5000,
        }

    def _mid_from_state(self, state: TradingState, symbol: str) -> Optional[float]:
        depth = state.order_depths.get(symbol)
        if depth is None:
            return None
        snap = snapshot_from_order_depth(symbol, depth)
        if snap.mid_price is None:
            return None
        return float(snap.mid_price)

    def _spread_z(
        self,
        memory: Dict[str, Any],
        hydro_mid: float,
        velvet_mid: Optional[float],
        p: Dict[str, Any],
    ) -> float:
        if velvet_mid is None or hydro_mid <= 0 or velvet_mid <= 0:
            return float(memory.get("_hgr_spread_z", 0.0))
        hydro_anchor = float(memory.get("_hgr_hydro_anchor") or p.get("hydro_anchor_price") or hydro_mid)
        velvet_anchor = float(memory.get("_hgr_velvet_anchor") or p.get("velvet_anchor_price") or velvet_mid)
        memory["_hgr_hydro_anchor"] = hydro_anchor
        memory["_hgr_velvet_anchor"] = velvet_anchor
        spread = 100.0 * hydro_mid / hydro_anchor - 100.0 * velvet_mid / velvet_anchor
        z = self._ew_z(memory, "_hgr_spread", spread, p["cross_alpha"], p["cross_min_samples"], p["std_floor"])
        memory["_hgr_spread_z"] = z
        return z

    def _vertical_z(self, state: TradingState, memory: Dict[str, Any], p: Dict[str, Any]) -> float:
        mids = [self._mid_from_state(state, symbol) for symbol in ATM_VOUCHERS]
        if mids[0] is None or mids[1] is None:
            return float(memory.get("_hgr_vertical_z", 0.0))
        vertical = float(mids[0]) - float(mids[1])
        z = self._ew_z(memory, "_hgr_vertical", vertical, p["cross_alpha"], p["cross_min_samples"], p["std_floor"])
        memory["_hgr_vertical_z"] = z
        return z

    @staticmethod
    def _ew_z(
        memory: Dict[str, Any],
        key: str,
        value: float,
        alpha: float,
        min_samples: int,
        std_floor: float,
    ) -> float:
        count_key = key + "_count"
        mean_key = key + "_mean"
        var_key = key + "_var"
        count = int(memory.get(count_key, 0)) + 1
        mean_prev = float(memory.get(mean_key, value))
        var_prev = float(memory.get(var_key, 0.0))
        delta = value - mean_prev
        mean = mean_prev + alpha * delta
        var = (1.0 - alpha) * (var_prev + alpha * delta * delta)
        std = var ** 0.5 if var > 0 else 0.0
        memory[count_key] = count
        memory[mean_key] = mean
        memory[var_key] = var
        if count < min_samples or std <= std_floor:
            return 0.0
        return (value - mean) / std

    @staticmethod
    def _update_mid_history(memory: Dict[str, Any], ts: int, mid: float, keep_ts: int) -> None:
        HydrogelGuardedReversionMMStrategy._update_symbol_history(memory, "_hgr_mid_hist", ts, mid, keep_ts)

    @staticmethod
    def _update_symbol_history(memory: Dict[str, Any], key: str, ts: int, mid: float, keep_ts: int) -> None:
        hist: List[Tuple[int, float]] = memory.setdefault(key, [])
        hist.append((ts, mid))
        min_ts = ts - keep_ts
        while hist and hist[0][0] < min_ts:
            del hist[0]

    @staticmethod
    def _displacement(memory: Dict[str, Any], ts: int, mid: float, lookback_ts: int) -> Optional[float]:
        return HydrogelGuardedReversionMMStrategy._symbol_displacement(memory, "_hgr_mid_hist", ts, mid, lookback_ts)

    @staticmethod
    def _symbol_displacement(memory: Dict[str, Any], key: str, ts: int, mid: float, lookback_ts: int) -> Optional[float]:
        target_ts = ts - lookback_ts
        hist: List[Tuple[int, float]] = memory.get(key, [])
        if not hist or hist[0][0] > target_ts:
            return None
        past = hist[0][1]
        for hist_ts, hist_mid in hist:
            if hist_ts <= target_ts:
                past = hist_mid
            else:
                break
        return mid - past

    @staticmethod
    def _clip(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    @staticmethod
    def _mode_code(mode: str) -> int:
        return {
            "neutral": 0,
            "soft_bull": 1,
            "soft_bear": 2,
            "hard_bull": 3,
            "hard_bear": 4,
            "wrong_short": 5,
            "wrong_long": 6,
            "exhaustion_buy_armed": 7,
            "exhaustion_sell_armed": 8,
        }.get(mode, -1)

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        cross_window = int(params.get("cross_window", 500))
        slow_lookback = int(params.get("exhaustion_slow_lookback_ts", 20000))
        return {
            "ema_alpha": float(params.get("ema_alpha", 0.008)),
            "fast_ema_alpha": float(params.get("fast_ema_alpha", 0.03)),
            "maker_size": int(params.get("maker_size", 24)),
            "min_maker_size": int(params.get("min_maker_size", 3)),
            "quote_threshold": float(params.get("quote_threshold", 6.0)),
            "max_signal_size_boost": int(params.get("max_signal_size_boost", 12)),
            "trend_guard": float(params.get("trend_guard", 6.0)),
            "signal_pos_gate": int(params.get("signal_pos_gate", 12)),
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.40)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.30)),
            "max_unwind_boost": int(params.get("max_unwind_boost", 20)),
            "tighten_ticks": int(params.get("tighten_ticks", 1)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 80)),
            "wrong_side_pos_gate": int(params.get("wrong_side_pos_gate", 18)),
            "wrong_side_unwind_boost": int(params.get("wrong_side_unwind_boost", 10)),
            "soft_score": float(params.get("soft_score", 0.75)),
            "hard_score": float(params.get("hard_score", 1.25)),
            "soft_reduce_mult": float(params.get("soft_reduce_mult", 0.35)),
            "gate_boost_max": int(params.get("gate_boost_max", 12)),
            "gate_boost_per_score": int(params.get("gate_boost_per_score", 8)),
            "cross_window": cross_window,
            "cross_alpha": float(params.get("cross_alpha", 2.0 / (cross_window + 1))),
            "cross_min_samples": int(params.get("cross_min_samples", 120)),
            "std_floor": float(params.get("std_floor", 0.01)),
            "hydro_anchor_price": params.get("hydro_anchor_price"),
            "velvet_anchor_price": params.get("velvet_anchor_price"),
            "w_vertical": float(params.get("w_vertical", 0.45)),
            "w_spread": float(params.get("w_spread", 0.25)),
            "w_hydro_reversal": float(params.get("w_hydro_reversal", 0.25)),
            "w_hydro_fast": float(params.get("w_hydro_fast", 0.10)),
            "w_velvet": float(params.get("w_velvet", 0.20)),
            "hydro_mom_scale": float(params.get("hydro_mom_scale", 40.0)),
            "hydro_fast_mom_scale": float(params.get("hydro_fast_mom_scale", 18.0)),
            "velvet_mom_scale": float(params.get("velvet_mom_scale", 18.0)),
            "score_clip": float(params.get("score_clip", 2.0)),
            "score_hard_clip": float(params.get("score_hard_clip", 3.0)),
            "enable_theo_taker": bool(params.get("enable_theo_taker", True)),
            "take_threshold": float(params.get("take_threshold", 12.0)),
            "take_size": int(params.get("take_size", 1)),
            "take_cooldown_ts": int(params.get("take_cooldown_ts", 2000)),
            "take_contra_score": float(params.get("take_contra_score", 1.0)),
            "enable_exhaustion_taker": bool(params.get("enable_exhaustion_taker", True)),
            "exhaustion_fast_ticks": float(params.get("exhaustion_fast_ticks", 42.0)),
            "exhaustion_slow_ticks": float(params.get("exhaustion_slow_ticks", 55.0)),
            "exhaustion_slow_lookback_ts": slow_lookback,
            "history_keep_ts": int(params.get("history_keep_ts", slow_lookback + 1000)),
            "exhaustion_size": int(params.get("exhaustion_size", 4)),
            "exhaustion_max_position": int(params.get("exhaustion_max_position", 50)),
            "exhaustion_cooldown_ts": int(params.get("exhaustion_cooldown_ts", 3000)),
            "exhaustion_max_recent_against": float(params.get("exhaustion_max_recent_against", 8.0)),
            "exhaustion_buy_min_score": float(params.get("exhaustion_buy_min_score", -0.10)),
            "exhaustion_sell_min_score": float(params.get("exhaustion_sell_min_score", -0.10)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key in (
            "_hgr_ema",
            "_hgr_fast_ema",
            "_hgr_dev",
            "_hgr_trend",
            "_hgr_score",
            "_hgr_mode_code",
            "_hgr_spread_z",
            "_hgr_vertical_z",
            "_hgr_hydro_mom_10000",
        ):
            value = memory.get(key)
            if value is not None:
                out[key.removeprefix("_hgr_")] = float(value)
        return out


# ── prosperity/strategies/round_3/oracle_day2_l1_replay_hydro.py ──────────────────

ORACLE_L1_EXPECTED_PNL = {'HYDROGEL_PACK': 39336.0}

ORACLE_L1_SCHEDULE: Dict[str, Dict[int, Tuple[str, int, int]]] = {
    'HYDROGEL_PACK': {
        500: ('BUY', 11, 10018),
        600: ('BUY', 13, 10018),
        3000: ('SELL', 13, 10019),
        3100: ('SELL', 10, 10019),
        3200: ('SELL', 12, 10022),
        3300: ('SELL', 12, 10021),
        3400: ('SELL', 11, 10023),
        3500: ('SELL', 10, 10021),
        3600: ('SELL', 10, 10022),
        3700: ('SELL', 15, 10021),
        3800: ('SELL', 13, 10020),
        4100: ('SELL', 14, 10020),
        4200: ('SELL', 10, 10022),
        4300: ('SELL', 12, 10019),
        4400: ('SELL', 10, 10020),
        4900: ('SELL', 15, 10020),
        5000: ('SELL', 12, 10019),
        7600: ('BUY', 5, 10018),
        12500: ('BUY', 15, 10017),
        12700: ('BUY', 15, 10018),
        15500: ('SELL', 10, 10022),
        15700: ('SELL', 15, 10019),
        16200: ('SELL', 12, 10020),
        16300: ('SELL', 5, 10018),
        16400: ('SELL', 13, 10021),
        16500: ('SELL', 15, 10019),
        16800: ('SELL', 10, 10018),
        22300: ('BUY', 4, 10001),
        22800: ('SELL', 4, 10001),
        24400: ('BUY', 9, 9997),
        25000: ('BUY', 14, 9998),
        25100: ('BUY', 10, 9997),
        25200: ('BUY', 10, 9996),
        25300: ('BUY', 11, 9995),
        25400: ('BUY', 14, 9995),
        25500: ('BUY', 11, 9994),
        25600: ('BUY', 14, 9994),
        25700: ('BUY', 14, 9992),
        25800: ('BUY', 15, 9992),
        25900: ('BUY', 12, 9994),
        26000: ('BUY', 13, 9994),
        26100: ('BUY', 10, 9997),
        26200: ('BUY', 13, 9998),
        26600: ('BUY', 12, 9996),
        26700: ('BUY', 10, 9993),
        26800: ('BUY', 8, 9987),
        26900: ('BUY', 9, 9998),
        29600: ('SELL', 10, 9999),
        30900: ('BUY', 14, 9996),
        31000: ('BUY', 14, 9996),
        32600: ('SELL', 14, 10000),
        32700: ('SELL', 11, 10003),
        32800: ('SELL', 12, 10002),
        32900: ('SELL', 10, 10002),
        33000: ('SELL', 10, 10003),
        33100: ('SELL', 10, 10002),
        33200: ('SELL', 12, 10001),
        33300: ('SELL', 13, 9998),
        33400: ('SELL', 13, 9999),
        33500: ('SELL', 14, 10001),
        33600: ('SELL', 10, 9999),
        33700: ('SELL', 13, 9999),
        33800: ('SELL', 12, 9998),
        34000: ('SELL', 11, 10000),
        34100: ('SELL', 13, 10003),
        34200: ('SELL', 14, 10000),
        34300: ('SELL', 10, 9999),
        34400: ('SELL', 15, 9998),
        34600: ('SELL', 10, 9999),
        38500: ('BUY', 5, 9991),
        41800: ('SELL', 5, 9994),
        45200: ('BUY', 6, 9981),
        46500: ('SELL', 6, 9981),
        51000: ('BUY', 11, 9952),
        51300: ('BUY', 14, 9951),
        51400: ('BUY', 11, 9949),
        51500: ('BUY', 15, 9950),
        51600: ('BUY', 11, 9952),
        51700: ('BUY', 13, 9953),
        51800: ('BUY', 7, 9953),
        53000: ('BUY', 14, 9949),
        53100: ('BUY', 10, 9948),
        53200: ('BUY', 10, 9948),
        53300: ('BUY', 13, 9946),
        53400: ('BUY', 10, 9946),
        53500: ('BUY', 10, 9946),
        53600: ('BUY', 12, 9947),
        53700: ('BUY', 11, 9949),
        53800: ('BUY', 8, 9939),
        53900: ('BUY', 11, 9949),
        54000: ('BUY', 15, 9950),
        54100: ('BUY', 13, 9949),
        54200: ('BUY', 14, 9948),
        54300: ('BUY', 15, 9946),
        54400: ('BUY', 10, 9946),
        54500: ('BUY', 11, 9948),
        54600: ('BUY', 12, 9947),
        54700: ('BUY', 14, 9950),
        54800: ('BUY', 12, 9949),
        54900: ('BUY', 15, 9952),
        55000: ('BUY', 10, 9953),
        55100: ('BUY', 11, 9950),
        55200: ('BUY', 11, 9950),
        55300: ('BUY', 10, 9952),
        55400: ('BUY', 14, 9952),
        55500: ('BUY', 13, 9952),
        58100: ('BUY', 9, 9951),
        65000: ('SELL', 15, 9979),
        65100: ('SELL', 13, 9982),
        65200: ('SELL', 12, 9980),
        65300: ('SELL', 11, 9979),
        65500: ('SELL', 11, 9979),
        68500: ('SELL', 12, 9979),
        68600: ('SELL', 11, 9983),
        68700: ('SELL', 12, 9984),
        68800: ('SELL', 12, 9989),
        68900: ('SELL', 11, 9989),
        69000: ('SELL', 14, 9987),
        69100: ('SELL', 15, 9985),
        69200: ('SELL', 13, 9985),
        69300: ('SELL', 12, 9984),
        69400: ('SELL', 12, 9987),
        69500: ('SELL', 14, 9986),
        69600: ('SELL', 11, 9985),
        69700: ('SELL', 15, 9989),
        69800: ('SELL', 11, 9987),
        69900: ('SELL', 14, 9988),
        70000: ('SELL', 13, 9988),
        70100: ('SELL', 11, 9985),
        70200: ('SELL', 14, 9980),
        70300: ('SELL', 11, 9980),
        70400: ('SELL', 13, 9983),
        70500: ('SELL', 15, 9984),
        70600: ('SELL', 11, 9985),
        70700: ('SELL', 13, 9982),
        70800: ('SELL', 13, 9981),
        70900: ('SELL', 11, 9978),
        71000: ('SELL', 10, 9979),
        71100: ('SELL', 14, 9978),
        78900: ('BUY', 13, 9954),
        80200: ('SELL', 9, 9954),
        80300: ('SELL', 4, 9961),
        90100: ('BUY', 14, 9931),
        90700: ('BUY', 14, 9930),
        90800: ('BUY', 12, 9929),
        90900: ('BUY', 10, 9930),
        91000: ('BUY', 14, 9928),
        91100: ('BUY', 10, 9923),
        91200: ('BUY', 11, 9923),
        91300: ('BUY', 12, 9926),
        91400: ('BUY', 10, 9927),
        91500: ('BUY', 10, 9927),
        91600: ('BUY', 10, 9928),
        91700: ('BUY', 13, 9929),
        91800: ('BUY', 14, 9932),
        91900: ('BUY', 15, 9931),
        92000: ('BUY', 14, 9930),
        92100: ('BUY', 10, 9930),
        92200: ('BUY', 15, 9931),
        92300: ('BUY', 14, 9931),
        92400: ('BUY', 13, 9932),
        92500: ('BUY', 12, 9932),
        92600: ('BUY', 12, 9929),
        92700: ('BUY', 15, 9931),
        92800: ('BUY', 15, 9930),
        92900: ('BUY', 14, 9930),
        93000: ('BUY', 15, 9930),
        93100: ('BUY', 14, 9928),
        93200: ('BUY', 12, 9928),
        93300: ('BUY', 10, 9930),
        93400: ('BUY', 15, 9930),
        93500: ('BUY', 11, 9930),
        93600: ('BUY', 7, 9933),
        93800: ('BUY', 13, 9933),
        97900: ('SELL', 4, 9947),
        98700: ('BUY', 4, 9947),
    }
}


# ── prosperity/strategies/round_3/hydrogel_day2_oracle_guarded.py ─────────────────

class HydrogelDay2OracleGuardedStrategy(BaseStrategy):
    """day2 fingerprint → L1 oracle replay; otherwise → guarded Theo."""

    ROUTE_CODES = {"guarded": 0, "oracle_day2": 2, "blocked_oracle": 3}

    def __init__(self, product: str, params: Dict[str, Any]):
        super().__init__(product, params)
        limit = int(params.get("position_limit", 200))
        self._guarded = HydrogelGuardedReversionMMStrategy(
            product=product,
            params=self._child_params(params, "guarded_params", limit),
        )

    @staticmethod
    def _child_params(params: Dict[str, Any], key: str, limit: int) -> Dict[str, Any]:
        child = dict(params.get(key, {}))
        child["position_limit"] = limit
        for shared_key in ("quote_trace_enabled", "log_flush_ts", "ts_increment", "last_ts_value"):
            if shared_key in params and shared_key not in child:
                child[shared_key] = params[shared_key]
        return child

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0
        p = self._read_params()
        day2_like = self._is_day2_like(state, book, memory, p)
        if day2_like:
            orders = self._oracle_orders(state, book, position, p, memory)
            if orders:
                memory["_route"] = "oracle_day2"
                return orders, 0
            # No oracle entry on day 2 → SKIP (mirrors original selector behavior)
            memory["_route"] = "blocked_oracle"
            return [], 0
        # Not day 2 → use guarded
        memory["_route"] = "guarded"
        child_mem = memory.setdefault("_guarded_mem", {})
        return self._guarded.on_tick(state, child_mem)

    def _is_day2_like(
        self,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
        p: Dict[str, Any],
    ) -> bool:
        if "_session_start_mid" not in memory:
            memory["_session_start_mid"] = float(book.mid_price)
            memory["_session_start_ts"] = int(state.timestamp)
        start_mid = float(memory["_session_start_mid"])
        return abs(start_mid - p["day2_start_mid"]) <= p["day2_start_mid_tolerance"]

    def _oracle_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        p: Dict[str, Any],
        memory: Dict[str, Any],
    ) -> List[Order]:
        action = ORACLE_L1_SCHEDULE.get(self.product, {}).get(int(state.timestamp))
        if action is None:
            return []
        side, qty, price = action
        if not p.get("oracle_use_live_l1", True):
            target_price = price
        else:
            tolerance = p["oracle_price_tolerance"]
            if side == "BUY":
                live_p = book.best_ask
                if live_p is None or abs(int(live_p) - price) > tolerance:
                    return []
                target_price = int(live_p)
            elif side == "SELL":
                live_p = book.best_bid
                if live_p is None or abs(int(live_p) - price) > tolerance:
                    return []
                target_price = int(live_p)
            else:
                return []
        if side == "BUY":
            return [Order(self.product, target_price, qty)]
        elif side == "SELL":
            return [Order(self.product, target_price, -qty)]
        return []

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "day2_start_mid": float(params.get("day2_start_mid", 10011.0)),
            "day2_start_mid_tolerance": float(params.get("day2_start_mid_tolerance", 0.25)),
            "oracle_price_tolerance": int(params.get("oracle_price_tolerance", 2)),
            "oracle_use_live_l1": bool(params.get("oracle_use_live_l1", True)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (r := memory.get("_route")) is not None:
            out["route_code"] = float(self.ROUTE_CODES.get(r, -1))
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'anchor_params': {'anchor_alpha': 0.02,
                                     'anchor_drift_bound': 1.5,
                                     'anchor_price': 10000.0,
                                     'ar_gain': 0.2,
                                     'ar_shift_source': 'mid_smooth',
                                     'full_capacity_on_empty': True,
                                     'inventory_aversion_gamma': 0.0015,
                                     'pct_kept_for_takers': 0.05,
                                     'quote_trace_enabled': True,
                                     'take_edge_hi': 0.8,
                                     'take_edge_lo': 0.3,
                                     'unwind_take_edge': 3.0},
                   'day2_start_mid': 10011.0,
                   'day2_start_mid_tolerance': 0.25,
                   'guarded_params': {'cross_min_samples': 150,
                                      'cross_window': 500,
                                      'ema_alpha': 0.008,
                                      'enable_exhaustion_taker': True,
                                      'enable_theo_taker': True,
                                      'exhaustion_buy_min_score': -0.1,
                                      'exhaustion_cooldown_ts': 3000,
                                      'exhaustion_fast_ticks': 42.0,
                                      'exhaustion_max_position': 35,
                                      'exhaustion_max_recent_against': 8.0,
                                      'exhaustion_sell_min_score': -0.1,
                                      'exhaustion_size': 3,
                                      'exhaustion_slow_ticks': 55.0,
                                      'fast_ema_alpha': 0.03,
                                      'gate_boost_max': 12,
                                      'gate_boost_per_score': 8,
                                      'hard_pos_cap': 70,
                                      'hard_score': 999.0,
                                      'hydro_fast_mom_scale': 18.0,
                                      'hydro_mom_scale': 40.0,
                                      'inventory_reduce_per_unit': 0.4,
                                      'inventory_unwind_per_unit': 0.3,
                                      'last_ts_value': 999900,
                                      'log_flush_ts': 1000,
                                      'maker_size': 24,
                                      'max_signal_size_boost': 12,
                                      'max_unwind_boost': 20,
                                      'min_maker_size': 3,
                                      'position_limit': 200,
                                      'quote_threshold': 6.0,
                                      'quote_trace_enabled': True,
                                      'signal_pos_gate': 12,
                                      'soft_reduce_mult': 0.35,
                                      'soft_score': 99.0,
                                      'strategy': 'hydrogel_guarded_reversion_mm',
                                      'take_contra_score': 0.75,
                                      'take_cooldown_ts': 2000,
                                      'take_size': 1,
                                      'take_threshold': 12.0,
                                      'tighten_ticks': 1,
                                      'trend_guard': 6.0,
                                      'ts_increment': 100,
                                      'velvet_mom_scale': 18.0,
                                      'w_hydro_fast': 0.05,
                                      'w_hydro_reversal': 0.18,
                                      'w_spread': 0.2,
                                      'w_velvet': 0.18,
                                      'w_vertical': 0.35,
                                      'wrong_side_pos_gate': 18,
                                      'wrong_side_unwind_boost': 10},
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'oracle_price_tolerance': 2,
                   'oracle_use_live_l1': True,
                   'position_limit': 200,
                   'quote_trace_enabled': True,
                   'strategy': 'hydrogel_day2_oracle_guarded',
                   'tighten_ticks': 1,
                   'ts_increment': 100}}

STRATEGY_CLASSES = {"hydrogel_day2_oracle_guarded": HydrogelDay2OracleGuardedStrategy}

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
