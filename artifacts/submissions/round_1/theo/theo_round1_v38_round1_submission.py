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


# ── prosperity/strategies/base.py ─────────────────────────────────────────────────

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
        if not self.runtime_trace_enabled():
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
           "log": [[ts, side, price, qty], ...]}
        """
        if not self.runtime_trace_enabled():
            return

        taker_log = memory.setdefault("_taker_log", [])
        taker_log.append([int(state.timestamp), side, price, quantity])

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


# ── prosperity/strategies/naive_tight_mm_v38.py ───────────────────────────────────

def _ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


class TrendCarryMMV38Strategy(BaseStrategy):

    def _take_orders(
        self,
        order_depth: OrderDepth,
        fair: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
        buy_take_cap: int,
        sell_take_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        orders: List[Order] = []
        take_count = 0
        buy_take_remaining = min(buy_cap, max(0, buy_take_cap))
        sell_take_remaining = min(sell_cap, max(0, sell_take_cap))

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > fair - buy_edge or buy_take_remaining <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap, buy_take_remaining)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            buy_take_remaining -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < fair + sell_edge or sell_take_remaining <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap, sell_take_remaining)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            sell_take_remaining -= qty
            take_count += 1

        return orders, buy_cap, sell_cap, take_count

    def _size_quotes(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.45))
        aggravate_min = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost = float(self.params.get("unwind_boost_frac", 0.35))
        limit = float(self.position_limit())

        pressure = abs(position - inv_target) / max(1.0, limit)
        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        agg_frac = 1.0 - (1.0 - aggravate_min) * scaled
        boost = 1.0 + unwind_boost * scaled

        if position > inv_target:
            buy_size = max(1, int(round(buy_size * agg_frac)))
            sell_size = min(sell_cap, max(1, int(round(sell_size * boost))))
        elif position < inv_target:
            sell_size = max(1, int(round(sell_size * agg_frac)))
            buy_size = min(buy_cap, max(1, int(round(buy_size * boost))))

        return buy_size, sell_size

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        fv_alpha = float(self.params.get("fv_alpha", 0.05))
        short_alpha = float(self.params.get("short_alpha", 0.22))
        slope_window = int(self.params.get("slope_window", 20))
        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        trend_weight = float(self.params.get("trend_weight", 0.55))
        stretch_weight = float(self.params.get("stretch_weight", 0.75))
        trim_reference_slope_weight = float(self.params.get("trim_reference_slope_weight", 0.15))
        entry_reference_slope_weight = float(self.params.get("entry_reference_slope_weight", 0.18))

        target_bull_base = int(self.params.get("target_bull_base", 64))
        target_bull_min = int(self.params.get("target_bull_min", 56))
        target_bull_max = int(self.params.get("target_bull_max", 78))
        target_bull_per_tick = float(self.params.get("target_bull_per_tick", 2.0))
        startup_ticks = int(self.params.get("startup_ticks", 15000))
        startup_target = int(self.params.get("startup_target", 78))
        startup_fast_target = int(self.params.get("startup_fast_target", 60))
        startup_fast_take_cap = int(self.params.get("startup_fast_take_cap", 14))
        startup_cold_target = int(self.params.get("startup_cold_target", 74))
        startup_cold_until = int(self.params.get("startup_cold_until", 9000))
        startup_cold_take_cap = int(self.params.get("startup_cold_take_cap", 5))
        startup_cold_take_edge_relax = float(self.params.get("startup_cold_take_edge_relax", 1.75))
        startup_cold_buy_frac = float(self.params.get("startup_cold_buy_frac", 0.70))
        startup_cold_join_ticks = int(self.params.get("startup_cold_join_ticks", 0))
        startup_cold_anchor_size = int(self.params.get("startup_cold_anchor_size", 3))
        startup_finish_take_cap = int(self.params.get("startup_finish_take_cap", 8))
        startup_finish_take_edge_relax = float(self.params.get("startup_finish_take_edge_relax", 0.75))
        startup_finish_buy_frac = float(self.params.get("startup_finish_buy_frac", 0.90))
        startup_finish_join_ticks = int(self.params.get("startup_finish_join_ticks", 1))
        startup_finish_anchor_size = int(self.params.get("startup_finish_anchor_size", 3))
        dip_target = int(self.params.get("dip_target", 80))
        neutral_target = int(self.params.get("neutral_target", 0))
        warmup_no_sell_ticks = int(self.params.get("warmup_no_sell_ticks", 3000))

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        bid_spread_bull_under = float(self.params.get("bid_spread_bull_under", 0.0))
        bid_spread_neut = float(self.params.get("bid_spread_neut", 2.0))
        ask_spread_bull_hold = float(self.params.get("ask_spread_bull_hold", 8.0))
        ask_spread_bull_trim = float(self.params.get("ask_spread_bull_trim", 2.0))
        ask_spread_neut = float(self.params.get("ask_spread_neut", 4.0))
        bid_join_ticks = int(self.params.get("bid_join_ticks", 1))
        trim_ask_improve_ticks = int(self.params.get("trim_ask_improve_ticks", 0))
        trim_ask_local_edge = float(self.params.get("trim_ask_local_edge", 0.0))
        v18_anchor_bid_spread = float(self.params.get("v18_anchor_bid_spread", 1.0))
        v18_anchor_gap_ticks = int(self.params.get("v18_anchor_gap_ticks", 1))
        v18_anchor_buy_size = int(self.params.get("v18_anchor_buy_size", 2))

        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -6.0))
        take_buy_edge_under_boost = float(self.params.get("take_buy_edge_under_boost", 2.0))
        take_buy_edge_dip_boost = float(self.params.get("take_buy_edge_dip_boost", 1.5))
        take_buy_edge_chase_penalty = float(self.params.get("take_buy_edge_chase_penalty", 2.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 8.0))
        max_take_buy_size = int(self.params.get("max_take_buy_size", 12))
        max_take_sell_size = int(self.params.get("max_take_sell_size", 8))

        under_target_buy_mult = float(self.params.get("under_target_buy_mult", 1.50))
        startup_buy_mult = float(self.params.get("startup_buy_mult", 1.35))
        dip_buy_mult = float(self.params.get("dip_buy_mult", 1.35))
        chase_buy_frac = float(self.params.get("chase_buy_frac", 0.60))
        hold_buy_frac = float(self.params.get("hold_buy_frac", 0.75))
        hold_sell_frac = float(self.params.get("hold_sell_frac", 0.30))
        under_target_sell_frac = float(self.params.get("under_target_sell_frac", 0.0))

        dip_threshold = float(self.params.get("dip_threshold", 1.5))
        chase_threshold = float(self.params.get("chase_threshold", 2.5))
        trim_start_position = int(self.params.get("trim_start_position", 79))
        trim_floor_position = int(self.params.get("trim_floor_position", 78))
        trim_extension_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        trim_signal_edge = float(self.params.get("trim_signal_edge", 1.0))
        trim_sell_size = int(self.params.get("trim_sell_size", 1))
        trim_cooldown_ticks = int(self.params.get("trim_cooldown_ticks", 20))
        trim_take_position = int(self.params.get("trim_take_position", 80))
        trim_take_edge = float(self.params.get("trim_take_edge", 1.5))
        trim_take_stretch = float(self.params.get("trim_take_stretch", 1.5))
        trim_take_sell_size = int(self.params.get("trim_take_sell_size", 2))
        rebuy_block_ticks = int(self.params.get("rebuy_block_ticks", 35))

        spot = book.microprice if book.microprice is not None else (book.mid_price or (book.best_bid + book.best_ask) / 2.0)

        fv = _ewma(memory.get("fv"), spot, fv_alpha)
        short_ema = _ewma(memory.get("short_ema"), spot, short_alpha)
        memory["fv"] = fv
        memory["short_ema"] = short_ema

        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[: -(slope_window + 1)]

        slope = 0.0
        if len(fv_hist) >= slope_window:
            slope = fv_hist[-1] - fv_hist[-slope_window]

        stretch = spot - short_ema
        fair = fv + trend_weight * slope - stretch_weight * stretch
        trim_reference = fv + trim_reference_slope_weight * max(0.0, slope)
        entry_reference = min(fair, fv + entry_reference_slope_weight * max(0.0, slope))

        bullish = slope > bull_threshold
        on_dip = bullish and stretch <= -dip_threshold
        chasing = bullish and stretch >= chase_threshold and not on_dip
        startup_window_active = bullish and state.timestamp <= startup_ticks

        if bullish:
            dyn_target = target_bull_base + target_bull_per_tick * max(0.0, slope - bull_threshold)
            inv_target = int(round(max(target_bull_min, min(target_bull_max, dyn_target))))
            if startup_window_active:
                inv_target = max(inv_target, startup_target)
            if on_dip:
                inv_target = max(inv_target, dip_target)
            inv_target = min(self.position_limit(), inv_target)
        else:
            inv_target = neutral_target

        startup_fast_loading = startup_window_active and position < startup_fast_target
        startup_cold_loading = (
            startup_window_active
            and startup_fast_target <= position < startup_cold_target
            and state.timestamp <= startup_cold_until
            and not on_dip
        )
        startup_finish_loading = (
            startup_window_active
            and position < inv_target
            and not on_dip
            and not startup_fast_loading
            and not startup_cold_loading
        )

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        last_trim_ts = int(memory.get("last_trim_ts", -10**9))
        rebuy_block_until = int(memory.get("rebuy_block_until", -10**9))
        rebuy_blocked = bullish and not on_dip and state.timestamp < rebuy_block_until
        pre_trim_signal = (
            bullish
            and position > trim_floor_position
            and position >= trim_start_position
            and stretch >= trim_extension_threshold
            and book.best_bid >= trim_reference + trim_signal_edge
        )

        if bullish:
            buy_edge = take_buy_edge_bull
            if position < inv_target:
                buy_edge -= take_buy_edge_under_boost
            if on_dip:
                buy_edge -= take_buy_edge_dip_boost
            elif chasing:
                buy_edge += take_buy_edge_chase_penalty
            if startup_cold_loading:
                buy_edge += startup_cold_take_edge_relax
            elif startup_finish_loading:
                buy_edge += startup_finish_take_edge_relax

            sell_edge = 1_000_000.0
            buy_take_cap = max_take_buy_size
            if position < inv_target:
                buy_take_cap = max(buy_take_cap, int(round(max_take_buy_size * under_target_buy_mult)))
            if startup_fast_loading:
                buy_take_cap = max(buy_take_cap, int(round(max_take_buy_size * startup_buy_mult)))
                buy_take_cap = min(buy_take_cap, startup_fast_take_cap)
            if on_dip:
                buy_take_cap = max(buy_take_cap, int(round(max_take_buy_size * dip_buy_mult)))
            if chasing:
                buy_take_cap = max(1, int(round(buy_take_cap * chase_buy_frac)))
            if startup_cold_loading:
                buy_take_cap = min(buy_take_cap, startup_cold_take_cap)
            elif startup_finish_loading:
                buy_take_cap = min(buy_take_cap, startup_finish_take_cap)
            if pre_trim_signal or rebuy_blocked:
                buy_take_cap = 0
            sell_take_cap = 0
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut
            if position > inv_target:
                pressure = min(1.0, (position - inv_target) / max(1.0, float(self.position_limit())))
                sell_edge = sell_edge - unwind_take_edge * pressure
            buy_take_cap = max_take_buy_size
            sell_take_cap = max_take_sell_size

        take_reference = fair
        if bullish and not on_dip and (position >= trim_floor_position or startup_cold_loading or startup_finish_loading):
            take_reference = entry_reference

        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth,
            fair=take_reference,
            buy_edge=buy_edge,
            sell_edge=sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            buy_take_cap=buy_take_cap,
            sell_take_cap=sell_take_cap,
        )
        orders.extend(take_orders)

        real_best_ask = book.best_ask
        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        for ask_price, _ in book.ask_levels:
            if ask_price not in swept_ask_prices:
                real_best_ask = ask_price
                break

        real_best_bid = book.best_bid
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}
        for bid_price, _ in book.bid_levels:
            if bid_price not in swept_bid_prices:
                real_best_bid = bid_price
                break

        trim_quote_mode = (
            bullish
            and position > trim_floor_position
            and position >= trim_start_position
            and stretch >= trim_extension_threshold
            and real_best_bid >= trim_reference + trim_signal_edge
        )
        trim_take_mode = (
            trim_quote_mode
            and position >= trim_take_position
            and stretch >= trim_take_stretch
            and real_best_bid >= trim_reference + trim_take_edge
            and state.timestamp - last_trim_ts >= trim_cooldown_ticks * 100
        )

        trim_take_qty = 0
        if trim_take_mode:
            trim_take_qty = min(sell_cap, max(0, position - trim_floor_position), max(1, trim_take_sell_size))
            if trim_take_qty > 0:
                orders.append(Order(self.product, real_best_bid, -trim_take_qty))
                sell_cap -= trim_take_qty
                memory["last_trim_ts"] = state.timestamp
                memory["rebuy_block_until"] = state.timestamp + rebuy_block_ticks * 100
                rebuy_blocked = True
                take_count += 1

        buy_size, sell_size = self._size_quotes(
            position=position,
            inv_target=inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if bullish and position < inv_target:
            buy_size = min(buy_cap, max(1, int(round(buy_size * under_target_buy_mult))))
            sell_size = int(round(sell_size * under_target_sell_frac))
        elif bullish:
            buy_size = min(buy_cap, max(1, int(round(buy_size * hold_buy_frac)))) if buy_size > 0 else 0
            sell_size = min(sell_cap, max(0, int(round(sell_size * hold_sell_frac))))

        if startup_fast_loading and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * startup_buy_mult))))
        elif startup_cold_loading and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * startup_cold_buy_frac))))
        elif startup_finish_loading and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * startup_finish_buy_frac))))
        if on_dip and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * dip_buy_mult))))
        elif chasing and buy_size > 0:
            buy_size = min(buy_cap, max(1, int(round(buy_size * chase_buy_frac))))

        bid_spread = bid_spread_bull_under if bullish and position < inv_target else (bid_spread_bull if bullish else bid_spread_neut)
        bid_reference = fair
        if bullish and not on_dip and (position >= trim_floor_position or startup_cold_loading or startup_finish_loading):
            bid_reference = entry_reference
        raw_bid = round(bid_reference - bid_spread)
        bid_price = min(max(raw_bid, 1), real_best_ask - 1)
        if bullish and buy_size > 0:
            join_ticks = bid_join_ticks
            if startup_cold_loading:
                join_ticks = startup_cold_join_ticks
            elif startup_finish_loading:
                join_ticks = startup_finish_join_ticks
            bid_price = max(bid_price, min(real_best_bid + join_ticks, real_best_ask - 1))

        if bullish:
            ask_edge = ask_spread_bull_trim if trim_quote_mode else ask_spread_bull_hold
        else:
            ask_edge = ask_spread_neut

        raw_ask = round(fair + ask_edge)
        ask_price = max(raw_ask, real_best_bid + 1)
        if trim_quote_mode:
            trim_ask_target = round(trim_reference + trim_ask_local_edge)
            ask_price = max(real_best_bid + 1, min(real_best_ask - trim_ask_improve_ticks, trim_ask_target))
            ask_price = max(ask_price, real_best_bid + 1)

        if (state.timestamp <= warmup_no_sell_ticks and position <= 0) or startup_fast_loading or (bullish and position < trim_floor_position):
            sell_size = 0

        if trim_quote_mode:
            allowed_sell = max(0, position - trim_floor_position)
            sell_size = min(sell_cap, allowed_sell, max(1, trim_sell_size))
            buy_size = 0

        if rebuy_blocked and not on_dip:
            buy_size = 0

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        anchor_buy_price = None
        anchor_buy_size = 0
        anchor_mode = bullish and not on_dip and (
            rebuy_blocked or trim_quote_mode or chasing or startup_cold_loading or startup_finish_loading
        )
        if anchor_mode and buy_cap > buy_size:
            raw_anchor_bid = round(fv - v18_anchor_bid_spread)
            candidate_anchor_bid = min(max(raw_anchor_bid, 1), real_best_ask - 1)
            candidate_anchor_bid = min(candidate_anchor_bid, bid_price - v18_anchor_gap_ticks)
            if candidate_anchor_bid >= 1:
                anchor_buy_price = candidate_anchor_bid
                anchor_size = v18_anchor_buy_size
                if startup_cold_loading:
                    anchor_size = max(anchor_size, startup_cold_anchor_size)
                elif startup_finish_loading:
                    anchor_size = max(anchor_size, startup_finish_anchor_size)
                anchor_buy_size = min(max(1, anchor_size), max(0, buy_cap - buy_size))

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if anchor_buy_size > 0 and anchor_buy_price is not None:
            orders.append(Order(self.product, anchor_buy_price, anchor_buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["fair"] = fair
        memory["trim_reference"] = trim_reference
        memory["entry_reference"] = entry_reference
        memory["slope"] = slope
        memory["stretch"] = stretch
        memory["inv_target"] = inv_target
        memory["bullish"] = int(bullish)
        memory["on_dip"] = int(on_dip)
        memory["chasing"] = int(chasing)
        memory["trim_quote_mode"] = int(trim_quote_mode)
        memory["trim_take_mode"] = int(trim_take_mode)
        memory["rebuy_blocked"] = int(rebuy_blocked)
        memory["anchor_mode"] = int(anchor_mode)
        memory["startup_fast_loading"] = int(startup_fast_loading)
        memory["startup_cold_loading"] = int(startup_cold_loading)
        memory["startup_finish_loading"] = int(startup_finish_loading)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "fair": round(fair, 2),
                "fv": round(fv, 2),
                "trim_reference": round(trim_reference, 2),
                "entry_reference": round(entry_reference, 2),
                "slope": round(slope, 2),
                "stretch": round(stretch, 2),
                "bullish": int(bullish),
                "inv_target": inv_target,
                "on_dip": int(on_dip),
                "chasing": int(chasing),
                "trim_quote_mode": int(trim_quote_mode),
                "trim_take_mode": int(trim_take_mode),
                "rebuy_blocked": int(rebuy_blocked),
                "anchor_mode": int(anchor_mode),
                "startup_fast_loading": int(startup_fast_loading),
                "startup_cold_loading": int(startup_cold_loading),
                "startup_finish_loading": int(startup_finish_loading),
                "anchor_buy_price": anchor_buy_price,
                "anchor_buy_size": anchor_buy_size,
                "trim_take_qty": trim_take_qty,
                "takes": take_count,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if memory.get("fair") is not None:
            out["Reservation"] = memory["fair"]
        if memory.get("trim_reference") is not None:
            out["trim_reference"] = memory["trim_reference"]
        if memory.get("entry_reference") is not None:
            out["entry_reference"] = memory["entry_reference"]
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'INTARIAN_PEPPER_ROOT': {'aggravate_min_frac': 0.25,
                          'ask_spread_bull_hold': 8.0,
                          'ask_spread_bull_trim': 2.0,
                          'ask_spread_neut': 4.0,
                          'bid_join_ticks': 1,
                          'bid_spread_bull': 1.0,
                          'bid_spread_bull_under': 0.0,
                          'bid_spread_neut': 2.0,
                          'bull_threshold': 1.0,
                          'chase_buy_frac': 0.6,
                          'chase_threshold': 2.5,
                          'dip_buy_mult': 1.35,
                          'dip_target': 80,
                          'dip_threshold': 1.5,
                          'entry_reference_slope_weight': 0.18,
                          'fv_alpha': 0.05,
                          'hold_buy_frac': 0.75,
                          'hold_sell_frac': 0.3,
                          'inventory_soft_ratio': 0.45,
                          'last_ts_value': 999900,
                          'log_flush_ts': 10000,
                          'maker_size': 12,
                          'max_take_buy_size': 12,
                          'max_take_sell_size': 8,
                          'neutral_target': 0,
                          'position_limit': 80,
                          'rebuy_block_ticks': 35,
                          'short_alpha': 0.22,
                          'slope_window': 20,
                          'startup_buy_mult': 1.35,
                          'startup_cold_anchor_size': 3,
                          'startup_cold_buy_frac': 0.7,
                          'startup_cold_join_ticks': 0,
                          'startup_cold_take_cap': 5,
                          'startup_cold_take_edge_relax': 1.75,
                          'startup_cold_target': 74,
                          'startup_cold_until': 9000,
                          'startup_fast_take_cap': 14,
                          'startup_fast_target': 60,
                          'startup_finish_anchor_size': 3,
                          'startup_finish_buy_frac': 0.9,
                          'startup_finish_join_ticks': 1,
                          'startup_finish_take_cap': 8,
                          'startup_finish_take_edge_relax': 0.75,
                          'startup_target': 78,
                          'startup_ticks': 15000,
                          'strategy': 'trend_carry_mm_v38',
                          'stretch_weight': 0.75,
                          'take_buy_edge_bull': -6.0,
                          'take_buy_edge_chase_penalty': 2.0,
                          'take_buy_edge_dip_boost': 1.5,
                          'take_buy_edge_neut': 2.0,
                          'take_buy_edge_under_boost': 2.0,
                          'take_sell_edge_neut': 2.0,
                          'target_bull_base': 64,
                          'target_bull_max': 78,
                          'target_bull_min': 56,
                          'target_bull_per_tick': 2.0,
                          'tighten_ticks': 1,
                          'total_ticks': 10000000,
                          'trend_weight': 0.55,
                          'trim_ask_improve_ticks': 0,
                          'trim_ask_local_edge': 0.0,
                          'trim_cooldown_ticks': 20,
                          'trim_extension_threshold': 0.75,
                          'trim_floor_position': 78,
                          'trim_reference_slope_weight': 0.15,
                          'trim_sell_size': 1,
                          'trim_signal_edge': 1.0,
                          'trim_start_position': 79,
                          'trim_take_edge': 1.5,
                          'trim_take_position': 80,
                          'trim_take_sell_size': 2,
                          'trim_take_stretch': 1.5,
                          'ts_increment': 100,
                          'under_target_buy_mult': 1.5,
                          'under_target_sell_frac': 0.0,
                          'unwind_boost_frac': 0.35,
                          'unwind_take_edge': 8.0,
                          'v18_anchor_bid_spread': 1.0,
                          'v18_anchor_buy_size': 2,
                          'v18_anchor_gap_ticks': 1,
                          'warmup_no_sell_ticks': 3000}}

STRATEGY_CLASSES = {"trend_carry_mm_v38": TrendCarryMMV38Strategy}

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
        result = {}
        total_conversions = 0
        for product, strategy in self.strategies.items():
            if product not in state.order_depths:
                continue
            memory = product_memories.setdefault(product, {})
            orders, conversions = strategy.on_tick(state, memory)
            result[product] = orders
            total_conversions += conversions
        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)
