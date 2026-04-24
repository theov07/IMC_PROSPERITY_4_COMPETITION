from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Optional, Set, Tuple
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


# ── prosperity/strategies/round_2/leo/mm_first_v4_combo.py ────────────────────────

class MMFirstV4ComboStrategy(BaseStrategy):

    # ── Tibo's original helpers (preserved) ───────────────────────────────

    def _compute_quote_prices(
        self,
        book: BookSnapshot,
        inventory_ratio: float,
        mid_smooth: float,
    ) -> Tuple[Optional[int], Optional[int], str]:
        """L1 penny-improve by default."""
        bid_price: Optional[int] = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price: Optional[int] = (book.best_ask - 1) if book.best_ask is not None else None
        return bid_price, ask_price, "L1"

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        window = int(self.params.get("zscore_window", 50))
        buf: List[float] = memory.setdefault("_zscore_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            memory["zscore"] = None
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            memory["zscore"] = None
            return None
        z = (mid - mean) / std
        memory["zscore"] = z
        memory["_zs_mean"] = mean
        memory["_zs_std"] = std
        return z

    def _zscore_size_factors(self, memory: Dict[str, Any]) -> Tuple[float, float]:
        z = memory.get("zscore")
        if z is None:
            return 1.0, 1.0
        threshold = float(self.params.get("zscore_threshold", 1.0))
        size_scale = float(self.params.get("zscore_size_scale", 0.5))
        max_scale = float(self.params.get("zscore_max_scale", 3.0))
        excess = max(0.0, abs(z) - threshold)
        scale = min(max_scale, 1.0 + size_scale * excess)
        if z > threshold:
            return 1.0 / scale, scale
        if z < -threshold:
            return scale, 1.0 / scale
        return 1.0, 1.0

    def _compute_sizes(self, position: int, limit: int) -> Tuple[float, float]:
        base = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base * (1.0 - position / limit)
        ask_size = base * (1.0 + position / limit)
        return bid_size, ask_size

    def _dynamic_take_edge(self, memory: Dict[str, Any]) -> float:
        lo = self.params.get("take_edge_lo")
        hi = self.params.get("take_edge_hi")
        if lo is None or hi is None:
            return float(self.params.get("take_edge", 1.0))
        sigma = memory.get("sigma_smoothed")
        if sigma is None:
            return float(lo)
        vol_lo = float(self.params.get("take_edge_vol_lo", 2.0))
        vol_hi = float(self.params.get("take_edge_vol_hi", 5.0))
        if sigma <= vol_lo:
            return float(lo)
        if sigma >= vol_hi:
            return float(hi)
        t = (sigma - vol_lo) / (vol_hi - vol_lo)
        return float(lo) + t * (float(hi) - float(lo))

    # ── NEW: Leo's anchor signal (opt-in via anchor_price) ────────────────

    def _compute_anchor_signal(
        self,
        mid: float,
        book: BookSnapshot,
        mid_smooth: float,
        memory: Dict[str, Any],
    ) -> float:
        """Return fair value — either anchor-based (Leo) or mid_smooth (Tibo fallback).

        When anchor_price is set in params:
          - Use fixed anchor (anchor_alpha = 0) or slow EMA of mid (anchor_alpha > 0)
          - If anchor_alpha > 0 and anchor_drift_bound > 0, clamp the EMA to stay
            within ±anchor_drift_bound ticks of anchor_price (hybrid safety).
          - Add AR(1) shift: -ar_gain * delta, where delta = (signal - prev_signal)
            signal is chosen by ar_shift_source: "mid", "microprice", "mid_smooth"
            (microprice/mid_smooth are cleaner — less bid-ask bounce).

        When anchor_price is absent, returns mid_smooth (Tibo default, zero impact).
        """
        anchor_price = self.params.get("anchor_price")
        if anchor_price is None:
            return mid_smooth

        anchor_fixed = float(anchor_price)
        anchor_alpha = float(self.params.get("anchor_alpha", 0.0))

        if anchor_alpha > 0.0:
            ema = memory.get("_anchor_ema", anchor_fixed)
            ema = anchor_alpha * mid + (1.0 - anchor_alpha) * ema
            drift_bound = float(self.params.get("anchor_drift_bound", 0.0))
            if drift_bound > 0:
                ema = max(anchor_fixed - drift_bound,
                          min(anchor_fixed + drift_bound, ema))
            memory["_anchor_ema"] = ema
            anchor_value = ema
        else:
            anchor_value = anchor_fixed

        # AR(1) shift — choose signal source
        ar_gain = float(self.params.get("ar_gain", 0.0))
        ar_shift = 0.0
        if ar_gain > 0.0:
            source = str(self.params.get("ar_shift_source", "mid"))
            if source == "microprice":
                current = self._microprice(book)
            elif source == "mid_smooth":
                current = mid_smooth
            else:
                current = mid
            prev = memory.get("_ar_prev_signal")
            if prev is not None:
                ar_shift = -ar_gain * (current - prev)
            memory["_ar_prev_signal"] = current

        return anchor_value + ar_shift

    # ── NEW: Leo's asymmetric take edges (opt-in via unwind_take_edge) ────

    def _compute_asym_take_edges(
        self,
        base_edge: float,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[float, float]:
        """Return (buy_edge, sell_edge) adjusted by inventory pressure.

        When unwind_take_edge = 0 (default), returns (base, base) — no change.
        When unwind_take_edge > 0:
          - If long: make it EASIER to sell (reduce sell_edge) and HARDER to
            buy more (raise buy_edge).  pressure = |position| / limit.
          - If short: opposite.
        """
        unwind = float(self.params.get("unwind_take_edge", 0.0))
        if unwind <= 0:
            return base_edge, base_edge

        limit = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))

        if position > 0:
            sell_edge = max(0.0, base_edge - unwind * pressure)
            buy_edge = base_edge + unwind * pressure
        elif position < 0:
            buy_edge = max(0.0, base_edge - unwind * pressure)
            sell_edge = base_edge + unwind * pressure
        else:
            return base_edge, base_edge
        return buy_edge, sell_edge

    # ── NEW: Tibo's fire_takers but accepting asymmetric edges ────────────

    def _fire_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        buy_edge: float,
        sell_edge: float,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        """Asymmetric taker: uses separate buy_edge and sell_edge."""
        taker_buy_threshold = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")

        orders: List[Order] = []
        taker_buy_px: Set[int] = set()
        taker_sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            available = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= fair_value - buy_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, int(bid_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                taker_buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= fair_value + sell_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, int(ask_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                taker_sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px

    # ── Tibo's gap_exploit (preserved — live alpha!) ──────────────────────

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        limit: int,
        bid_size: float,
        ask_size: float,
        bid_price: Optional[int],
        ask_price: Optional[int],
        buy_cap: int,
        sell_cap: int,
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        gap_min = float(self.params.get("gap_trigger_min", 10))
        shift = float(self.params.get("OB_cleared_shift", 10))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

        z = memory.get("zscore")
        gap_gate = float(self.params.get("zscore_gap_gate", self.params.get("zscore_threshold", 1.0)))
        bid_z_ok = z is None or z >= -gap_gate
        ask_z_ok = z is None or z <= gap_gate

        orders: List[Order] = []
        memory["_gap_buy_px"] = []
        memory["_gap_sell_px"] = []

        all_bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        all_asks = sorted(order_depth.sell_orders.keys())
        if all_bids:
            memory["_last_best_bid"] = all_bids[0]
        if all_asks:
            memory["_last_best_ask"] = all_asks[0]
        last_best_bid = memory.get("_last_best_bid")
        last_best_ask = memory.get("_last_best_ask")

        remaining_bids = [p for p in all_bids if p not in taker_sell_px]
        remaining_asks = [p for p in all_asks if p not in taker_buy_px]

        gap_swept_bids: Set[int] = set()
        gap_swept_asks: Set[int] = set()

        if gap_min > 0 and gap_max_vol > 0:
            bid_gap_ok = False
            bid1 = bid2 = bid1_vol = None
            if len(remaining_bids) >= 2:
                bid1, bid2 = remaining_bids[0], remaining_bids[1]
                bid1_vol = order_depth.buy_orders[bid1]
                bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol

            bid_streak = memory.get("_gap_bid_streak", 0)
            bid_streak = bid_streak + 1 if bid_gap_ok else 0
            memory["_gap_bid_streak"] = bid_streak

            if bid_streak >= gap_confirm and bid_gap_ok and sell_cap > 0 and bid_z_ok:
                qty = min(bid1_vol, sell_cap, int(ask_size))
                if qty > 0:
                    orders.append(Order(self.product, bid1, -qty))
                    sell_cap -= qty
                    memory["_gap_sell_px"].append(bid1)
                    if qty >= bid1_vol:
                        gap_swept_bids.add(bid1)

            ask_gap_ok = False
            ask1 = ask2 = ask1_vol = None
            if len(remaining_asks) >= 2:
                ask1, ask2 = remaining_asks[0], remaining_asks[1]
                ask1_vol = -order_depth.sell_orders[ask1]
                ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol

            ask_streak = memory.get("_gap_ask_streak", 0)
            ask_streak = ask_streak + 1 if ask_gap_ok else 0
            memory["_gap_ask_streak"] = ask_streak

            if ask_streak >= gap_confirm and ask_gap_ok and buy_cap > 0 and ask_z_ok:
                qty = min(ask1_vol, buy_cap, int(bid_size))
                if qty > 0:
                    orders.append(Order(self.product, ask1, qty))
                    buy_cap -= qty
                    memory["_gap_buy_px"].append(ask1)
                    if qty >= ask1_vol:
                        gap_swept_asks.add(ask1)

        # Re-anchor passives — PRESERVES the live far-quote alpha
        final_remaining_bids = [p for p in remaining_bids if p not in gap_swept_bids]
        final_remaining_asks = [p for p in remaining_asks if p not in gap_swept_asks]

        if final_remaining_asks:
            ask_price = final_remaining_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + int(shift)   # LIVE alpha: far above

        if final_remaining_bids:
            bid_price = final_remaining_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - int(shift)   # LIVE alpha: far below

        return orders, buy_cap, sell_cap, bid_price, ask_price

    # ── NEW: Leo's toxic flow filter (opt-in via toxic_threshold) ─────────

    def _apply_toxic_flow(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        """Shrink the adverse side when signed flow is too concentrated.

        Uses prev_best_bid / prev_best_ask to infer trade direction:
          trade.price >= prev_ask → aggressive buy
          trade.price <= prev_bid → aggressive sell
        """
        toxic_threshold = float(self.params.get("toxic_threshold", 0.0))
        if toxic_threshold <= 0:
            return buy_size, sell_size

        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.75))

        flow_history = memory.setdefault("_flow_history", [])
        prev_best_bid = memory.get("_prev_best_bid")
        prev_best_ask = memory.get("_prev_best_ask")
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None:
            for trade in trades:
                if trade.price >= prev_best_ask:
                    flow_history.append(trade.quantity)
                elif trade.price <= prev_best_bid:
                    flow_history.append(-trade.quantity)
            if len(flow_history) > toxic_window:
                del flow_history[:-toxic_window]

        flow_score = 0.0
        if flow_history:
            signed = sum(flow_history)
            total = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total

        memory["_flow_score"] = flow_score

        # Positive flow_score = buying pressure → adverse for sellers → shrink sell_size
        if flow_score > toxic_threshold and sell_size > 0:
            sell_size = max(1.0, sell_size * toxic_size_frac)
        elif flow_score < -toxic_threshold and buy_size > 0:
            buy_size = max(1.0, buy_size * toxic_size_frac)
        return buy_size, sell_size

    # ── NEW: Leo's jump filter (opt-in via trend_jump_threshold) ──────────

    def _apply_jump_filter(
        self,
        book: BookSnapshot,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        """Shrink size on the side that just got joined by a 1-tick improve.

        If best_bid moved up by exactly 1 → informed buyer joining → risk for sellers.
        Reduce sell_size.  Opposite for best_ask.
        """
        threshold = float(self.params.get("trend_jump_threshold", 0.0))
        if threshold <= 0:
            return buy_size, sell_size

        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))
        prev_best_bid = memory.get("_prev_best_bid")
        prev_best_ask = memory.get("_prev_best_ask")

        bid_jumped = prev_best_bid is not None and book.best_bid == prev_best_bid + 1
        ask_jumped = prev_best_ask is not None and book.best_ask == prev_best_ask - 1

        if bid_jumped and sell_size > 0:
            sell_size = max(1.0, sell_size * jump_size_frac)
        if ask_jumped and buy_size > 0:
            buy_size = max(1.0, buy_size * jump_size_frac)
        return buy_size, sell_size

    # ── NEW: wall mid (volume-filtered fair value) ──────────────────────

    def _compute_base_mid(
        self,
        raw_mid: float,
        book: BookSnapshot,
    ) -> float:
        """Return a volume-filtered mid that ignores book levels with vol < threshold.

        Small resting orders at extreme prices are often toxic (informed traders
        baiting fills). Computing mid only from "substantial" levels gives a
        more robust fair value.

        Params:
          mid_vol_filter — minimum level volume to include (default 0 = off)

        Returns raw_mid when filter is off, or when no levels pass the filter.
        """
        vol_filter = int(self.params.get("mid_vol_filter", 0))
        if vol_filter <= 0:
            return raw_mid

        wall_bid = None
        for (p, v) in book.bid_levels:
            if v >= vol_filter:
                wall_bid = p
                break

        wall_ask = None
        for (p, v) in book.ask_levels:
            if v >= vol_filter:
                wall_ask = p
                break

        if wall_bid is None or wall_ask is None:
            return raw_mid
        return (wall_bid + wall_ask) / 2.0

    # ── NEW: taker cooldown (prevents overtrading) ──────────────────────

    def _taker_cooldown_active(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[bool, bool]:
        """Return (buy_blocked, sell_blocked) based on time since last taker fire.

        After firing a taker on side X, block new takers on that side for
        taker_cooldown_ticks ticks. Helps avoid overtrading in volatile spikes
        where the backtest fires repeatedly then reverses.

        Params:
          taker_cooldown_ticks — cooldown duration in ticks (default 0 = off)
        """
        cooldown = int(self.params.get("taker_cooldown_ticks", 0))
        if cooldown <= 0:
            return False, False

        now = int(state.timestamp)
        ts_increment = int(self.params.get("ts_increment", 100))
        last_buy = memory.get("_last_taker_buy_ts")
        last_sell = memory.get("_last_taker_sell_ts")

        buy_blocked = last_buy is not None and (now - last_buy) < cooldown * ts_increment
        sell_blocked = last_sell is not None and (now - last_sell) < cooldown * ts_increment
        return buy_blocked, sell_blocked

    def _update_taker_cooldown(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> None:
        """Record timestamp of this tick's taker fires for next-tick cooldown."""
        now = int(state.timestamp)
        if taker_buy_px:
            memory["_last_taker_buy_ts"] = now
        if taker_sell_px:
            memory["_last_taker_sell_ts"] = now

    # ── NEW: inventory-aversion bias on fair value (AS-lite) ────────────

    def _apply_inventory_bias(
        self,
        fair_value: float,
        position: int,
        memory: Dict[str, Any],
    ) -> float:
        """Shift fair value toward zero-inventory (Avellaneda-Stoikov lite).

        fair_biased = fair - gamma * position * sigma^2

        When long (position > 0):  fair shifts DOWN -> more likely to sell,
                                   less likely to buy at old fair.
        When short (position < 0): fair shifts UP.

        Complements _compute_asym_take_edges but at the fair-value level
        (affects both takers AND passives, more holistic).

        Params:
          inventory_aversion_gamma — scale factor (default 0.0 = off)
                                     typical 0.01-0.05 for OSM (sigma~1)
        """
        gamma = float(self.params.get("inventory_aversion_gamma", 0.0))
        if gamma <= 0 or position == 0:
            return fair_value

        sigma = memory.get("sigma_smoothed", 1.0)
        return fair_value - gamma * position * (sigma ** 2)

    # ── NEW: microprice size tilt (order flow predictive) ───────────────

    def _microprice_size_tilt(
        self,
        book: BookSnapshot,
        raw_mid: float,
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        """Tilt passive sizes based on microprice - mid deviation.

        When microprice > mid (bid-heavy book), expect price UP:
          increase ask_size (sell more — capture the rise)
          decrease bid_size (don't load more into a rising market)

        Orthogonal to z-score size tilt which is mean-reversion based.
        This is order-flow based (predictive, not reactive).

        Params:
          microprice_size_gain — linear gain on deviation (default 0.0 = off)
          microprice_size_threshold — min |delta| to activate (default 0.2)
        """
        gain = float(self.params.get("microprice_size_gain", 0.0))
        if gain <= 0:
            return bid_size, ask_size

        threshold = float(self.params.get("microprice_size_threshold", 0.2))
        micro = self._microprice(book)
        delta = micro - raw_mid
        if abs(delta) < threshold:
            return bid_size, ask_size

        scale = 1.0 + gain * (abs(delta) - threshold)
        if delta > 0:  # bid-heavy -> expect up -> sell more
            return bid_size / scale, ask_size * scale
        else:  # ask-heavy -> expect down -> buy more
            return bid_size * scale, ask_size / scale

    # ── NEW: adaptive spread widening in high vol ──────────────────────

    def _apply_spread_widening(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        """Widen passive quotes further from mid when volatility is elevated.

        Reduces adverse selection during volatile regimes. Applied AFTER
        _asym_passive_skew so it can counter it (skew pulls toward mid,
        widening pushes away).

        Params:
          spread_widen_vol_threshold — sigma above which widening kicks in (default 0 = off)
          spread_widen_extra_ticks   — ticks to widen each side (default 1)

        Only fires on two-sided books (preserves far-quote alpha).
        """
        threshold = float(self.params.get("spread_widen_vol_threshold", 0.0))
        if threshold <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price

        sigma = memory.get("sigma_smoothed", 0.0)
        if sigma < threshold:
            return bid_price, ask_price

        extra = int(self.params.get("spread_widen_extra_ticks", 1))
        # Push bid down, ask up (widen), but respect crossing bounds
        new_bid = max(1, bid_price - extra)
        new_ask = ask_price + extra
        if book.best_ask is not None:
            new_bid = min(new_bid, book.best_ask - 1)
        if book.best_bid is not None:
            new_ask = max(new_ask, book.best_bid + 1)
        return new_bid, new_ask

    # ── NEW: soft position target ≠ 0 ──────────────────────────────────

    def _effective_position(self, position: int) -> int:
        """Return position adjusted by a soft target for downstream helpers.

        If inventory_target != 0, helpers that react to position (asym takers,
        sizing, inv_bias) see position - target instead of raw position.

        Example: target=+5 means we want to hold +5 long, so:
          - at raw position=5, effective=0 (helpers see "flat")
          - at raw position=10, effective=+5 (helpers see "long 5")

        Params:
          inventory_target — signed target position (default 0)
        """
        target = int(self.params.get("inventory_target", 0))
        return position - target

    # ── NEW: fill-rate toxicity detector ───────────────────────────────

    def _apply_fill_rate_toxicity(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        """Detect asymmetric fill rate and pause exposed side.

        If our buy fills vastly outnumber sell fills in recent window, the
        market is dropping (we buy the dip repeatedly but can't sell).
        Conversely: sell-heavy fills -> market rising.
        Shrink the exposed side size.

        Params:
          fill_toxicity_window   — rolling window size in own_trades (default 10)
          fill_toxicity_threshold — |imbalance| ratio to trigger (default 0.7)
          fill_toxicity_frac     — size multiplier on exposed side (default 0.5)
        """
        window = int(self.params.get("fill_toxicity_window", 0))
        if window <= 0:
            return bid_size, ask_size

        history = memory.setdefault("_fill_history", [])
        for trade in state.own_trades.get(self.product, []):
            qty = float(trade.quantity)
            # +1 for buy, -1 for sell (sign of recent position change)
            if trade.buyer == "SUBMISSION":
                history.append(qty)
            elif trade.seller == "SUBMISSION":
                history.append(-qty)
        if len(history) > window:
            del history[:-window]

        if not history:
            return bid_size, ask_size

        signed = sum(history)
        total = sum(abs(x) for x in history)
        if total <= 0:
            return bid_size, ask_size

        imbalance = signed / total
        threshold = float(self.params.get("fill_toxicity_threshold", 0.7))
        frac = float(self.params.get("fill_toxicity_frac", 0.5))

        # Strong buying = we just bought repeatedly = price likely falling = adverse for us
        # -> shrink BUY side (stop buying more into falling market)
        if imbalance > threshold and bid_size > 0:
            bid_size = max(1.0, bid_size * frac)
        elif imbalance < -threshold and ask_size > 0:
            ask_size = max(1.0, ask_size * frac)
        return bid_size, ask_size

    # ── NEW: mean-rev z-score on SPREAD ────────────────────────────────

    def _apply_spread_zscore_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        """When spread is abnormally wide (z > threshold), post more aggressively.

        Spread tends to mean-revert after shocks. Wide spread → about to tighten →
        post inside the regular penny-improve (one more tick closer to mid).

        Params:
          spread_zscore_window     — rolling window for spread stats (default 100)
          spread_zscore_threshold  — z above which to skew (default 1.5)
          spread_zscore_shift      — ticks to push quotes toward mid (default 1)
        """
        window = int(self.params.get("spread_zscore_window", 0))
        if window <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price

        spread = book.best_ask - book.best_bid
        buf: List[float] = memory.setdefault("_spread_buf", [])
        buf.append(spread)
        if len(buf) > window:
            del buf[:-window]
        if len(buf) < max(10, window // 4):
            return bid_price, ask_price

        mean = sum(buf) / len(buf)
        var = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return bid_price, ask_price

        z = (spread - mean) / std
        threshold = float(self.params.get("spread_zscore_threshold", 1.5))
        if z < threshold:
            return bid_price, ask_price

        # Spread wide → expect tighten → post MORE aggressive (closer to mid)
        shift = int(self.params.get("spread_zscore_shift", 1))
        new_bid = min(book.best_ask - 1, bid_price + shift)
        new_ask = max(book.best_bid + 1, ask_price - shift)
        if new_bid >= new_ask:
            new_ask = new_bid + 1
        return new_bid, new_ask

    # ── NEW: tick-0 extreme probe (detect aggressors at extreme depths) ─

    def _probe_tick0(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Fire one-shot probes at MULTIPLE distances at session start.

        Posts bids/asks at best ± each of probe_t0_distances ticks (minimal qty)
        within the first probe_t0_max_ts timestamps. Tests multiple depths
        in a single submission — if a specific distance gets filled, we know
        aggressors cross at that depth.

        Params:
          probe_t0_distances — list/tuple of tick distances (default [] = off)
          probe_t0_qty       — qty per probe (default 1)
          probe_t0_max_ts    — last timestamp to fire (default 500)
        """
        distances = self.params.get("probe_t0_distances")
        if not distances or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap

        max_ts = int(self.params.get("probe_t0_max_ts", 500))
        now = int(state.timestamp)
        if now > max_ts:
            return [], buy_cap, sell_cap
        if memory.get("_probe_t0_fired", False):
            return [], buy_cap, sell_cap

        qty = int(self.params.get("probe_t0_qty", 1))
        orders: List[Order] = []
        for dist in distances:
            d = int(dist)
            if d <= 0:
                continue
            b_qty = min(qty, buy_cap)
            a_qty = min(qty, sell_cap)
            if b_qty > 0:
                orders.append(Order(self.product, book.best_bid - d, b_qty))
                buy_cap -= b_qty
            if a_qty > 0:
                orders.append(Order(self.product, book.best_ask + d, -a_qty))
                sell_cap -= a_qty
        if orders:
            memory["_probe_t0_fired"] = True
        return orders, buy_cap, sell_cap

    # ── NEW: momentum follower (no names, uses market_trades signed flow) ─

    def _apply_momentum_follower(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Follow strong one-sided market trade flow with aggressive takers.

        No named participants in R2 logs, so we approximate "bot-follower" by:
          1. Track signed market trade volume in rolling window
          2. If flow > threshold → aggressive buyers dominate → add taker BUY
          3. If flow < -threshold → aggressive sellers dominate → add taker SELL
        Directional bet that momentum continues.

        Params:
          momentum_window    — rolling window (default 0 = off)
          momentum_threshold — |signed/total| to trigger (default 0.8)
          momentum_qty       — taker qty (default 3)
        """
        window = int(self.params.get("momentum_window", 0))
        if window <= 0:
            return [], buy_cap, sell_cap

        history = memory.setdefault("_momentum_history", [])
        prev_bid = memory.get("_prev_best_bid")
        prev_ask = memory.get("_prev_best_ask")
        for trade in state.market_trades.get(self.product, []):
            qty = float(trade.quantity)
            if prev_ask is not None and trade.price >= prev_ask:
                history.append(qty)
            elif prev_bid is not None and trade.price <= prev_bid:
                history.append(-qty)
        if len(history) > window:
            del history[:-window]
        if not history:
            return [], buy_cap, sell_cap

        signed = sum(history)
        total = sum(abs(x) for x in history)
        if total <= 0:
            return [], buy_cap, sell_cap
        flow = signed / total

        threshold = float(self.params.get("momentum_threshold", 0.8))
        qty = int(self.params.get("momentum_qty", 3))
        orders: List[Order] = []

        if flow > threshold and buy_cap > 0:
            # Strong buying aggressors → join them, take best ask
            asks = sorted(order_depth.sell_orders.keys())
            if asks:
                ask_p = asks[0]
                available = -order_depth.sell_orders[ask_p]
                q = min(qty, buy_cap, available)
                if q > 0:
                    orders.append(Order(self.product, ask_p, q))
                    buy_cap -= q
        elif flow < -threshold and sell_cap > 0:
            bids = sorted(order_depth.buy_orders.keys(), reverse=True)
            if bids:
                bid_p = bids[0]
                volume = order_depth.buy_orders[bid_p]
                q = min(qty, sell_cap, volume)
                if q > 0:
                    orders.append(Order(self.product, bid_p, -q))
                    sell_cap -= q
        return orders, buy_cap, sell_cap

    # ── NEW: always-on far-quote probe (live aggressor detection) ───────

    def _probe_quotes(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Post small far-quote probes regardless of book state.

        Unlike gap_exploit's far-quote (fires only when a side is empty),
        this probe ALWAYS posts at last_best ± probe_distance to measure
        whether aggressors cross at that depth even in normal book conditions.

        Runs at most once every probe_interval_ticks to limit risk.

        Params:
          probe_distance        — ticks from best to post probe (default 0 = off)
          probe_qty             — size per side (default 1)
          probe_interval_ticks  — minimum ticks between probes (default 100)
        """
        probe_dist = int(self.params.get("probe_distance", 0))
        if probe_dist <= 0 or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap

        probe_qty = int(self.params.get("probe_qty", 1))
        probe_interval = int(self.params.get("probe_interval_ticks", 100))
        ts_increment = int(self.params.get("ts_increment", 100))

        now = int(state.timestamp)
        last_probe = memory.get("_last_probe_ts", -10**9)
        if (now - last_probe) < probe_interval * ts_increment:
            return [], buy_cap, sell_cap

        orders: List[Order] = []
        actual_bid_qty = min(probe_qty, buy_cap)
        actual_ask_qty = min(probe_qty, sell_cap)

        if actual_bid_qty > 0:
            probe_bid = book.best_bid - probe_dist
            orders.append(Order(self.product, probe_bid, actual_bid_qty))
            buy_cap -= actual_bid_qty

        if actual_ask_qty > 0:
            probe_ask = book.best_ask + probe_dist
            orders.append(Order(self.product, probe_ask, -actual_ask_qty))
            sell_cap -= actual_ask_qty

        if orders:
            memory["_last_probe_ts"] = now
        return orders, buy_cap, sell_cap

    # ── NEW: asymmetric passive skew (maker-aggressive unwind) ────────────

    def _asym_passive_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        position: int,
        book: BookSnapshot,
    ) -> Tuple[Optional[int], Optional[int]]:
        """Push passive quote toward mid on the unwind side when long/short.

        Complements _compute_asym_take_edges: instead of only unwinding via
        takers (which pay the spread), also post passives closer to mid on
        the unwind side to capture partial spread + higher fill probability.

        Params:
          passive_unwind_skew_ticks — max ticks to shift toward mid (default 0 = off)
          passive_unwind_trigger    — |pos|/limit above which skew activates
                                      (default 0.3; avoids skew at low inventory)

        Only fires on two-sided books (preserves far-quote live alpha).
        Scales linearly with pressure beyond the trigger.
        """
        skew_max = int(self.params.get("passive_unwind_skew_ticks", 0))
        if skew_max <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price  # preserve far-quote when one side empty

        trigger = float(self.params.get("passive_unwind_trigger", 0.3))
        limit = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if pressure < trigger:
            return bid_price, ask_price

        # Scale: 0 at trigger, skew_max at pressure=1.0
        scaled = (pressure - trigger) / max(1e-9, 1.0 - trigger)
        skew = int(round(skew_max * scaled))
        if skew <= 0:
            return bid_price, ask_price

        if position > 0:
            # long: push ask DOWN toward mid (floor = best_bid + 1 to avoid crossing)
            ask_price = max(book.best_bid + 1, ask_price - skew)
        elif position < 0:
            # short: push bid UP toward mid (cap = best_ask - 1)
            bid_price = min(book.best_ask - 1, bid_price + skew)

        return bid_price, ask_price

    # ── NEW: Leo's EOD flatten (opt-in via eod_flatten_ts) ────────────────

    def _apply_eod_flatten(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        position: int,
    ) -> Optional[List[Order]]:
        """Aggressive liquidation past eod_flatten_ts.  Returns None if inactive."""
        eod_ts = int(self.params.get("eod_flatten_ts", 0))
        if eod_ts <= 0 or state.timestamp < eod_ts or position == 0:
            return None

        orders: List[Order] = []
        if position > 0:
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                vol = order_depth.buy_orders[bid_price]
                qty = min(vol, position)
                if qty <= 0:
                    break
                orders.append(Order(self.product, bid_price, -qty))
                position -= qty
                if position == 0:
                    break
        else:
            need = -position
            for ask_price in sorted(order_depth.sell_orders):
                vol = -order_depth.sell_orders[ask_price]
                qty = min(vol, need)
                if qty <= 0:
                    break
                orders.append(Order(self.product, ask_price, qty))
                need -= qty
                if need == 0:
                    break
        return orders

    # ── Passive quotes (Tibo default, with hard stop) ─────────────────────

    def _passive_quotes(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        limit: int,
    ) -> Tuple[List[Order], int, int]:
        quote_buy = min(buy_cap, int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))

        inv_abs = abs(position) / float(limit) if limit else 0.0
        hard_stop_thr = 1.0 - float(self.params.get("pct_kept_for_takers", 0.2))
        if inv_abs >= hard_stop_thr:
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0

        orders: List[Order] = []
        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))
        return orders, buy_cap - quote_buy, sell_cap - quote_sell

    def _log_taker_fills(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        this_taker_buy_px: Set[int],
        this_taker_sell_px: Set[int],
    ) -> None:
        prev_taker_buy_px = set(memory.get("_taker_buy_px", []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        prev_gap_buy_px = set(memory.get("_gap_buy_px_prev", []))
        prev_gap_sell_px = set(memory.get("_gap_sell_px_prev", []))

        memory["_taker_buy_px"] = list(this_taker_buy_px)
        memory["_taker_sell_px"] = list(this_taker_sell_px)
        memory["_gap_buy_px_prev"] = list(memory.get("_gap_buy_px", []))
        memory["_gap_sell_px_prev"] = list(memory.get("_gap_sell_px", []))

        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY", trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                is_gap = (
                    (side == "BUY" and trade.price in prev_gap_buy_px)
                    or (side == "SELL" and trade.price in prev_gap_sell_px)
                )
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                    gap_exploit=is_gap,
                )

    # ── Orchestrator ──────────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        # EOD short-circuit
        if order_depth.buy_orders and order_depth.sell_orders:
            eod_orders = self._apply_eod_flatten(state, order_depth, position)
            if eod_orders is not None:
                return eod_orders, 0

        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0

        raw_mid = book.mid_price
        if raw_mid is None and book.best_bid is not None:
            raw_mid = float(book.best_bid)
        if raw_mid is None and book.best_ask is not None:
            raw_mid = float(book.best_ask)
        mid = raw_mid if raw_mid is not None else memory["_last_mid"]
        if raw_mid is not None:
            memory["_last_mid"] = raw_mid

        # NEW: base_mid = volume-filtered mid if mid_vol_filter > 0, else raw_mid
        # If use_microprice_as_fair=True, use microprice instead of mid as input
        if self.params.get("use_microprice_as_fair", False):
            micro = self._microprice(book)
            base_mid = micro if micro else mid
        else:
            base_mid = self._compute_base_mid(mid, book)

        mid_smooth = self._smooth_mid(base_mid, memory)
        self._compute_zscore(base_mid, memory)
        sigma = self._update_volatility(base_mid, memory)

        # NEW: compute fair value (anchor-based if anchor_price set, else mid_smooth)
        fair_value = self._compute_anchor_signal(base_mid, book, mid_smooth, memory)

        # NEW: compute effective position (for soft inventory_target != 0)
        eff_position = self._effective_position(position)

        # NEW: inventory-aversion bias on fair value (Avellaneda-Stoikov lite)
        # Uses eff_position so the target=0 assumption shifts by inventory_target
        fair_value = self._apply_inventory_bias(fair_value, eff_position, memory)

        limit = self.position_limit()
        inventory_ratio = position / float(limit) if limit else 0.0

        bid_price, ask_price, _ = self._compute_quote_prices(book, inventory_ratio, fair_value)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_size, ask_size = self._compute_sizes(position, limit)
        bid_factor, ask_factor = self._zscore_size_factors(memory)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)

        # NEW: microprice size tilt (order-flow predictive)
        bid_size, ask_size = self._microprice_size_tilt(book, mid, bid_size, ask_size)

        # NEW: asymmetric take edges (uses effective position for target support)
        base_edge = self._dynamic_take_edge(memory)
        buy_edge, sell_edge = self._compute_asym_take_edges(base_edge, eff_position, memory)

        # NEW: taker cooldown — if active, raise edge to effectively block takers that side
        buy_blocked, sell_blocked = self._taker_cooldown_active(state, memory)
        if buy_blocked:
            buy_edge = 1_000_000.0   # effectively block buy takers this tick
        if sell_blocked:
            sell_edge = 1_000_000.0

        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._fire_takers(
            order_depth, fair_value, bid_size, ask_size, buy_cap, sell_cap,
            buy_edge=buy_edge, sell_edge=sell_edge,
        )

        # NEW: update taker cooldown timestamps for next tick
        self._update_taker_cooldown(state, memory, taker_buy_px, taker_sell_px)

        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap,
            taker_buy_px, taker_sell_px,
        )

        # NEW: asym passive skew (maker-aggressive unwind, uses effective position)
        bid_price, ask_price = self._asym_passive_skew(bid_price, ask_price, eff_position, book)

        # NEW: spread widening on high vol (reduces adverse selection)
        bid_price, ask_price = self._apply_spread_widening(bid_price, ask_price, book, memory)

        # NEW: spread z-score skew (when spread is abnormally wide, tighten our quotes)
        bid_price, ask_price = self._apply_spread_zscore_skew(bid_price, ask_price, book, memory)

        # NEW: toxic flow + jump filters on passive sizing
        bid_size, ask_size = self._apply_toxic_flow(state, memory, bid_size, ask_size)
        bid_size, ask_size = self._apply_jump_filter(book, memory, bid_size, ask_size)

        # NEW: fill-rate toxicity on sizing
        bid_size, ask_size = self._apply_fill_rate_toxicity(state, memory, bid_size, ask_size)

        passive_orders, buy_cap, sell_cap = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit
        )

        # NEW: always-on far-quote probe (live-only alpha detection)
        probe_orders, buy_cap, sell_cap = self._probe_quotes(
            book, state, memory, position, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_orders)

        # NEW: tick-0 extreme probe (one-shot at session start)
        probe_t0_orders, buy_cap, sell_cap = self._probe_tick0(
            book, state, memory, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_t0_orders)

        # NEW: momentum follower (opt-in, uses market_trades direction)
        momentum_orders, buy_cap, sell_cap = self._apply_momentum_follower(
            state, order_depth, memory, buy_cap, sell_cap,
        )
        taker_orders.extend(momentum_orders)

        # Persist state for next tick
        if book.best_bid is not None:
            memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_prev_best_ask"] = book.best_ask

        self._log_taker_fills(state, memory, taker_buy_px, taker_sell_px)

        z = memory.get("zscore")
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position": position,
                "fair": round(fair_value, 2),
                "buy_edge": round(buy_edge, 2),
                "sell_edge": round(sell_edge, 2),
                "bid_size": int(bid_size),
                "ask_size": int(ask_size),
                "zscore": round(z, 4) if z is not None else None,
                "sigma": round(sigma, 4),
                "flow_score": round(memory.get("_flow_score", 0.0), 3),
            },
        )

        return taker_orders + gap_orders + passive_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        if (a := memory.get("_anchor_ema")) is not None:
            out["AnchorEMA"] = a
        z = memory.get("zscore")
        if z is not None:
            out["Z"] = float(z)
        return out


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized.py ─────────────

# Alias used inside the extracted code
StrategyBase = BaseStrategy

def _ewma(previous: Optional[float], current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


# ── TestTheo Strategy ─────────────────────────────────────────────────────────────

class TheoBestCleanGeneralizedStrategy(StrategyBase):
    """Hybrid: Full Leo fusion for buys + v34-style passive sells when at max position."""

    # ── helpers ──────────────────────────────────────────────────────────

    def _update_regression(
        self,
        *,
        state: TradingState,
        mid: float,
        memory: Dict[str, Any],
    ) -> Dict[str, float]:
        ts_increment = max(1, int(self.params.get("ts_increment", 100)))
        seed_slope = float(self.params.get("seed_slope", 0.1015))
        block_size = max(1, int(self.params.get("block_size", 100)))
        min_completed_blocks = max(1, int(self.params.get("min_completed_blocks", 5)))
        horizon = int(self.params.get("reg_horizon", 25))
        r2_floor = float(self.params.get("reg_r2_floor", 0.85))
        r2_cap = float(self.params.get("reg_r2_cap", 0.98))
        rmse_floor = float(self.params.get("reg_rmse_floor", 1.0))
        mean_revert_weight = float(self.params.get("reg_residual_reversion", 0.25))

        anchor_ts = memory.setdefault("line_anchor_ts", int(state.timestamp))
        anchor_mid = memory.setdefault("line_anchor_mid", mid)
        tick_index = max(0, int(round((int(state.timestamp) - anchor_ts) / ts_increment)))

        completed_means = memory.setdefault("block_means", [])
        completed_centers = memory.setdefault("block_centers", [])
        current_block_index = int(memory.get("current_block_index", 0))
        block_sum = float(memory.get("current_block_sum", 0.0))
        block_count = int(memory.get("current_block_count", 0))

        target_block_index = tick_index // block_size
        if target_block_index != current_block_index and block_count > 0:
            start_tick = current_block_index * block_size
            end_tick = start_tick + block_count - 1
            completed_means.append(block_sum / block_count)
            completed_centers.append((start_tick + end_tick) / 2.0)
            current_block_index = target_block_index
            block_sum = 0.0
            block_count = 0

        block_sum += mid
        block_count += 1
        memory["current_block_index"] = current_block_index
        memory["current_block_sum"] = block_sum
        memory["current_block_count"] = block_count

        current_block_mean = block_sum / max(1, block_count)
        current_block_start = current_block_index * block_size
        current_block_center = current_block_start + (block_count - 1) / 2.0

        xs: List[float] = list(completed_centers)
        ys: List[float] = list(completed_means)
        if block_count > 0:
            xs.append(current_block_center)
            ys.append(current_block_mean)

        if len(completed_means) < min_completed_blocks:
            slope = seed_slope
            intercept = anchor_mid
            fit_r2 = 0.0
            fitted_now = anchor_mid + slope * tick_index
            residual = mid - fitted_now
            rmse = max(abs(residual), rmse_floor)
            confidence = float(self.params.get("bootstrap_confidence", 0.55))
        else:
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n

            ss_xx = 0.0
            ss_xy = 0.0
            for x, y in zip(xs, ys):
                dx = x - mean_x
                dy = y - mean_y
                ss_xx += dx * dx
                ss_xy += dx * dy

            slope = ss_xy / ss_xx if ss_xx > 0 else seed_slope
            intercept = mean_y - slope * mean_x
            fitted_points = [intercept + slope * x for x in xs]
            fitted_now = intercept + slope * tick_index
            residual = mid - fitted_now

            ss_tot = sum((y - mean_y) ** 2 for y in ys)
            ss_res = sum((y - fit) ** 2 for y, fit in zip(ys, fitted_points))
            fit_r2 = 0.0 if ss_tot <= 1e-9 else max(0.0, 1.0 - ss_res / ss_tot)
            rmse = max(math.sqrt(ss_res / max(1, n)), rmse_floor)

            if r2_cap <= r2_floor:
                confidence = 1.0 if fit_r2 > r2_floor else 0.0
            else:
                confidence = max(0.0, min(1.0, (fit_r2 - r2_floor) / (r2_cap - r2_floor)))

        trend_ticks = slope * horizon * confidence
        residual_z = residual / rmse if rmse > 0 else 0.0
        forecast = intercept + slope * (tick_index + horizon)
        fair_value = forecast - mean_revert_weight * residual

        stats = {
            "slope": slope,
            "intercept": intercept,
            "fitted_now": fitted_now,
            "forecast": forecast,
            "residual": residual,
            "rmse": rmse,
            "r2": fit_r2,
            "confidence": confidence,
            "trend_ticks": trend_ticks,
            "fair_value": fair_value,
            "residual_z": residual_z,
            "block_count": float(len(completed_means)),
            "current_block_mean": current_block_mean,
        }
        memory["regression_stats"] = stats
        return stats

    def _inventory_target(
        self,
        *,
        state: TradingState,
        stats: Dict[str, float],
        position: int,
    ) -> int:
        trend_inv_per_tick = float(self.params.get("trend_inv_per_tick", 26.0))
        resid_inv_per_z = float(self.params.get("resid_inv_per_z", 7.0))
        inv_cap = int(self.params.get("trend_inventory_cap", 74))

        target = stats["trend_ticks"] * trend_inv_per_tick
        target -= stats["residual_z"] * resid_inv_per_z

        startup_target = int(self.params.get("startup_target", 40))
        startup_end_ts = int(self.params.get("startup_end_ts", 30000))
        if int(state.timestamp) <= startup_end_ts and stats["trend_ticks"] >= 0.0:
            target = max(target, startup_target)

        target = max(-inv_cap, min(inv_cap, target))
        return int(round(target))

    def _size_from_target(
        self,
        *,
        position: int,
        inv_target: int,
        stats: Dict[str, float],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        min_quote_size = int(self.params.get("min_quote_size", 1))
        base_buy = min(buy_cap, maker_size)
        base_sell = min(sell_cap, maker_size)

        if base_buy <= 0 and base_sell <= 0:
            return 0, 0

        gap = inv_target - position
        gap_scale = max(1.0, float(self.params.get("target_gap_scale", 26.0)))
        bullish_boost = max(0.0, stats["trend_ticks"]) * float(self.params.get("trend_buy_boost_per_tick", 0.24))
        bearish_boost = max(0.0, -stats["trend_ticks"]) * float(self.params.get("trend_sell_boost_per_tick", 0.20))
        cheap_boost = max(0.0, -stats["residual_z"]) * float(self.params.get("cheap_buy_boost_per_z", 0.18))
        rich_boost = max(0.0, stats["residual_z"]) * float(self.params.get("rich_sell_boost_per_z", 0.14))

        buy_mult = 1.0 + max(0.0, gap) / gap_scale + bullish_boost + cheap_boost
        sell_mult = 1.0 + max(0.0, -gap) / gap_scale + bearish_boost + rich_boost

        aggravate_cut = float(self.params.get("aggravate_cut", 0.04))
        if gap > 0:
            sell_mult *= aggravate_cut
        elif gap < 0:
            buy_mult *= aggravate_cut

        one_sided_gap = int(self.params.get("one_sided_target_gap", 24))
        strong_trend = float(self.params.get("strong_trend_ticks", 1.1))
        if gap >= one_sided_gap and stats["trend_ticks"] >= strong_trend:
            sell_mult = 0.0
        elif gap <= -one_sided_gap and stats["trend_ticks"] <= -strong_trend:
            buy_mult = 0.0

        buy_size = 0 if buy_mult <= 0.0 else min(buy_cap, max(min_quote_size, int(round(base_buy * buy_mult))))
        sell_size = 0 if sell_mult <= 0.0 else min(sell_cap, max(min_quote_size, int(round(base_sell * sell_mult))))
        return buy_size, sell_size

    def _process_premium_fills(
        self,
        state:  TradingState,
        memory: Dict[str, Any],
    ) -> None:
        """Detect gap fills from own_trades and promote them into rebuy state.

        Checks each own trade against last tick's active gap quote prices and
        against a minimum premium threshold vs the last known market price.
        Avoids assuming a posted gap quote was filled — only marks state when
        there is confirmed trade evidence.

        Params:
          empty_side_shift  — used to compute gap_fill_min_premium default
          gap_fill_min_premium — min price offset from last known market price
                                 to classify a fill as a gap fill (default max(30, shift//2))

        Side effects on memory:
          _last_gap_sell_ts, _last_gap_sell_price, _last_gap_sell_qty
          _last_gap_buy_ts,  _last_gap_buy_price,  _last_gap_buy_qty
        """
        empty_side_shift      = int(self.params.get("empty_side_shift", 85))
        gap_fill_min_premium  = int(self.params.get("gap_fill_min_premium", max(30, empty_side_shift // 2)))
        last_best_bid         = memory.get("_last_best_bid")
        last_best_ask         = memory.get("_last_best_ask")
        prev_gap_sell_quotes  = {int(p) for p in memory.get("_active_gap_sell_quotes", [])}
        prev_gap_buy_quotes   = {int(p) for p in memory.get("_active_gap_buy_quotes", [])}

        for trade in state.own_trades.get(self.product, []):
            trade_price = int(trade.price)
            if trade.seller == "SUBMISSION":
                is_gap_fill = trade_price in prev_gap_sell_quotes
                if not is_gap_fill and last_best_ask is not None:
                    is_gap_fill = trade_price >= int(last_best_ask) + gap_fill_min_premium
                if is_gap_fill:
                    memory["_last_gap_sell_ts"]    = int(trade.timestamp)
                    memory["_last_gap_sell_price"] = trade_price
                    memory["_last_gap_sell_qty"]   = int(trade.quantity)
            elif trade.buyer == "SUBMISSION":
                is_gap_fill = trade_price in prev_gap_buy_quotes
                if not is_gap_fill and last_best_bid is not None:
                    is_gap_fill = trade_price <= int(last_best_bid) - gap_fill_min_premium
                if is_gap_fill:
                    memory["_last_gap_buy_ts"]    = int(trade.timestamp)
                    memory["_last_gap_buy_price"] = trade_price
                    memory["_last_gap_buy_qty"]   = int(trade.quantity)

    def _handle_onesided_book(
        self,
        book:            BookSnapshot,
        position:        int,
        memory:          Dict[str, Any],
        gap_sell_quotes: List[int],
        gap_buy_quotes:  List[int],
    ) -> Optional[Tuple[List[Order], int]]:
        """Handle one-sided or fully empty order book by posting wide quotes.

        When both sides are absent, post a buy at last_known - shift and a sell
        at last_known + shift (if position allows). Returns early with those orders.
        When only one side is absent, post a single wide quote on the missing side.
        When both sides are present, returns None so normal logic continues.

        Also updates memory with last known best bid/ask and recent ask history
        before returning early.

        Params:
          empty_side_shift             — tick offset for wide quotes (default 85)
          ask_gap_sell_enable_position — min position to post a gap sell (default position_limit)
          ask_gap_quote_size           — max size for a gap sell quote (default 8)

        Returns (orders, 0) if the book is one-sided/empty, else None.
        """
        orders: List[Order] = []
        empty_side_shift          = int(self.params.get("empty_side_shift", 85))
        ask_gap_sell_enable_pos   = int(self.params.get("ask_gap_sell_enable_position", self.position_limit()))
        ask_gap_quote_size        = int(self.params.get("ask_gap_quote_size", 8))
        last_best_bid             = memory.get("_last_best_bid")
        last_best_ask             = memory.get("_last_best_ask")

        # Fully empty book
        if book.best_bid is None and book.best_ask is None:
            if last_best_bid is None and last_best_ask is None:
                return orders, 0
            ref           = last_best_bid if last_best_bid is not None else last_best_ask
            gap_buy_price = ref - empty_side_shift
            gap_sell_price = ref + empty_side_shift
            orders.append(Order(self.product, gap_buy_price, self.buy_capacity(position)))
            gap_buy_quotes.append(gap_buy_price)
            if position >= ask_gap_sell_enable_pos:
                gap_sell_qty = min(self.sell_capacity(position), ask_gap_quote_size)
                if gap_sell_qty > 0:
                    orders.append(Order(self.product, gap_sell_price, -gap_sell_qty))
                    gap_sell_quotes.append(gap_sell_price)
            memory["_active_gap_sell_quotes"] = gap_sell_quotes[:]
            memory["_active_gap_buy_quotes"]  = gap_buy_quotes[:]
            memory["_gap_sell_px"]            = gap_sell_quotes[:]
            memory["_gap_buy_px"]             = gap_buy_quotes[:]
            return orders, 0

        # Only asks visible — post a wide bid below last known bid
        if book.best_bid is None:
            ref           = last_best_bid if last_best_bid is not None else book.best_ask - 1
            gap_buy_price = ref - empty_side_shift
            orders.append(Order(self.product, gap_buy_price, self.buy_capacity(position)))
            gap_buy_quotes.append(gap_buy_price)

        # Only bids visible — post a wide ask above last known ask
        elif book.best_ask is None:
            ref            = last_best_ask if last_best_ask is not None else book.best_bid + 1
            gap_sell_price = ref + empty_side_shift
            if position >= ask_gap_sell_enable_pos:
                gap_sell_qty = min(self.sell_capacity(position), ask_gap_quote_size)
                if gap_sell_qty > 0:
                    orders.append(Order(self.product, gap_sell_price, -gap_sell_qty))
                    gap_sell_quotes.append(gap_sell_price)

        # Update last known prices and recent ask history
        if book.best_bid is not None:
            memory["_last_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_best_ask"] = book.best_ask
            recent_best_asks             = memory.setdefault("_recent_best_asks", [])
            gap_scout_recent_ask_window  = int(self.params.get("gap_scout_recent_ask_window", 6))
            recent_best_asks.append(int(book.best_ask))
            if len(recent_best_asks) > gap_scout_recent_ask_window:
                del recent_best_asks[:-gap_scout_recent_ask_window]

        # One side is still missing: flush trackers and return
        if book.best_bid is None or book.best_ask is None:
            memory["_active_gap_sell_quotes"] = gap_sell_quotes[:]
            memory["_active_gap_buy_quotes"]  = gap_buy_quotes[:]
            memory["_gap_sell_px"]            = gap_sell_quotes[:]
            memory["_gap_buy_px"]             = gap_buy_quotes[:]
            return orders, 0

        return None

    def _update_ewma_signals(
        self,
        spot:   float,
        fv:     float,
        memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float, float, float]:
        """Update slow/fast EWMAs, slope window, and derived stretch signals.

        ewma_fv    — slow EWMA of microprice (tracks the long-run trend level)
        short_ema  — fast EWMA of microprice (tracks short-term momentum)
        ewma_slope — change of ewma_fv over the last slope_window ticks
        stretch    — spot minus short_ema (positive = price running above MA)
        trim_reference — ewma_fv nudged forward by slope (signals for trimming)
        entry_reference — min(fv, trim_reference) used as bid anchor price

        Params:
          fv_alpha                  — slow EWMA alpha (default 0.05)
          short_alpha               — fast EWMA alpha (default 0.22)
          slope_window              — window for EWMA slope (default 20)
          trim_reference_slope_weight — weight applied to slope (default 0.15)

        Returns (ewma_fv, short_ema, ewma_slope, stretch, trim_reference, entry_reference).
        """
        fv_alpha     = float(self.params.get("fv_alpha", 0.05))
        short_alpha  = float(self.params.get("short_alpha", 0.22))
        slope_window = int(self.params.get("slope_window", 20))

        ewma_fv   = _ewma(memory.get("ewma_fv"), spot, fv_alpha)
        short_ema = _ewma(memory.get("short_ema"), spot, short_alpha)
        memory["ewma_fv"]   = ewma_fv
        memory["short_ema"] = short_ema

        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(ewma_fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[:-(slope_window + 1)]

        ewma_slope = 0.0
        if len(fv_hist) >= slope_window:
            ewma_slope = fv_hist[-1] - fv_hist[-slope_window]

        stretch         = spot - short_ema
        trim_reference  = ewma_fv + float(self.params.get("trim_reference_slope_weight", 0.15)) * max(0.0, ewma_slope)
        entry_reference = min(fv, trim_reference)

        return ewma_fv, short_ema, ewma_slope, stretch, trim_reference, entry_reference

    def _compute_regime(
        self,
        state:           TradingState,
        stats:           Dict[str, float],
        spot:            float,
        stretch:         float,
        book:            BookSnapshot,
        position: int,
        memory:   Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute all per-tick regime flags, inventory targets, and taker limits.

        Covers: bullish/build_phase/on_dip/chasing flags, startup sub-phases
        (fast/cold/chase/anchor), pullback tracking, gap_rebuy_mode, trim mode,
        and rebuy_blocked. Also derives buy_edge and buy_take_cap so that
        _buy_takers receives a fully resolved policy without re-reading params.

        Returns a dict with all flags needed downstream by _compute_quote_prices,
        _buy_takers, _sell_takers, _compute_passive_sizes, and _gap_trap_quotes.
        """
        trend_ticks = stats["trend_ticks"]
        residual_z  = stats["residual_z"]
        ts          = int(state.timestamp)

        # ── direction and build phase ──────────────────────────────────
        bull_threshold  = float(self.params.get("bull_threshold", 1.0))
        bullish         = trend_ticks > bull_threshold
        fastfill_target = int(self.params.get("fastfill_target", self.position_limit()))
        fastfill_end_ts = int(self.params.get("fastfill_end_ts", 15000))
        build_phase     = bullish and (position < fastfill_target or ts <= fastfill_end_ts)
        base_target     = self._inventory_target(state=state, stats=stats, position=position)
        inv_target      = max(base_target, fastfill_target) if build_phase else base_target

        # ── dip / chase signals ────────────────────────────────────────
        dip_threshold   = float(self.params.get("dip_threshold", 1.0))
        chase_threshold = float(self.params.get("chase_threshold", 1.25))
        cheap_z         = float(self.params.get("cheap_residual_z", 0.9))
        rich_z          = float(self.params.get("rich_residual_z", 1.0))
        on_dip          = bullish and (stretch <= -dip_threshold or residual_z <= -cheap_z)

        # ── startup sub-phases ─────────────────────────────────────────
        startup_fast_target           = int(self.params.get("startup_fast_target", min(fastfill_target, 32)))
        startup_fast_take_cap         = int(self.params.get("startup_fast_take_cap", 12))
        startup_fast_passive_buy      = int(self.params.get("startup_fast_passive_buy", 8))
        startup_cold_take_cap         = int(self.params.get("startup_cold_take_cap", 4))
        startup_cold_passive_buy      = int(self.params.get("startup_cold_passive_buy", 3))
        startup_cold_join_ticks       = int(self.params.get("startup_cold_join_ticks", 0))
        startup_cold_take_edge        = float(self.params.get("startup_cold_take_edge", 3.0))
        startup_chase_take_cap        = int(self.params.get("startup_chase_take_cap", 1))
        startup_chase_passive_buy     = int(self.params.get("startup_chase_passive_buy", 1))
        startup_chase_take_edge       = float(self.params.get("startup_chase_take_edge", 4.0))
        startup_pullback_ticks        = float(self.params.get("startup_pullback_ticks", 2.0))
        startup_pre_pullback_target   = int(self.params.get("startup_pre_pullback_target", 48))
        startup_post_pullback_target  = int(self.params.get("startup_post_pullback_target", 64))
        startup_delayed_finish_ts     = int(self.params.get("startup_delayed_finish_ts", 3000))
        startup_release_stretch       = float(self.params.get("startup_release_stretch", 1.0))
        startup_release_take_cap      = int(self.params.get("startup_release_take_cap", 8))
        startup_dip_take_edge_boost   = float(self.params.get("startup_dip_take_edge_boost", 1.0))
        startup_anchor_bid_spread     = float(self.params.get("startup_anchor_bid_spread", 1.0))
        startup_anchor_gap_ticks      = int(self.params.get("startup_anchor_gap_ticks", 1))
        startup_anchor_size           = int(self.params.get("startup_anchor_size", 4))

        startup_window_active = build_phase and ts <= fastfill_end_ts
        startup_fast_loading  = startup_window_active and position < startup_fast_target
        startup_cold_loading  = (
            startup_window_active
            and startup_fast_target <= position < inv_target
            and not on_dip
        )

        startup_peak_spot = float(memory.get("startup_peak_spot", spot))
        if startup_window_active:
            startup_peak_spot = max(startup_peak_spot, float(spot))
            memory["startup_peak_spot"] = startup_peak_spot
        else:
            memory["startup_peak_spot"] = float(spot)

        current_pullback_ready = startup_peak_spot - float(spot) >= startup_pullback_ticks
        pullback_seen          = bool(memory.get("startup_pullback_seen", False)) or current_pullback_ready
        memory["startup_pullback_seen"] = int(pullback_seen) if startup_window_active else 0

        build_release_ready = pullback_seen and stretch <= -startup_release_stretch

        active_build_target = inv_target
        if startup_window_active and ts <= startup_delayed_finish_ts and not build_release_ready:
            if not pullback_seen:
                active_build_target = min(active_build_target, startup_pre_pullback_target)
            else:
                active_build_target = min(active_build_target, startup_post_pullback_target)

        # ── gap rebuy mode ─────────────────────────────────────────────
        last_gap_sell_ts    = int(memory.get("_last_gap_sell_ts", -(10 ** 9)))
        last_gap_sell_price = memory.get("_last_gap_sell_price")
        gap_rebuy_window      = int(self.params.get("gap_rebuy_window", 2500))
        gap_rebuy_min_discount = float(self.params.get("gap_rebuy_min_discount", 20.0))
        gap_rebuy_age         = ts - last_gap_sell_ts
        gap_rebuy_discount    = 0.0
        if last_gap_sell_price is not None:
            gap_rebuy_discount = float(last_gap_sell_price) - float(book.best_ask)
        gap_rebuy_mode = (
            bullish
            and last_gap_sell_price is not None
            and 0 <= gap_rebuy_age <= gap_rebuy_window
            and position < inv_target
            and gap_rebuy_discount >= gap_rebuy_min_discount
        )
        if gap_rebuy_mode:
            active_build_target = inv_target

        chasing = bullish and not on_dip and (
            stretch >= chase_threshold
            or (startup_cold_loading and not pullback_seen)
        )

        # ── trim mode ──────────────────────────────────────────────────
        trim_start_position      = int(self.params.get("trim_start_position", 79))
        trim_extension_threshold = float(self.params.get("trim_extension_threshold", 0.75))
        trim_quote_mode = (
            bullish
            and not build_phase
            and position >= trim_start_position
            and stretch >= trim_extension_threshold
        )
        trim_take_mode = False
        trim_take_qty  = 0

        # ── rebuy block ────────────────────────────────────────────────
        rebuy_block_until = int(memory.get("rebuy_block_until", -(10 ** 9)))
        rebuy_blocked     = bullish and ts < rebuy_block_until

        # ── buy edge ──────────────────────────────────────────────────
        take_buy_edge_bull      = float(self.params.get("take_buy_edge_bull", -8.0))
        take_buy_edge_neut      = float(self.params.get("take_buy_edge_neut", 2.0))
        fastfill_buy_edge_boost = float(self.params.get("fastfill_buy_edge_boost", 0.0))

        if bullish:
            buy_edge = take_buy_edge_bull
            if build_phase:
                buy_edge -= fastfill_buy_edge_boost
            elif residual_z >= rich_z:
                buy_edge = take_buy_edge_neut
            if on_dip:
                buy_edge -= startup_dip_take_edge_boost
            if startup_cold_loading:
                buy_edge = max(buy_edge, startup_cold_take_edge)
            if chasing:
                buy_edge = max(buy_edge, startup_chase_take_edge)
        else:
            buy_edge = take_buy_edge_neut

        buy_cap_initial = self.buy_capacity(position)
        buy_take_cap    = buy_cap_initial
        if build_phase:
            if startup_fast_loading:
                buy_take_cap = min(buy_take_cap, startup_fast_take_cap)
            if startup_cold_loading:
                buy_take_cap = min(buy_take_cap, startup_cold_take_cap)
            if chasing:
                buy_take_cap = min(buy_take_cap, startup_chase_take_cap)
            if build_release_ready:
                buy_take_cap = min(buy_take_cap, startup_release_take_cap)

        if rebuy_blocked:
            buy_edge     = 1_000_000.0
            buy_take_cap = 0
        elif gap_rebuy_mode:
            gap_rebuy_buy_edge  = float(self.params.get("gap_rebuy_buy_edge", -10.0))
            gap_rebuy_take_cap  = int(self.params.get("gap_rebuy_take_cap", 8))
            buy_edge     = min(buy_edge, gap_rebuy_buy_edge)
            buy_take_cap = min(buy_cap_initial, max(buy_take_cap, gap_rebuy_take_cap))

        return {
            "timestamp":              ts,
            "bullish":                bullish,
            "build_phase":            build_phase,
            "inv_target":             inv_target,
            "active_build_target":    active_build_target,
            "on_dip":                 on_dip,
            "startup_window_active":  startup_window_active,
            "startup_fast_loading":   startup_fast_loading,
            "startup_cold_loading":   startup_cold_loading,
            "startup_fast_passive_buy":  startup_fast_passive_buy,
            "startup_cold_passive_buy":  startup_cold_passive_buy,
            "startup_chase_passive_buy": startup_chase_passive_buy,
            "startup_anchor_bid_spread": startup_anchor_bid_spread,
            "startup_anchor_gap_ticks":  startup_anchor_gap_ticks,
            "startup_anchor_size":       startup_anchor_size,
            "startup_cold_join_ticks":   startup_cold_join_ticks,
            "pullback_seen":          pullback_seen,
            "current_pullback_ready": current_pullback_ready,
            "build_release_ready":    build_release_ready,
            "gap_rebuy_mode":         gap_rebuy_mode,
            "gap_rebuy_discount":     gap_rebuy_discount,
            "chasing":                chasing,
            "rebuy_blocked":          rebuy_blocked,
            "buy_edge":               buy_edge,
            "buy_take_cap":           buy_take_cap,
            "trim_quote_mode":        trim_quote_mode,
            "trim_take_mode":         trim_take_mode,
            "trim_take_qty":          trim_take_qty,
            "rich_z":                 rich_z,
            "cheap_z":                cheap_z,
        }

    def _compute_quote_prices(
        self,
        book:            BookSnapshot,
        fv:              float,
        stats:           Dict[str, float],
        regime:          Dict[str, Any],
        entry_reference: float,
    ) -> Tuple[int, int]:
        """Compute passive bid and ask quote prices.

        Base prices are derived from fair value ± spread (bull or neutral).
        bid_extra ticks are added based on trend strength and residual cheapness.
        During build phase, bid_price is nudged up toward entry_reference to
        capture more of the trend move in cold/chase sub-phases.

        Returns (bid_price, ask_price) — both sides guaranteed non-None here
        since _handle_onesided_book has already filtered the one-sided case.
        """
        bullish             = regime["bullish"]
        build_phase         = regime["build_phase"]
        startup_cold_loading = regime["startup_cold_loading"]
        chasing             = regime["chasing"]
        trend_ticks         = stats["trend_ticks"]
        residual_z          = stats["residual_z"]
        cheap_z             = regime["cheap_z"]

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))

        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)

        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # Trend / residual bid extras
        bid_extra   = 0
        strong      = float(self.params.get("strong_trend_ticks", 1.1))
        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        if trend_ticks >= strong:
            bid_extra += 1
        if trend_ticks >= very_strong:
            bid_extra += 1
        if residual_z <= -cheap_z:
            bid_extra += 1

        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        bid_extra     = max(0, min(max_bid_extra, bid_extra))
        bid_price     = min(book.best_ask - 1, bid_price + bid_extra)

        # Build-phase bid anchoring
        startup_anchor_bid_spread = regime["startup_anchor_bid_spread"]
        startup_cold_join_ticks   = regime["startup_cold_join_ticks"]
        if build_phase:
            if startup_cold_loading or chasing:
                raw_entry_bid = round(entry_reference - startup_anchor_bid_spread)
                bid_price     = min(book.best_ask - 1, max(raw_entry_bid, 1))
                bid_price     = max(bid_price, min(book.best_bid + startup_cold_join_ticks, book.best_ask - 1))
            else:
                bid_price = max(bid_price, min(book.best_bid + 1, book.best_ask - 1))

        return bid_price, ask_price

    def _buy_takers(
        self,
        order_depth: OrderDepth,
        fv:          float,
        position:    int,
        buy_cap:     int,
        regime:      Dict[str, Any],
    ) -> Tuple[List[Order], int, int, Set[int]]:
        """Emit aggressive buy orders when ask price is below the fair-value edge.

        Iterates sell_orders from cheapest upward, buying each level while:
          - ask_p <= fv - buy_edge  (fair-value condition)
          - buy_cap and buy_take_cap > 0  (capacity guards)
          - During build phase: room to active_build_target is not exhausted

        deep_take_guard restricts multi-level taker sweeps during early ticks
        to avoid paying too far through the market.

        Returns (orders, remaining_buy_cap, pending_buy, swept_ask_prices).
        """
        orders:         List[Order] = []
        swept_prices:   Set[int]    = set()
        pending_buy     = 0
        buy_take_cap    = regime["buy_take_cap"]

        build_phase         = regime["build_phase"]
        active_build_target = regime["active_build_target"]
        buy_edge            = regime["buy_edge"]
        ts                  = regime["timestamp"]

        deep_take_guard_end_ts = int(self.params.get("fastfill_deep_take_guard_end_ts", 0))
        deep_take_max_gap      = int(self.params.get("fastfill_deep_take_max_gap_ticks", 999999))
        deep_take_guard        = build_phase and ts <= deep_take_guard_end_ts
        first_take_ask: Optional[int] = None

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0 or buy_take_cap <= 0:
                break
            room = max(0, active_build_target - position - pending_buy)
            if build_phase and room <= 0:
                break
            if first_take_ask is None:
                first_take_ask = ask_p
            elif deep_take_guard and ask_p - first_take_ask > deep_take_max_gap:
                break
            qty = min(
                -order_depth.sell_orders[ask_p],
                buy_cap,
                buy_take_cap,
                room if build_phase else buy_cap,
            )
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            swept_prices.add(ask_p)
            buy_cap     -= qty
            buy_take_cap -= qty
            pending_buy  += qty

        return orders, buy_cap, pending_buy, swept_prices

    def _sell_takers(
        self,
        order_depth: OrderDepth,
        fv:          float,
        position:    int,
        sell_cap:    int,
        regime:      Dict[str, Any],
    ) -> Tuple[List[Order], int, int]:
        """Emit aggressive sell orders for neutral unwind (non-bullish, non-trim regimes).

        Only fires when: not build_phase AND not trim_quote_mode AND not bullish.
        Sell edge is tightened proportionally when position is above inv_target
        to accelerate unwind under inventory pressure.

        Returns (orders, remaining_sell_cap, pending_sell).
        """
        orders:      List[Order] = []
        pending_sell = 0

        build_phase     = regime["build_phase"]
        trim_quote_mode = regime["trim_quote_mode"]
        bullish         = regime["bullish"]
        inv_target      = regime["inv_target"]

        if not build_phase and not trim_quote_mode and not bullish:
            sell_edge = float(self.params.get("take_sell_edge_neut", 2.0))
            if position > inv_target:
                pressure  = min(1.0, (position - inv_target) / max(1.0, float(self.position_limit())))
                sell_edge = sell_edge - float(self.params.get("unwind_take_edge", 10.0)) * pressure
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fv + sell_edge or sell_cap <= 0:
                    break
                qty = min(order_depth.buy_orders[bid_p], sell_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap     -= qty
                pending_sell += qty

        return orders, sell_cap, pending_sell

    def _compute_passive_sizes(
        self,
        position:         int,
        buy_cap:          int,
        sell_cap:         int,
        pending_buy:      int,
        pending_sell:     int,
        stats:            Dict[str, float],
        regime:           Dict[str, Any],
        entry_reference:  float,
        book:             BookSnapshot,
        bid_price:        int,
        ask_price:        int,
        buy_taker_prices: Set[int],
    ) -> Tuple[int, int, Optional[int], int, int, bool]:
        """Compute passive bid/ask sizes, anchor order, and final ask_price.

        Sizing via _size_from_target; then adjusted for:
          - build_phase overrides (suppress sells, cap/floor buys by sub-phase)
          - anchor bid in cold/chase sub-phases (secondary bid at entry_reference)
          - gap_rebuy_mode (boost passive buy, cap to inv_target room)
          - hold_sell_size logic (passive sell at top of book when near max position)
          - rebuy_block (zero buys while blocked)
          - crossing prevention (ask_price = bid_price + 1 if crossed)

        Returns (buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode).
        """
        build_phase         = regime["build_phase"]
        gap_rebuy_mode      = regime["gap_rebuy_mode"]
        bullish             = regime["bullish"]
        rebuy_blocked       = regime["rebuy_blocked"]
        inv_target          = regime["inv_target"]
        active_build_target = regime["active_build_target"]
        on_dip              = regime["on_dip"]
        chasing             = regime["chasing"]
        startup_fast_loading     = regime["startup_fast_loading"]
        startup_cold_loading     = regime["startup_cold_loading"]
        startup_fast_passive_buy = regime["startup_fast_passive_buy"]
        startup_cold_passive_buy = regime["startup_cold_passive_buy"]
        startup_chase_passive_buy = regime["startup_chase_passive_buy"]
        startup_anchor_bid_spread = regime["startup_anchor_bid_spread"]
        startup_anchor_gap_ticks  = regime["startup_anchor_gap_ticks"]
        startup_anchor_size       = regime["startup_anchor_size"]

        # Effective best ask after filtering taker-swept levels
        real_best_bid = book.best_bid
        real_best_ask = book.best_ask
        for ap, _ in book.ask_levels:
            if ap not in buy_taker_prices:
                real_best_ask = ap
                break

        buy_size, sell_size = self._size_from_target(
            position=position + pending_buy - pending_sell,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        anchor_buy_price: Optional[int] = None
        anchor_buy_size                 = 0
        anchor_mode                     = False

        if build_phase:
            sell_size = 0
            if startup_fast_loading:
                buy_size = min(buy_size, min(buy_cap, startup_fast_passive_buy))
            elif startup_cold_loading:
                buy_size = min(buy_size, min(buy_cap, startup_cold_passive_buy))
            else:
                buy_size = max(buy_size, min(buy_cap, int(self.params.get("fastfill_min_passive_buy", 20))))
            if chasing:
                buy_size = min(buy_size, min(buy_cap, startup_chase_passive_buy))
            buy_size = min(buy_size, max(0, active_build_target - position - pending_buy))

            anchor_mode = bullish and not on_dip and (startup_cold_loading or chasing)
            if anchor_mode and buy_cap > buy_size:
                raw_anchor_bid       = round(entry_reference - startup_anchor_bid_spread)
                candidate_anchor_bid = min(max(raw_anchor_bid, 1), real_best_ask - 1)
                candidate_anchor_bid = min(candidate_anchor_bid, bid_price - startup_anchor_gap_ticks)
                if candidate_anchor_bid >= 1:
                    anchor_buy_price = candidate_anchor_bid
                    anchor_buy_size  = min(max(1, startup_anchor_size), max(0, buy_cap - buy_size))

        if gap_rebuy_mode:
            gap_rebuy_passive_buy = int(self.params.get("gap_rebuy_passive_buy", 6))
            buy_size = max(buy_size, min(buy_cap, gap_rebuy_passive_buy))
            buy_size = min(buy_size, max(0, inv_target - position - pending_buy))

        hold_sell_size   = int(self.params.get("hold_sell_size", 1))
        hold_sell_offset = int(self.params.get("hold_sell_offset", 0))
        if not build_phase and bullish and position >= self.position_limit() - hold_sell_size + 1:
            sell_size = min(sell_cap, hold_sell_size)
            ask_price = max(real_best_bid + 1, real_best_ask + hold_sell_offset)
        elif not build_phase and bullish:
            sell_size = 0

        if rebuy_blocked:
            buy_size = 0

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        return buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode

    def _gap_trap_quotes(
        self,
        book:           BookSnapshot,
        position:       int,
        memory:         Dict[str, Any],
        sell_cap:       int,
        ask_price:      int,
        trend_ticks:    float,
        gap_rebuy_mode: bool,
    ) -> Tuple[List[Order], List[int]]:
        """Arm and post gap-trap sell orders when the ask side is persistently fragile.

        Fragility is defined as: only one ask level, OR the gap to the second ask
        level exceeds gap_trap_min_gap, OR top-of-book volume is thin AND imbalance
        supports the bull case.

        Once the ask side has been fragile for gap_trap_arm_streak consecutive ticks
        and position >= gap_trap_floor_position, the trap is armed. A passive SELL is
        posted at anchor_ask + empty_side_shift. An optional premium order is added
        at peak_ask + empty_side_shift + premium_extra after gap_trap_premium_streak.

        The trap is cleared when position drops below the floor, gap_rebuy_mode is
        active, or gap_trap_clear_after consecutive non-fragile ticks occur.

        Params:
          gap_trap_arm_streak, gap_trap_clear_after, gap_trap_floor_position
          gap_trap_min_gap, gap_trap_top_ask_max, gap_trap_min_imbalance
          gap_trap_recent_ask_window, gap_trap_fragile_ask_window
          gap_trap_base_size, gap_trap_premium_size, gap_trap_premium_streak
          gap_trap_premium_extra, empty_side_shift

        Returns (orders, gap_sell_prices_list).
        """
        orders:              List[Order] = []
        gap_sell_prices:     List[int]   = []
        empty_side_shift     = int(self.params.get("empty_side_shift", 85))

        # Restore persisted trap state
        gap_trap_fragile_streak = int(memory.get("_gap_trap_fragile_streak", 0))
        gap_trap_clear_streak   = int(memory.get("_gap_trap_clear_streak", 0))
        gap_trap_anchor_ask     = memory.get("_gap_trap_anchor_ask")
        gap_trap_peak_ask       = memory.get("_gap_trap_peak_ask")

        gap_trap_floor_position   = int(self.params.get("gap_trap_floor_position", 78))
        gap_trap_arm_streak       = int(self.params.get("gap_trap_arm_streak", 2))
        gap_trap_clear_after      = int(self.params.get("gap_trap_clear_after", 2))
        gap_trap_min_trend        = float(self.params.get("gap_trap_min_trend", 0.0))
        gap_trap_min_gap          = int(self.params.get("gap_trap_min_gap", 3))
        gap_trap_top_ask_max      = int(self.params.get("gap_trap_top_ask_max", 10))
        gap_trap_min_imbalance    = float(self.params.get("gap_trap_min_imbalance", 0.05))
        gap_trap_recent_ask_window  = int(self.params.get("gap_trap_recent_ask_window", 8))
        gap_trap_fragile_ask_window = int(self.params.get("gap_trap_fragile_ask_window", 4))
        gap_trap_base_size          = int(self.params.get("gap_trap_base_size", 3))
        gap_trap_premium_size_limit = int(self.params.get("gap_trap_premium_size", 2))
        gap_trap_premium_streak     = int(self.params.get("gap_trap_premium_streak", 3))
        gap_trap_premium_extra      = int(self.params.get("gap_trap_premium_extra", 2))

        # Fragility detection
        ask_gap_fragile      = len(book.ask_levels) == 1
        if len(book.ask_levels) >= 2:
            ask_gap_fragile  = ask_gap_fragile or (book.ask_levels[1][0] - book.ask_levels[0][0] >= gap_trap_min_gap)
        ask_size_fragile     = book.best_ask_volume > 0 and book.best_ask_volume <= gap_trap_top_ask_max
        imbalance_supportive = book.imbalance is None or book.imbalance >= gap_trap_min_imbalance
        ask_side_fragile     = ask_gap_fragile or (ask_size_fragile and imbalance_supportive)

        # Rolling ask history for anchor and peak tracking
        trap_recent_asks = memory.setdefault("_gap_trap_recent_asks", [])
        trap_recent_asks.append(int(book.best_ask))
        if len(trap_recent_asks) > gap_trap_recent_ask_window:
            del trap_recent_asks[:-gap_trap_recent_ask_window]

        trap_fragile_asks = memory.setdefault("_gap_trap_fragile_asks", [])
        if ask_side_fragile:
            trap_fragile_asks.append(int(book.best_ask))
            if len(trap_fragile_asks) > gap_trap_fragile_ask_window:
                del trap_fragile_asks[:-gap_trap_fragile_ask_window]
        else:
            trap_fragile_asks[:] = []

        # Streak update
        trap_armable = trend_ticks >= gap_trap_min_trend and not gap_rebuy_mode and position >= gap_trap_floor_position
        if trap_armable and ask_side_fragile:
            gap_trap_fragile_streak += 1
            gap_trap_clear_streak    = 0
        elif gap_trap_anchor_ask is not None:
            gap_trap_clear_streak   += 1
            gap_trap_fragile_streak  = max(0, gap_trap_fragile_streak - 1)
        else:
            gap_trap_fragile_streak  = 0
            gap_trap_clear_streak    = 0

        # Arm trap
        if gap_trap_anchor_ask is None and trap_armable and gap_trap_fragile_streak >= gap_trap_arm_streak and trap_recent_asks:
            gap_trap_anchor_ask = min(trap_recent_asks)
            gap_trap_peak_ask   = max(trap_fragile_asks) if trap_fragile_asks else int(book.best_ask)

        # Update or disarm trap
        if gap_trap_anchor_ask is not None:
            if not trap_armable or gap_trap_clear_streak >= gap_trap_clear_after:
                gap_trap_anchor_ask = None
                gap_trap_peak_ask   = None
                gap_trap_fragile_streak = 0
                gap_trap_clear_streak   = 0
            else:
                if trap_recent_asks:
                    gap_trap_anchor_ask = min(int(gap_trap_anchor_ask), min(trap_recent_asks))
                if trap_fragile_asks:
                    latest_peak       = max(trap_fragile_asks)
                    gap_trap_peak_ask = max(int(gap_trap_peak_ask or latest_peak), latest_peak)

        # Build trap orders
        gap_trap_sell_price    = None
        gap_trap_sell_size     = 0
        gap_trap_premium_price = None
        gap_trap_premium_size  = 0
        gap_trap_active        = False
        gap_trap_armed         = False

        if gap_trap_anchor_ask is not None:
            gap_trap_armed          = True
            candidate_gap_trap_sell = int(gap_trap_anchor_ask) + empty_side_shift
            if candidate_gap_trap_sell > ask_price:
                gap_trap_sell_price = candidate_gap_trap_sell
                gap_trap_sell_size  = min(
                    sell_cap,
                    gap_trap_base_size,
                    max(0, position - gap_trap_floor_position + 1),
                )
                gap_trap_active = gap_trap_sell_size > 0

            if (
                gap_trap_peak_ask is not None
                and gap_trap_fragile_streak >= gap_trap_premium_streak
                and sell_cap > gap_trap_sell_size
            ):
                candidate_gap_trap_premium = max(
                    (gap_trap_sell_price or ask_price) + gap_trap_premium_extra,
                    int(gap_trap_peak_ask) + empty_side_shift + gap_trap_premium_extra,
                )
                if candidate_gap_trap_premium > (gap_trap_sell_price or ask_price):
                    gap_trap_premium_price = candidate_gap_trap_premium
                    gap_trap_premium_size  = min(
                        max(0, sell_cap - gap_trap_sell_size),
                        gap_trap_premium_size_limit,
                        max(0, position - gap_trap_floor_position),
                    )
                    gap_trap_active = gap_trap_active or gap_trap_premium_size > 0

        if gap_trap_sell_size > 0 and gap_trap_sell_price is not None:
            orders.append(Order(self.product, gap_trap_sell_price, -gap_trap_sell_size))
            gap_sell_prices.append(gap_trap_sell_price)
        if gap_trap_premium_size > 0 and gap_trap_premium_price is not None:
            orders.append(Order(self.product, gap_trap_premium_price, -gap_trap_premium_size))
            gap_sell_prices.append(gap_trap_premium_price)

        # Persist updated trap state
        memory["_gap_trap_fragile_streak"] = gap_trap_fragile_streak
        memory["_gap_trap_clear_streak"]   = gap_trap_clear_streak
        memory["_gap_trap_anchor_ask"]     = gap_trap_anchor_ask
        memory["_gap_trap_peak_ask"]       = gap_trap_peak_ask
        memory["gap_trap_active"]          = int(gap_trap_active)
        memory["gap_trap_armed"]           = int(gap_trap_armed)

        return orders, gap_sell_prices

    # ── order construction ───────────────────────────────────────────────

    def compute_orders(
        self,
        state:       TradingState,
        book:        BookSnapshot,
        order_depth: OrderDepth,
        position:    int,
        memory:      Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        # ── PREMIUM FILL DETECTION ─────────────────────────────────────
        self._process_premium_fills(state, memory)

        # ── RESET QUOTE TRACKERS ───────────────────────────────────────
        gap_sell_quotes: List[int] = []
        gap_buy_quotes:  List[int] = []
        memory["_active_gap_sell_quotes"] = []
        memory["_active_gap_buy_quotes"]  = []
        memory["_gap_sell_px"]            = []
        memory["_gap_buy_px"]             = []

        # ── ONE-SIDED / EMPTY BOOK ─────────────────────────────────────
        onesided = self._handle_onesided_book(book, position, memory, gap_sell_quotes, gap_buy_quotes)
        if onesided is not None:
            return onesided

        # Update last known prices and recent ask window (normal book path)
        if book.best_bid is not None:
            memory["_last_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_best_ask"] = book.best_ask
            recent_best_asks            = memory.setdefault("_recent_best_asks", [])
            gap_scout_recent_ask_window = int(self.params.get("gap_scout_recent_ask_window", 6))
            recent_best_asks.append(int(book.best_ask))
            if len(recent_best_asks) > gap_scout_recent_ask_window:
                del recent_best_asks[:-gap_scout_recent_ask_window]

        # ── REGRESSION + FAIR VALUE ────────────────────────────────────
        mid   = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        fv    = stats["fair_value"]

        # ── EWMA SIGNALS ───────────────────────────────────────────────
        spot = book.microprice if book.microprice is not None else mid
        _, _, _, stretch, trim_reference, entry_reference = (
            self._update_ewma_signals(spot, fv, memory)
        )

        # ── REGIME FLAGS ───────────────────────────────────────────────
        regime = self._compute_regime(state, stats, spot, stretch, book, position, memory)

        # ── QUOTE PRICES ───────────────────────────────────────────────
        bid_price, ask_price = self._compute_quote_prices(book, fv, stats, regime, entry_reference)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── BUY TAKERS ─────────────────────────────────────────────────
        buy_orders, buy_cap, pending_buy, swept_ask_prices = self._buy_takers(
            order_depth, fv, position, buy_cap, regime
        )

        # ── SELL TAKERS ────────────────────────────────────────────────
        sell_orders, sell_cap, pending_sell = self._sell_takers(
            order_depth, fv, position, sell_cap, regime
        )

        # ── PASSIVE SIZING ─────────────────────────────────────────────
        buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode = (
            self._compute_passive_sizes(
                position, buy_cap, sell_cap, pending_buy, pending_sell,
                stats, regime, entry_reference, book, bid_price, ask_price, swept_ask_prices,
            )
        )

        # ── GAP TRAP ───────────────────────────────────────────────────
        gap_trap_orders, gap_trap_sell_prices = self._gap_trap_quotes(
            book, position, memory, sell_cap, ask_price,
            stats["trend_ticks"], regime["gap_rebuy_mode"],
        )
        gap_sell_quotes.extend(gap_trap_sell_prices)

        # ── ASSEMBLE ORDERS ────────────────────────────────────────────
        orders: List[Order] = buy_orders + sell_orders
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if anchor_buy_size > 0 and anchor_buy_price is not None:
            orders.append(Order(self.product, anchor_buy_price, anchor_buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))
        orders.extend(gap_trap_orders)

        # ── MEMORY WRITES ──────────────────────────────────────────────
        memory["last_bid_price"]       = bid_price
        memory["last_ask_price"]       = ask_price
        memory["entry_reference"]      = entry_reference
        memory["inv_target"]           = regime["inv_target"]
        memory["active_build_target"]  = regime["active_build_target"]
        memory["bullish"]              = int(regime["bullish"])
        memory["build_phase"]          = int(regime["build_phase"])
        memory["on_dip"]               = int(regime["on_dip"])
        memory["chasing"]              = int(regime["chasing"])
        memory["anchor_mode"]          = int(anchor_mode)
        memory["startup_fast_loading"] = int(regime["startup_fast_loading"])
        memory["startup_cold_loading"] = int(regime["startup_cold_loading"])
        memory["pullback_ready"]       = int(regime["current_pullback_ready"])
        memory["pullback_seen"]        = int(regime["pullback_seen"])
        memory["build_release_ready"]  = int(regime["build_release_ready"])
        memory["gap_rebuy_mode"]       = int(regime["gap_rebuy_mode"])
        memory["gap_rebuy_discount"]   = regime["gap_rebuy_discount"]
        memory["trim_quote_mode"]      = int(regime["trim_quote_mode"])
        memory["trim_take_mode"]       = int(regime["trim_take_mode"])
        memory["rebuy_blocked"]        = int(regime["rebuy_blocked"])
        memory["stretch"]              = stretch
        memory["_active_gap_sell_quotes"] = sorted(set(gap_sell_quotes))
        memory["_active_gap_buy_quotes"]  = sorted(set(gap_buy_quotes))
        memory["_gap_sell_px"]            = memory["_active_gap_sell_quotes"]
        memory["_gap_buy_px"]             = memory["_active_gap_buy_quotes"]

        # ── LOGGING ────────────────────────────────────────────────────
        trend_ticks = stats["trend_ticks"]
        gap_trap_armed          = bool(memory.get("gap_trap_armed", 0))
        gap_trap_active         = bool(memory.get("gap_trap_active", 0))
        gap_trap_fragile_streak = int(memory.get("_gap_trap_fragile_streak", 0))
        gap_trap_anchor_ask     = memory.get("_gap_trap_anchor_ask")
        gap_trap_peak_ask       = memory.get("_gap_trap_peak_ask")
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position":              position,
                "trend_ticks":           round(trend_ticks, 2),
                "fair_value":            round(fv, 2),
                "stretch":               round(stretch, 2),
                "trim_ref":              round(trim_reference, 2),
                "entry_ref":             round(entry_reference, 2),
                "inv_target":            regime["inv_target"],
                "active_build_target":   regime["active_build_target"],
                "bullish":               int(regime["bullish"]),
                "build_phase":           int(regime["build_phase"]),
                "on_dip":                int(regime["on_dip"]),
                "chasing":               int(regime["chasing"]),
                "pullback_ready":        int(regime["current_pullback_ready"]),
                "pullback_seen":         int(regime["pullback_seen"]),
                "build_release_ready":   int(regime["build_release_ready"]),
                "gap_rebuy_mode":        int(regime["gap_rebuy_mode"]),
                "gap_rebuy_discount":    round(regime["gap_rebuy_discount"], 2),
                "anchor_mode":           int(anchor_mode),
                "startup_fast_loading":  int(regime["startup_fast_loading"]),
                "startup_cold_loading":  int(regime["startup_cold_loading"]),
                "buy_size":              buy_size,
                "sell_size":             sell_size,
                "anchor_buy_price":      anchor_buy_price,
                "anchor_buy_size":       anchor_buy_size,
                "gap_trap_active":       int(gap_trap_active),
                "gap_trap_armed":        int(gap_trap_armed),
                "gap_trap_fragile_streak": gap_trap_fragile_streak,
                "gap_trap_anchor_ask":   gap_trap_anchor_ask,
                "gap_trap_peak_ask":     gap_trap_peak_ask,
                "trim_quote_mode":       int(regime["trim_quote_mode"]),
                "trim_take_mode":        int(regime["trim_take_mode"]),
                "trim_take_qty":         regime["trim_take_qty"],
                "rebuy_blocked":         int(regime["rebuy_blocked"]),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        stats = memory.get("regression_stats")
        if stats:
            out["reg_fair_value"] = float(stats["fair_value"])
        if memory.get("ewma_fv") is not None:
            out["ewma_fv"] = memory["ewma_fv"]
        if memory.get("short_ema") is not None:
            out["short_ema"] = memory["short_ema"]
        if memory.get("entry_reference") is not None:
            out["entry_reference"] = memory["entry_reference"]
        return out

# ── Config ────────────────────────────────────────────────────────────────────


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v2.py ──────────

class TheoBestCleanGeneralizedV2Strategy(TheoBestCleanGeneralizedStrategy):
    """V2: same logic as v1, with tuned startup-build parameters from search."""

    pass


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v3.py ──────────

class TheoBestCleanGeneralizedV3Strategy(TheoBestCleanGeneralizedV2Strategy):
    """V3: suppress regular sells at max inventory when the ask is not rich enough."""

    def _max_inventory_sell_guard_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        guard_position = int(
            self.params.get("max_inventory_sell_guard_position", self.position_limit())
        )
        guard_threshold = float(self.params.get("max_inventory_sell_guard_threshold", 8.0))

        active = (
            best_ask is not None
            and position >= guard_position
            and float(best_ask) < fair_value + guard_threshold
        )

        self._memory["max_inventory_sell_guard_active"] = int(active)
        self._memory["max_inventory_sell_guard_ref"] = fair_value + guard_threshold
        return active

    def _compute_passive_sizes(
        self,
        position: int,
        buy_cap: int,
        sell_cap: int,
        pending_buy: int,
        pending_sell: int,
        stats,
        regime,
        entry_reference: float,
        book,
        bid_price: int,
        ask_price: int,
        buy_taker_prices: Set[int],
    ) -> Tuple[int, int, Optional[int], int, int, bool]:
        buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode = super()._compute_passive_sizes(
            position,
            buy_cap,
            sell_cap,
            pending_buy,
            pending_sell,
            stats,
            regime,
            entry_reference,
            book,
            bid_price,
            ask_price,
            buy_taker_prices,
        )

        if self._max_inventory_sell_guard_active(
            position=position,
            best_ask=book.best_ask,
            fair_value=float(stats["fair_value"]),
        ):
            sell_size = 0

        return buy_size, sell_size, anchor_buy_price, anchor_buy_size, ask_price, anchor_mode


# ── prosperity/strategies/round_2/theo/theo_best_clean_generalized_v4.py ──────────

class TheoBestCleanGeneralizedV4Strategy(TheoBestCleanGeneralizedV3Strategy):
    """V4: keep 3 slots of reserve unless a deep dump unlocks the reserve."""

    def _reserve_inventory_size(self) -> int:
        return max(0, int(self.params.get("dump_reserve_inventory", 3)))

    def _reserve_normal_inventory_cap(self) -> int:
        return max(0, self.position_limit() - self._reserve_inventory_size())

    def _dump_reserve_release_active(
        self,
        *,
        position: int,
        best_ask: Optional[int],
        fair_value: float,
    ) -> bool:
        reserve_size = self._reserve_inventory_size()
        reserve_threshold = float(self.params.get("dump_reserve_release_threshold", 3.0))
        reserve_min_position = int(
            self.params.get(
                "dump_reserve_release_min_position",
                self._reserve_normal_inventory_cap(),
            )
        )

        active = (
            reserve_size > 0
            and best_ask is not None
            and position >= reserve_min_position
            and float(best_ask) <= fair_value - reserve_threshold
        )

        self._memory["dump_reserve_release_active"] = int(active)
        self._memory["dump_reserve_release_ref"] = fair_value - reserve_threshold
        self._memory["dump_reserve_normal_cap"] = self._reserve_normal_inventory_cap()
        return active

    def _reserve_buy_room(
        self,
        *,
        position: int,
        pending_buy: int,
        release_active: bool,
    ) -> int:
        target_cap = self.position_limit() if release_active else self._reserve_normal_inventory_cap()
        return max(0, target_cap - position - pending_buy)

    def _buy_takers(
        self,
        order_depth,
        fv: float,
        position: int,
        buy_cap: int,
        regime,
    ):
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        release_active = self._dump_reserve_release_active(
            position=position,
            best_ask=best_ask,
            fair_value=float(fv),
        )
        capped_buy_cap = min(
            buy_cap,
            self._reserve_buy_room(
                position=position,
                pending_buy=0,
                release_active=release_active,
            ),
        )
        if capped_buy_cap <= 0:
            return [], 0, 0, set()

        capped_regime = dict(regime)
        capped_regime["buy_take_cap"] = min(int(regime["buy_take_cap"]), capped_buy_cap)
        return super()._buy_takers(order_depth, fv, position, capped_buy_cap, capped_regime)

    def _compute_passive_sizes(
        self,
        position: int,
        buy_cap: int,
        sell_cap: int,
        pending_buy: int,
        pending_sell: int,
        stats,
        regime,
        entry_reference: float,
        book,
        bid_price: int,
        ask_price: int,
        buy_taker_prices: Set[int],
    ) -> Tuple[int, int, Optional[int], int, int, bool]:
        release_active = self._dump_reserve_release_active(
            position=position,
            best_ask=book.best_ask,
            fair_value=float(stats["fair_value"]),
        )
        capped_buy_cap = min(
            buy_cap,
            self._reserve_buy_room(
                position=position,
                pending_buy=pending_buy,
                release_active=release_active,
            ),
        )

        return super()._compute_passive_sizes(
            position,
            capped_buy_cap,
            sell_cap,
            pending_buy,
            pending_sell,
            stats,
            regime,
            entry_reference,
            book,
            bid_price,
            ask_price,
            buy_taker_prices,
        )

# ── Config ────────────────────────────────────────────────────────────────────

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'ASH_COATED_OSMIUM': {'OB_cleared_shift': 89,
                       'anchor_alpha': 0.02,
                       'anchor_drift_bound': 2.0,
                       'anchor_price': 10000.0,
                       'ar_gain': 0.3,
                       'ar_shift_source': 'mid_smooth',
                       'gap_trigger_confirm_ticks': 1,
                       'gap_trigger_max_vol_pct': 0.1,
                       'gap_trigger_min': 10,
                       'inventory_aversion_gamma': 0.0015,
                       'last_ts_value': 999900,
                       'log_flush_ts': 1000,
                       'maker_size': 20,
                       'maker_size_base_pct': 0.5,
                       'mid_smooth_half_life': 10,
                       'mid_smooth_window': 50,
                       'pct_kept_for_takers': 0.05,
                       'position_limit': 80,
                       'quote_trace_enabled': True,
                       'strategy': 'mm_first_v4_combo',
                       'take_edge': 1,
                       'take_edge_hi': 0.8,
                       'take_edge_lo': 0.3,
                       'take_edge_vol_hi': 5.0,
                       'take_edge_vol_lo': 2.0,
                       'taker_buy_threshold': 9990,
                       'taker_sell_threshold': 10025,
                       'tighten_ticks': 1,
                       'ts_increment': 100,
                       'unwind_take_edge': 3.0,
                       'zscore_gap_gate': 1.5,
                       'zscore_max_scale': 5.0,
                       'zscore_size_scale': 0.5,
                       'zscore_threshold': 1,
                       'zscore_window': 50},
 'INTARIAN_PEPPER_ROOT': {'aggravate_cut': 0.04,
                          'ask_gap_quote_size': 8,
                          'ask_gap_sell_enable_position': 75,
                          'ask_spread_bull': 9.0,
                          'bid_spread_bull': 1.0,
                          'block_size': 200,
                          'bootstrap_confidence': 0.55,
                          'bull_threshold': 1.0,
                          'chase_threshold': 1.25,
                          'cheap_buy_boost_per_z': 0.18,
                          'cheap_residual_z': 0.9,
                          'dip_threshold': 1.0,
                          'dump_reserve_inventory': 1,
                          'dump_reserve_release_min_position': 75,
                          'dump_reserve_release_threshold': 3.0,
                          'empty_side_shift': 85,
                          'fastfill_buy_edge_boost': 0.0,
                          'fastfill_deep_take_guard_end_ts': 1000,
                          'fastfill_deep_take_max_gap_ticks': 1,
                          'fastfill_end_ts': 12000,
                          'fastfill_min_passive_buy': 10,
                          'fastfill_target': 80,
                          'fv_alpha': 0.05,
                          'gap_fill_min_premium': 35,
                          'gap_rebuy_buy_edge': -10.0,
                          'gap_rebuy_min_discount': 20.0,
                          'gap_rebuy_passive_buy': 6,
                          'gap_rebuy_take_cap': 8,
                          'gap_rebuy_window': 2500,
                          'gap_trap_arm_streak': 2,
                          'gap_trap_base_size': 4,
                          'gap_trap_clear_after': 4,
                          'gap_trap_floor_position': 73,
                          'gap_trap_fragile_ask_window': 6,
                          'gap_trap_min_gap': 3,
                          'gap_trap_min_imbalance': -0.05,
                          'gap_trap_min_trend': 0.0,
                          'gap_trap_premium_extra': 2,
                          'gap_trap_premium_size': 3,
                          'gap_trap_premium_streak': 2,
                          'gap_trap_recent_ask_window': 12,
                          'gap_trap_top_ask_max': 12,
                          'hold_sell_offset': 0,
                          'hold_sell_size': 0,
                          'last_ts_value': 999900,
                          'log_flush_ts': 1000,
                          'maker_size': 80,
                          'max_bid_extra_ticks': 2,
                          'max_inventory_sell_guard_position': 80,
                          'max_inventory_sell_guard_threshold': 0.0,
                          'min_completed_blocks': 5,
                          'neut_spread_ask': 5.0,
                          'neut_spread_bid': 2.0,
                          'one_sided_target_gap': 24,
                          'position_limit': 80,
                          'rebuy_block_ticks': 25,
                          'reg_horizon': 25,
                          'reg_r2_cap': 0.98,
                          'reg_r2_floor': 0.85,
                          'reg_residual_reversion': 0.25,
                          'reg_rmse_floor': 1.0,
                          'resid_inv_per_z': 14.0,
                          'rich_residual_z': 1.0,
                          'rich_sell_boost_per_z': 0.14,
                          'seed_slope': 0.1015,
                          'short_alpha': 0.22,
                          'slope_window': 20,
                          'startup_anchor_bid_spread': 1.0,
                          'startup_anchor_gap_ticks': 1,
                          'startup_anchor_size': 4,
                          'startup_chase_passive_buy': 1,
                          'startup_chase_take_cap': 1,
                          'startup_chase_take_edge': 4.0,
                          'startup_cold_join_ticks': 0,
                          'startup_cold_passive_buy': 3,
                          'startup_cold_take_cap': 4,
                          'startup_cold_take_edge': 3.0,
                          'startup_delayed_finish_ts': 3000,
                          'startup_dip_take_edge_boost': 1.0,
                          'startup_end_ts': 30000,
                          'startup_fast_passive_buy': 8,
                          'startup_fast_take_cap': 12,
                          'startup_fast_target': 64,
                          'startup_post_pullback_target': 72,
                          'startup_pre_pullback_target': 48,
                          'startup_pullback_ticks': 2.0,
                          'startup_release_stretch': 1.0,
                          'startup_release_take_cap': 8,
                          'startup_target': 80,
                          'strategy': 'theo_best_clean_generalized_v4',
                          'strong_trend_ticks': 0.9,
                          'take_buy_edge_bull': -8.0,
                          'take_buy_edge_neut': 2.0,
                          'take_sell_edge_neut': 2.0,
                          'target_gap_scale': 26.0,
                          'tighten_ticks': 1,
                          'trend_buy_boost_per_tick': 0.24,
                          'trend_inv_per_tick': 16.0,
                          'trend_inventory_cap': 80,
                          'trend_sell_boost_per_tick': 0.2,
                          'trim_ask_local_edge': 0.0,
                          'trim_cooldown_ticks': 20,
                          'trim_extension_threshold': 0.75,
                          'trim_floor_position': 78,
                          'trim_reference_slope_weight': 0.15,
                          'trim_sell_size': 1,
                          'trim_signal_edge': 1.0,
                          'trim_start_position': 79,
                          'trim_take_edge': 2.0,
                          'trim_take_position': 80,
                          'trim_take_sell_size': 1,
                          'trim_take_stretch': 999.0,
                          'ts_increment': 100,
                          'unwind_take_edge': 10.0,
                          'very_strong_trend_ticks': 1.6}}

STRATEGY_CLASSES = {"mm_first_v4_combo": MMFirstV4ComboStrategy, "theo_best_clean_generalized_v4": TheoBestCleanGeneralizedV4Strategy}

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
        return 2951

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
