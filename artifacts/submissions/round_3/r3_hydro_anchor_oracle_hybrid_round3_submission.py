from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Optional, Set, Tuple
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

        # Track if we full-cap'd the ask side (so _passive_quotes skips its own ask)
        fullcap_ask_posted = False
        fullcap_bid_posted = False

        if final_remaining_asks:
            ask_price = final_remaining_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + int(shift)   # LIVE alpha: far above
            # FULL-CAPACITY: post full-cap sell at far-quote when ask empty
            if self.params.get("full_capacity_on_empty", False) and sell_cap > 0:
                orders.append(Order(self.product, ask_price, -sell_cap))
                memory["_gap_sell_px"].append(ask_price)
                fullcap_ask_posted = True
                # Note: DO NOT zero sell_cap here — let opposite-side passive use
                # its share. The _passive_quotes should check fullcap flag.

        if final_remaining_bids:
            bid_price = final_remaining_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - int(shift)   # LIVE alpha: far below
            # FULL-CAPACITY: post full-cap buy at far-quote when bid empty
            if self.params.get("full_capacity_on_empty", False) and buy_cap > 0:
                orders.append(Order(self.product, bid_price, buy_cap))
                memory["_gap_buy_px"].append(bid_price)
                fullcap_bid_posted = True

        # Clamp caps only on the sides that were fullcap'd (avoid double-posting
        # when _passive_quotes runs next).
        if fullcap_ask_posted:
            sell_cap = 0
        if fullcap_bid_posted:
            buy_cap = 0

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

        sdq = int(self.params.get("osm_standing_deep_qty", 0))
        if sdq > 0:
            sh = int(self.params.get("OB_cleared_shift", 10))
            lbb = memory.get("_last_best_bid")
            lba = memory.get("_last_best_ask")
            ao = taker_orders + gap_orders + passive_orders
            ebp = {o.price for o in ao if o.quantity > 0}
            eap = {o.price for o in ao if o.quantity < 0}
            if lbb is not None and buy_cap > 0:
                db = int(lbb) - sh
                if db > 0 and db not in ebp:
                    q = min(sdq, buy_cap)
                    if q > 0:
                        passive_orders.append(Order(self.product, db, q))
            if lba is not None and sell_cap > 0:
                da = int(lba) + sh
                if da not in eap:
                    q = min(sdq, sell_cap)
                    if q > 0:
                        passive_orders.append(Order(self.product, da, -q))

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


# ── prosperity/strategies/round_3/oracle_day2_l1_replay.py ────────────────────────

ORACLE_L1_EXPECTED_PNL = {
    'HYDROGEL_PACK': 39336.0,
    'VELVETFRUIT_EXTRACT': 22354.0,
    'VEV_4000': 4517.0,
    'VEV_4500': 6269.0,
    'VEV_5000': 16553.0,
    'VEV_5100': 19139.0,
    'VEV_5200': 17302.5,
    'VEV_5300': 9579.0,
    'VEV_5400': 3904.0,
    'VEV_5500': 921.5,
    'VEV_6000': 0.0,
    'VEV_6500': 0.0,
}

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
    },
    'VELVETFRUIT_EXTRACT': {
        600: ('BUY', 18, 5265),
        700: ('BUY', 24, 5265),
        800: ('BUY', 20, 5265),
        900: ('BUY', 8, 5262),
        1000: ('BUY', 21, 5265),
        1200: ('BUY', 58, 5265),
        1300: ('BUY', 51, 5265),
        3400: ('SELL', 24, 5272),
        4200: ('SELL', 19, 5272),
        4300: ('SELL', 25, 5272),
        5500: ('SELL', 63, 5273),
        5600: ('SELL', 68, 5273),
        5700: ('SELL', 69, 5273),
        5800: ('SELL', 22, 5272),
        5900: ('SELL', 9, 5275),
        6000: ('SELL', 19, 5273),
        6100: ('SELL', 12, 5275),
        6200: ('SELL', 15, 5273),
        6300: ('SELL', 14, 5275),
        7000: ('BUY', 11, 5271),
        7500: ('SELL', 32, 5271),
        8000: ('SELL', 11, 5271),
        8500: ('SELL', 9, 5271),
        9600: ('BUY', 20, 5265),
        9700: ('BUY', 23, 5265),
        9800: ('BUY', 16, 5265),
        9900: ('BUY', 60, 5265),
        10000: ('BUY', 18, 5265),
        10200: ('BUY', 4, 5265),
        10300: ('BUY', 15, 5263),
        10500: ('BUY', 59, 5264),
        10600: ('BUY', 59, 5264),
        10700: ('BUY', 22, 5265),
        10800: ('BUY', 70, 5264),
        10900: ('BUY', 18, 5264),
        11000: ('BUY', 16, 5265),
        12000: ('SELL', 7, 5266),
        12700: ('BUY', 7, 5266),
        16500: ('SELL', 8, 5272),
        17200: ('SELL', 64, 5272),
        17300: ('SELL', 22, 5273),
        17400: ('SELL', 17, 5274),
        17500: ('SELL', 19, 5274),
        17600: ('SELL', 22, 5273),
        18000: ('SELL', 21, 5273),
        18100: ('SELL', 25, 5272),
        18200: ('SELL', 49, 5272),
        18300: ('SELL', 64, 5272),
        18400: ('SELL', 18, 5271),
        18500: ('SELL', 61, 5271),
        18900: ('SELL', 10, 5271),
        19700: ('BUY', 13, 5266),
        19800: ('BUY', 16, 5269),
        20600: ('BUY', 16, 5270),
        21800: ('SELL', 19, 5270),
        21900: ('SELL', 15, 5270),
        22300: ('SELL', 11, 5270),
        23600: ('BUY', 18, 5265),
        24600: ('BUY', 5, 5265),
        26900: ('SELL', 23, 5265),
        30600: ('BUY', 66, 5264),
        30700: ('BUY', 19, 5263),
        30800: ('BUY', 58, 5262),
        30900: ('BUY', 22, 5263),
        31000: ('BUY', 23, 5261),
        31100: ('BUY', 17, 5261),
        31200: ('BUY', 7, 5258),
        31300: ('BUY', 23, 5263),
        31400: ('BUY', 60, 5264),
        31500: ('BUY', 60, 5264),
        31600: ('BUY', 21, 5264),
        31700: ('BUY', 3, 5265),
        31800: ('BUY', 21, 5265),
        33100: ('SELL', 25, 5267),
        33900: ('SELL', 15, 5268),
        34000: ('SELL', 20, 5268),
        34100: ('SELL', 59, 5269),
        34200: ('SELL', 58, 5270),
        34300: ('SELL', 23, 5270),
        34400: ('SELL', 62, 5269),
        34500: ('SELL', 19, 5269),
        34600: ('SELL', 20, 5268),
        34700: ('SELL', 16, 5268),
        35600: ('SELL', 9, 5268),
        37200: ('SELL', 44, 5266),
        37700: ('SELL', 8, 5268),
        38900: ('SELL', 15, 5267),
        39000: ('SELL', 7, 5266),
        41500: ('BUY', 24, 5254),
        41600: ('BUY', 53, 5254),
        41700: ('BUY', 50, 5254),
        41900: ('BUY', 70, 5253),
        42000: ('BUY', 23, 5252),
        42100: ('BUY', 58, 5254),
        43700: ('BUY', 22, 5254),
        43800: ('BUY', 56, 5253),
        43900: ('BUY', 19, 5253),
        44000: ('BUY', 25, 5254),
        46500: ('SELL', 4, 5257),
        47200: ('SELL', 11, 5259),
        49000: ('BUY', 15, 5257),
        50800: ('SELL', 49, 5261),
        50900: ('SELL', 19, 5263),
        51000: ('SELL', 51, 5261),
        51100: ('SELL', 54, 5261),
        51200: ('SELL', 20, 5260),
        51300: ('SELL', 15, 5262),
        51400: ('SELL', 22, 5262),
        51500: ('SELL', 58, 5260),
        51600: ('SELL', 19, 5262),
        51700: ('SELL', 19, 5260),
        51800: ('SELL', 18, 5260),
        52100: ('SELL', 18, 5260),
        52300: ('SELL', 25, 5260),
        52900: ('SELL', 13, 5260),
        56600: ('BUY', 8, 5251),
        56800: ('SELL', 8, 5252),
        58900: ('BUY', 4, 5245),
        59200: ('BUY', 68, 5244),
        59500: ('BUY', 20, 5244),
        59600: ('BUY', 58, 5244),
        59700: ('BUY', 62, 5244),
        59800: ('BUY', 59, 5245),
        59900: ('BUY', 23, 5244),
        60100: ('BUY', 19, 5245),
        60200: ('BUY', 19, 5245),
        60300: ('BUY', 68, 5245),
        63200: ('SELL', 8, 5252),
        63300: ('BUY', 7, 5251),
        65900: ('BUY', 1, 5252),
        67600: ('SELL', 23, 5257),
        67700: ('SELL', 61, 5257),
        67800: ('SELL', 21, 5257),
        67900: ('SELL', 20, 5257),
        68000: ('SELL', 50, 5257),
        68100: ('SELL', 22, 5257),
        68200: ('SELL', 60, 5256),
        68300: ('SELL', 16, 5256),
        69200: ('BUY', 11, 5253),
        71300: ('BUY', 6, 5254),
        71400: ('BUY', 52, 5255),
        71500: ('BUY', 60, 5255),
        71600: ('BUY', 68, 5255),
        71700: ('BUY', 17, 5255),
        72500: ('SELL', 16, 5256),
        72600: ('SELL', 61, 5256),
        72700: ('SELL', 56, 5256),
        72800: ('SELL', 59, 5256),
        73100: ('SELL', 45, 5256),
        77100: ('BUY', 16, 5255),
        77200: ('BUY', 54, 5255),
        77300: ('BUY', 24, 5254),
        77400: ('BUY', 17, 5254),
        77500: ('BUY', 53, 5256),
        77600: ('BUY', 24, 5256),
        77700: ('BUY', 49, 5256),
        78000: ('BUY', 15, 5256),
        78600: ('BUY', 24, 5256),
        78700: ('BUY', 20, 5256),
        82200: ('SELL', 66, 5269),
        82300: ('SELL', 69, 5269),
        82400: ('SELL', 15, 5270),
        82600: ('SELL', 54, 5269),
        83300: ('BUY', 23, 5268),
        84200: ('SELL', 10, 5269),
        84300: ('SELL', 6, 5269),
        84500: ('SELL', 63, 5270),
        84600: ('SELL', 22, 5271),
        84700: ('SELL', 19, 5273),
        84800: ('SELL', 58, 5271),
        85700: ('SELL', 25, 5269),
        86300: ('BUY', 14, 5268),
        86500: ('SELL', 10, 5270),
        87900: ('SELL', 6, 5271),
        89000: ('SELL', 14, 5269),
        90800: ('BUY', 20, 5268),
        91000: ('BUY', 49, 5268),
        91100: ('BUY', 45, 5268),
        91200: ('BUY', 53, 5268),
        93000: ('SELL', 35, 5268),
        93100: ('SELL', 61, 5268),
        93900: ('SELL', 71, 5268),
        94900: ('BUY', 10, 5264),
        95300: ('BUY', 63, 5264),
        95600: ('BUY', 9, 5262),
        95800: ('BUY', 21, 5264),
        95900: ('BUY', 15, 5264),
        96000: ('BUY', 24, 5264),
        97300: ('BUY', 21, 5264),
        97400: ('BUY', 22, 5263),
        97500: ('BUY', 7, 5264),
        99300: ('BUY', 8, 5262),
    },
    'VEV_4000': {
        3400: ('SELL', 8, 1264),
        4200: ('SELL', 11, 1264),
        4300: ('SELL', 9, 1264),
        5500: ('SELL', 13, 1265),
        5600: ('SELL', 11, 1265),
        5700: ('SELL', 8, 1265),
        5800: ('SELL', 13, 1264),
        5900: ('SELL', 9, 1264),
        6000: ('SELL', 15, 1265),
        6100: ('SELL', 12, 1264),
        6200: ('SELL', 14, 1265),
        6300: ('SELL', 13, 1264),
        7800: ('SELL', 2, 1270),
        17200: ('SELL', 12, 1264),
        17300: ('SELL', 13, 1265),
        17400: ('SELL', 10, 1266),
        17500: ('SELL', 10, 1266),
        17600: ('SELL', 11, 1265),
        17700: ('SELL', 3, 1263),
        17800: ('SELL', 10, 1263),
        17900: ('SELL', 13, 1263),
        18000: ('SELL', 8, 1265),
        18100: ('SELL', 15, 1264),
        18200: ('SELL', 9, 1264),
        18300: ('SELL', 7, 1264),
        18400: ('SELL', 15, 1263),
        18500: ('SELL', 15, 1263),
        19100: ('SELL', 2, 1269),
        24600: ('SELL', 4, 1265),
        35200: ('SELL', 2, 1266),
        39300: ('SELL', 3, 1264),
        41900: ('BUY', 2, 1250),
        42900: ('BUY', 4, 1253),
        45100: ('BUY', 5, 1258),
        52900: ('BUY', 5, 1259),
        57300: ('BUY', 8, 1259),
        57400: ('BUY', 7, 1259),
        57600: ('BUY', 10, 1259),
        57700: ('BUY', 9, 1259),
        57800: ('BUY', 9, 1259),
        57900: ('BUY', 15, 1259),
        58000: ('BUY', 14, 1258),
        58100: ('BUY', 7, 1259),
        58300: ('BUY', 12, 1259),
        58400: ('BUY', 14, 1258),
        58500: ('BUY', 15, 1258),
        58600: ('BUY', 13, 1258),
        58700: ('BUY', 7, 1256),
        58800: ('BUY', 10, 1254),
        58900: ('BUY', 12, 1253),
        59000: ('BUY', 8, 1253),
        59100: ('BUY', 7, 1253),
        59200: ('BUY', 12, 1252),
        59300: ('BUY', 11, 1253),
        59400: ('BUY', 13, 1253),
        59500: ('BUY', 14, 1252),
        59600: ('BUY', 8, 1252),
        59700: ('BUY', 8, 1252),
        59800: ('BUY', 15, 1253),
        59900: ('BUY', 8, 1252),
        60000: ('BUY', 7, 1254),
        60100: ('BUY', 8, 1253),
        60200: ('BUY', 14, 1253),
        60300: ('BUY', 10, 1253),
        60400: ('BUY', 7, 1254),
        60500: ('BUY', 9, 1255),
        60600: ('BUY', 10, 1256),
        60700: ('BUY', 7, 1256),
        60800: ('BUY', 11, 1257),
        60900: ('BUY', 13, 1257),
        61000: ('BUY', 14, 1257),
        61100: ('BUY', 10, 1258),
        61200: ('BUY', 8, 1259),
        61300: ('BUY', 10, 1259),
        61400: ('BUY', 13, 1259),
        61500: ('BUY', 14, 1258),
        61600: ('BUY', 8, 1258),
        61700: ('BUY', 15, 1259),
        61800: ('BUY', 8, 1259),
        62000: ('BUY', 13, 1259),
        62100: ('BUY', 10, 1259),
        62200: ('BUY', 12, 1259),
        62300: ('BUY', 15, 1258),
        62400: ('BUY', 9, 1258),
        62500: ('BUY', 12, 1259),
        62600: ('BUY', 15, 1259),
        63000: ('BUY', 2, 1260),
        63100: ('BUY', 14, 1260),
        65000: ('BUY', 11, 1260),
        75200: ('BUY', 4, 1255),
        79300: ('BUY', 5, 1257),
        84700: ('SELL', 10, 1265),
    },
    'VEV_4500': {
        3400: ('SELL', 10, 766),
        3600: ('SELL', 12, 766),
        3800: ('SELL', 8, 766),
        3900: ('SELL', 6, 766),
        4200: ('SELL', 7, 766),
        4300: ('SELL', 9, 766),
        5500: ('SELL', 7, 768),
        5600: ('SELL', 9, 768),
        5700: ('SELL', 10, 768),
        5800: ('SELL', 11, 766),
        5900: ('SELL', 7, 767),
        6000: ('SELL', 11, 767),
        6100: ('SELL', 8, 767),
        6200: ('SELL', 12, 767),
        6300: ('SELL', 8, 766),
        7500: ('SELL', 8, 766),
        7800: ('SELL', 2, 770),
        13100: ('BUY', 3, 765),
        17100: ('SELL', 7, 765),
        17200: ('SELL', 8, 766),
        17300: ('SELL', 9, 767),
        17400: ('SELL', 11, 768),
        17500: ('SELL', 12, 768),
        17600: ('SELL', 10, 767),
        17700: ('SELL', 8, 765),
        17800: ('SELL', 11, 765),
        17900: ('SELL', 12, 765),
        18000: ('SELL', 8, 767),
        18100: ('SELL', 11, 766),
        18200: ('SELL', 12, 767),
        18300: ('SELL', 9, 767),
        18400: ('SELL', 7, 765),
        18500: ('SELL', 8, 765),
        19100: ('SELL', 2, 769),
        23500: ('BUY', 2, 763),
        24600: ('SELL', 4, 765),
        34200: ('SELL', 9, 765),
        35200: ('SELL', 2, 766),
        41900: ('BUY', 2, 750),
        42000: ('BUY', 9, 757),
        42900: ('BUY', 4, 753),
        43800: ('BUY', 7, 758),
        45100: ('BUY', 5, 758),
        57100: ('BUY', 9, 758),
        57200: ('BUY', 12, 758),
        57300: ('BUY', 9, 757),
        57400: ('BUY', 12, 757),
        57500: ('BUY', 8, 757),
        57600: ('BUY', 10, 756),
        57700: ('BUY', 9, 757),
        57800: ('BUY', 11, 757),
        57900: ('BUY', 8, 757),
        58000: ('BUY', 8, 756),
        58100: ('BUY', 6, 757),
        58200: ('BUY', 11, 758),
        58300: ('BUY', 12, 757),
        58400: ('BUY', 8, 755),
        58500: ('BUY', 6, 755),
        58600: ('BUY', 6, 755),
        58700: ('BUY', 6, 753),
        58800: ('BUY', 7, 751),
        58900: ('BUY', 10, 750),
        59000: ('BUY', 8, 751),
        59100: ('BUY', 11, 750),
        59200: ('BUY', 6, 749),
        59300: ('BUY', 8, 751),
        59400: ('BUY', 8, 750),
        59500: ('BUY', 7, 749),
        59600: ('BUY', 9, 749),
        59700: ('BUY', 6, 749),
        59800: ('BUY', 7, 750),
        59900: ('BUY', 12, 750),
        60000: ('BUY', 12, 751),
        60100: ('BUY', 12, 751),
        60200: ('BUY', 8, 751),
        60300: ('BUY', 6, 750),
        60400: ('BUY', 10, 752),
        60500: ('BUY', 6, 752),
        60600: ('BUY', 7, 753),
        60700: ('BUY', 10, 753),
        60800: ('BUY', 7, 754),
        60900: ('BUY', 10, 754),
        61000: ('BUY', 7, 754),
        61100: ('BUY', 12, 755),
        61200: ('BUY', 6, 757),
        61300: ('BUY', 7, 756),
        61400: ('BUY', 10, 756),
        61500: ('BUY', 8, 756),
        61600: ('BUY', 7, 755),
        61700: ('BUY', 9, 757),
        61800: ('BUY', 8, 757),
        61900: ('BUY', 8, 758),
        62000: ('BUY', 10, 757),
        62100: ('BUY', 6, 756),
        62200: ('BUY', 12, 756),
        62300: ('BUY', 12, 756),
        62400: ('BUY', 10, 756),
        62500: ('BUY', 8, 756),
        62600: ('BUY', 7, 757),
        62700: ('BUY', 10, 758),
        62800: ('BUY', 7, 757),
        62900: ('BUY', 11, 757),
        63000: ('BUY', 8, 757),
        63100: ('BUY', 11, 757),
        65000: ('BUY', 11, 758),
        66000: ('BUY', 3, 759),
        66400: ('BUY', 6, 759),
        66500: ('BUY', 6, 759),
        75200: ('BUY', 4, 755),
        77300: ('BUY', 6, 759),
        79300: ('BUY', 5, 757),
        82200: ('SELL', 12, 764),
        82300: ('SELL', 6, 764),
        82400: ('SELL', 12, 764),
        82600: ('SELL', 8, 764),
        84500: ('SELL', 8, 765),
        84600: ('SELL', 12, 765),
        84700: ('SELL', 10, 767),
        84800: ('SELL', 10, 765),
    },
    'VEV_5000': {
        400: ('BUY', 8, 271),
        500: ('BUY', 7, 269),
        600: ('BUY', 9, 268),
        700: ('BUY', 22, 269),
        800: ('BUY', 9, 269),
        900: ('BUY', 6, 269),
        1000: ('BUY', 12, 269),
        1100: ('BUY', 8, 270),
        1200: ('BUY', 24, 269),
        1300: ('BUY', 6, 268),
        1400: ('BUY', 12, 270),
        1500: ('BUY', 10, 271),
        1600: ('BUY', 7, 271),
        1800: ('BUY', 2, 272),
        1900: ('BUY', 11, 272),
        3300: ('SELL', 6, 273),
        3400: ('SELL', 10, 274),
        3500: ('SELL', 12, 273),
        3600: ('SELL', 27, 273),
        3700: ('SELL', 9, 273),
        3800: ('SELL', 30, 273),
        3900: ('SELL', 22, 273),
        4100: ('SELL', 10, 273),
        4200: ('SELL', 7, 274),
        4300: ('SELL', 9, 274),
        5300: ('SELL', 11, 273),
        5400: ('SELL', 25, 272),
        5500: ('SELL', 7, 275),
        5600: ('SELL', 21, 275),
        5700: ('SELL', 25, 275),
        5800: ('SELL', 11, 274),
        5900: ('SELL', 7, 274),
        6000: ('SELL', 11, 275),
        6100: ('SELL', 27, 274),
        6200: ('SELL', 12, 275),
        6300: ('SELL', 8, 274),
        6400: ('SELL', 11, 273),
        6500: ('SELL', 7, 273),
        6600: ('SELL', 24, 272),
        6700: ('SELL', 9, 272),
        6800: ('SELL', 8, 272),
        6900: ('SELL', 8, 273),
        7400: ('SELL', 7, 272),
        7500: ('SELL', 30, 273),
        7600: ('SELL', 12, 272),
        7700: ('SELL', 28, 272),
        7800: ('SELL', 2, 273),
        9400: ('BUY', 12, 270),
        9500: ('BUY', 9, 269),
        9600: ('BUY', 9, 269),
        9700: ('BUY', 25, 269),
        9800: ('BUY', 30, 269),
        9900: ('BUY', 8, 268),
        10000: ('BUY', 8, 269),
        10100: ('BUY', 9, 269),
        10200: ('BUY', 11, 268),
        10300: ('BUY', 11, 267),
        10400: ('BUY', 6, 268),
        10500: ('BUY', 34, 268),
        10600: ('BUY', 10, 267),
        10700: ('BUY', 22, 269),
        10800: ('BUY', 9, 267),
        10900: ('BUY', 28, 268),
        11000: ('BUY', 12, 269),
        11100: ('BUY', 11, 270),
        11200: ('BUY', 27, 271),
        11300: ('BUY', 9, 271),
        13100: ('BUY', 3, 268),
        13500: ('BUY', 6, 271),
        13700: ('BUY', 10, 271),
        14600: ('BUY', 11, 270),
        16300: ('SELL', 12, 272),
        16400: ('SELL', 22, 272),
        16500: ('SELL', 8, 272),
        16600: ('SELL', 10, 273),
        16700: ('SELL', 34, 272),
        16800: ('SELL', 10, 273),
        16900: ('SELL', 10, 273),
        17000: ('SELL', 8, 273),
        17100: ('SELL', 10, 273),
        17200: ('SELL', 8, 274),
        17300: ('SELL', 9, 275),
        17400: ('SELL', 11, 276),
        17500: ('SELL', 12, 276),
        17600: ('SELL', 10, 275),
        17700: ('SELL', 8, 273),
        17800: ('SELL', 11, 273),
        17900: ('SELL', 12, 273),
        18000: ('SELL', 8, 275),
        18100: ('SELL', 11, 274),
        18200: ('SELL', 12, 274),
        18300: ('SELL', 9, 274),
        18400: ('SELL', 7, 273),
        18500: ('SELL', 8, 273),
        19100: ('SELL', 2, 272),
        21700: ('SELL', 15, 271),
        21800: ('SELL', 34, 272),
        21900: ('SELL', 10, 272),
        22000: ('SELL', 9, 271),
        23500: ('BUY', 2, 267),
        23600: ('BUY', 7, 269),
        28000: ('BUY', 8, 269),
        29500: ('BUY', 2, 269),
        30300: ('BUY', 23, 269),
        30400: ('BUY', 7, 268),
        30600: ('BUY', 22, 268),
        30700: ('BUY', 6, 267),
        30800: ('BUY', 27, 266),
        30900: ('BUY', 6, 267),
        31000: ('BUY', 10, 265),
        31100: ('BUY', 10, 265),
        31200: ('BUY', 10, 265),
        31300: ('BUY', 9, 267),
        31400: ('BUY', 10, 267),
        31500: ('BUY', 26, 268),
        31600: ('BUY', 22, 268),
        33100: ('SELL', 8, 269),
        33400: ('SELL', 9, 269),
        33800: ('SELL', 11, 269),
        33900: ('SELL', 12, 270),
        34000: ('SELL', 9, 270),
        34100: ('SELL', 28, 271),
        34200: ('SELL', 29, 272),
        34300: ('SELL', 10, 272),
        34400: ('SELL', 8, 272),
        34500: ('SELL', 12, 271),
        34600: ('SELL', 30, 270),
        34700: ('SELL', 10, 270),
        35200: ('SELL', 2, 269),
        35400: ('SELL', 12, 269),
        35500: ('SELL', 7, 269),
        35600: ('SELL', 10, 269),
        40900: ('BUY', 6, 260),
        41200: ('BUY', 12, 259),
        41300: ('BUY', 8, 260),
        41400: ('BUY', 25, 260),
        41500: ('BUY', 11, 258),
        41600: ('BUY', 31, 258),
        41700: ('BUY', 11, 258),
        41800: ('BUY', 25, 259),
        41900: ('BUY', 2, 254),
        42000: ('BUY', 9, 256),
        42100: ('BUY', 7, 258),
        42200: ('BUY', 10, 259),
        42400: ('BUY', 10, 260),
        42500: ('BUY', 8, 260),
        42700: ('BUY', 29, 260),
        42800: ('BUY', 31, 260),
        42900: ('BUY', 4, 256),
        43000: ('BUY', 24, 260),
        43100: ('BUY', 22, 260),
        43200: ('BUY', 22, 260),
        43300: ('BUY', 25, 260),
        43400: ('BUY', 11, 260),
        43500: ('BUY', 24, 259),
        43600: ('BUY', 12, 259),
        43700: ('BUY', 9, 258),
        43800: ('BUY', 7, 257),
        43900: ('BUY', 24, 258),
        44000: ('BUY', 9, 258),
        44100: ('BUY', 23, 260),
        49900: ('SELL', 12, 261),
        50000: ('SELL', 8, 261),
        50100: ('SELL', 12, 261),
        50600: ('SELL', 27, 261),
        50700: ('SELL', 12, 262),
        50800: ('SELL', 11, 264),
        50900: ('SELL', 11, 265),
        51000: ('SELL', 10, 264),
        51100: ('SELL', 6, 264),
        51200: ('SELL', 12, 263),
        51300: ('SELL', 25, 264),
        51400: ('SELL', 12, 264),
        51500: ('SELL', 10, 263),
        51600: ('SELL', 8, 264),
        51700: ('SELL', 26, 262),
        51800: ('SELL', 6, 263),
        51900: ('SELL', 11, 262),
        52000: ('SELL', 27, 261),
        52100: ('SELL', 27, 262),
        52200: ('SELL', 12, 262),
        52300: ('SELL', 36, 262),
        52400: ('SELL', 10, 262),
        52500: ('SELL', 8, 261),
        52700: ('SELL', 3, 260),
        52800: ('SELL', 7, 260),
        52900: ('SELL', 11, 260),
        53100: ('SELL', 8, 261),
        53200: ('SELL', 31, 261),
        53300: ('SELL', 6, 262),
        53400: ('SELL', 9, 262),
        53500: ('SELL', 7, 261),
        53600: ('SELL', 9, 260),
        54200: ('SELL', 8, 260),
        54500: ('SELL', 6, 261),
        54600: ('SELL', 7, 261),
        57400: ('BUY', 12, 255),
        57600: ('BUY', 10, 255),
        57700: ('BUY', 9, 255),
        57800: ('BUY', 11, 255),
        57900: ('BUY', 8, 255),
        58000: ('BUY', 29, 255),
        58300: ('BUY', 12, 255),
        58400: ('BUY', 8, 254),
        58500: ('BUY', 6, 254),
        58600: ('BUY', 6, 254),
        58700: ('BUY', 6, 252),
        58800: ('BUY', 7, 250),
        58900: ('BUY', 34, 250),
        59000: ('BUY', 8, 250),
        59100: ('BUY', 11, 249),
        59200: ('BUY', 6, 248),
        59300: ('BUY', 8, 250),
        59400: ('BUY', 21, 250),
        59500: ('BUY', 19, 249),
        59600: ('BUY', 9, 248),
        59700: ('BUY', 6, 248),
        59800: ('BUY', 31, 250),
        59900: ('BUY', 12, 249),
        60000: ('BUY', 12, 250),
        60100: ('BUY', 35, 250),
        60200: ('BUY', 28, 250),
        60300: ('BUY', 6, 249),
        60400: ('BUY', 10, 251),
        60500: ('BUY', 6, 251),
        60600: ('BUY', 7, 252),
        60700: ('BUY', 10, 252),
        60800: ('BUY', 7, 253),
        60900: ('BUY', 10, 253),
        61000: ('BUY', 7, 253),
        61100: ('BUY', 12, 254),
        61200: ('BUY', 6, 255),
        61300: ('BUY', 7, 255),
        61400: ('BUY', 10, 255),
        61500: ('BUY', 31, 255),
        61600: ('BUY', 7, 254),
        61700: ('BUY', 9, 255),
        62100: ('BUY', 6, 255),
        62200: ('BUY', 12, 255),
        62300: ('BUY', 36, 255),
        62400: ('BUY', 24, 255),
        62500: ('BUY', 8, 255),
        65000: ('BUY', 5, 256),
        67600: ('SELL', 21, 259),
        67700: ('SELL', 10, 260),
        67800: ('SELL', 32, 259),
        67900: ('SELL', 30, 259),
        68000: ('SELL', 6, 260),
        68100: ('SELL', 8, 260),
        71400: ('BUY', 20, 259),
        71500: ('BUY', 32, 259),
        71600: ('BUY', 8, 259),
        71700: ('BUY', 9, 259),
        75200: ('BUY', 4, 258),
        77100: ('BUY', 11, 259),
        77200: ('BUY', 11, 259),
        77300: ('BUY', 6, 258),
        77400: ('BUY', 6, 258),
        82100: ('SELL', 23, 270),
        82200: ('SELL', 12, 272),
        82300: ('SELL', 6, 272),
        82400: ('SELL', 12, 272),
        82500: ('SELL', 24, 270),
        82600: ('SELL', 29, 271),
        82700: ('SELL', 26, 270),
        84400: ('SELL', 8, 271),
        84500: ('SELL', 20, 272),
        84600: ('SELL', 12, 273),
        84700: ('SELL', 10, 275),
        84800: ('SELL', 31, 273),
        84900: ('SELL', 8, 271),
        85500: ('SELL', 6, 270),
        85600: ('SELL', 7, 270),
        85700: ('SELL', 8, 271),
        86400: ('SELL', 6, 270),
        86500: ('SELL', 8, 270),
        87100: ('SELL', 12, 270),
        87300: ('SELL', 24, 270),
        87400: ('SELL', 22, 270),
        87500: ('SELL', 20, 270),
        87600: ('SELL', 10, 271),
        87700: ('SELL', 11, 270),
        87800: ('SELL', 12, 270),
        87900: ('SELL', 11, 271),
        88000: ('SELL', 7, 270),
        88600: ('SELL', 8, 270),
        88800: ('SELL', 10, 270),
        88900: ('SELL', 33, 270),
        89200: ('SELL', 10, 270),
        89500: ('SELL', 5, 269),
        90400: ('SELL', 6, 269),
        92800: ('SELL', 9, 270),
        92900: ('SELL', 28, 270),
        93000: ('SELL', 9, 271),
        93100: ('SELL', 12, 271),
        93200: ('SELL', 28, 269),
        93300: ('SELL', 12, 269),
        93800: ('SELL', 26, 269),
        93900: ('SELL', 9, 271),
        94000: ('SELL', 10, 270),
        95300: ('BUY', 11, 267),
        97400: ('BUY', 10, 267),
        97800: ('BUY', 11, 267),
    },
    'VEV_5100': {
        100: ('BUY', 4, 180),
        200: ('BUY', 23, 180),
        300: ('BUY', 9, 180),
        400: ('BUY', 22, 179),
        500: ('BUY', 23, 178),
        600: ('BUY', 23, 177),
        700: ('BUY', 7, 177),
        800: ('BUY', 9, 177),
        900: ('BUY', 6, 177),
        1000: ('BUY', 12, 177),
        1100: ('BUY', 8, 178),
        1200: ('BUY', 24, 177),
        1300: ('BUY', 21, 177),
        1400: ('BUY', 12, 178),
        1500: ('BUY', 33, 179),
        1600: ('BUY', 20, 179),
        1700: ('BUY', 6, 180),
        1800: ('BUY', 27, 180),
        1900: ('BUY', 11, 180),
        3300: ('SELL', 18, 182),
        3400: ('SELL', 10, 183),
        3500: ('SELL', 12, 182),
        3600: ('SELL', 27, 182),
        3700: ('SELL', 9, 182),
        3800: ('SELL', 30, 182),
        3900: ('SELL', 22, 182),
        4100: ('SELL', 32, 182),
        4200: ('SELL', 7, 183),
        4300: ('SELL', 9, 183),
        5000: ('SELL', 9, 182),
        5100: ('SELL', 9, 182),
        5200: ('SELL', 12, 182),
        5300: ('SELL', 29, 182),
        5400: ('SELL', 10, 182),
        5500: ('SELL', 28, 184),
        5600: ('SELL', 21, 184),
        5700: ('SELL', 25, 184),
        5800: ('SELL', 11, 183),
        5900: ('SELL', 20, 183),
        6000: ('SELL', 11, 184),
        6100: ('SELL', 27, 183),
        6200: ('SELL', 12, 184),
        6300: ('SELL', 8, 183),
        6400: ('SELL', 26, 182),
        6500: ('SELL', 22, 182),
        6600: ('SELL', 10, 182),
        6700: ('SELL', 1, 181),
        6800: ('SELL', 32, 181),
        6900: ('SELL', 8, 182),
        7000: ('SELL', 9, 181),
        7400: ('SELL', 29, 181),
        7500: ('SELL', 30, 182),
        7600: ('SELL', 12, 181),
        7700: ('SELL', 11, 182),
        7800: ('SELL', 2, 182),
        9400: ('BUY', 27, 179),
        9500: ('BUY', 22, 178),
        9600: ('BUY', 9, 177),
        9700: ('BUY', 7, 177),
        9800: ('BUY', 12, 177),
        9900: ('BUY', 22, 177),
        10000: ('BUY', 8, 177),
        10100: ('BUY', 22, 178),
        10200: ('BUY', 27, 177),
        10300: ('BUY', 33, 176),
        10400: ('BUY', 27, 177),
        10500: ('BUY', 11, 176),
        10600: ('BUY', 30, 176),
        10700: ('BUY', 8, 177),
        10800: ('BUY', 22, 176),
        10900: ('BUY', 11, 176),
        11000: ('BUY', 12, 177),
        11100: ('BUY', 11, 178),
        11200: ('BUY', 27, 179),
        11300: ('BUY', 9, 179),
        11800: ('BUY', 32, 180),
        12800: ('BUY', 36, 180),
        12900: ('BUY', 12, 180),
        13000: ('BUY', 24, 180),
        13100: ('BUY', 3, 177),
        13500: ('BUY', 6, 179),
        13600: ('BUY', 23, 180),
        13700: ('BUY', 10, 179),
        13800: ('BUY', 24, 180),
        14000: ('BUY', 8, 180),
        14200: ('BUY', 7, 180),
        14500: ('BUY', 28, 180),
        14600: ('BUY', 11, 178),
        14700: ('BUY', 10, 180),
        15000: ('BUY', 9, 180),
        16300: ('SELL', 12, 181),
        16400: ('SELL', 9, 182),
        16500: ('SELL', 8, 181),
        16600: ('SELL', 10, 182),
        16700: ('SELL', 11, 182),
        16800: ('SELL', 10, 182),
        16900: ('SELL', 10, 182),
        17000: ('SELL', 21, 182),
        17100: ('SELL', 24, 182),
        17200: ('SELL', 26, 183),
        17300: ('SELL', 9, 184),
        17400: ('SELL', 26, 184),
        17500: ('SELL', 27, 184),
        17600: ('SELL', 23, 183),
        17700: ('SELL', 26, 182),
        17800: ('SELL', 11, 182),
        17900: ('SELL', 32, 182),
        18000: ('SELL', 31, 183),
        18100: ('SELL', 11, 183),
        18200: ('SELL', 28, 183),
        18300: ('SELL', 25, 183),
        18400: ('SELL', 7, 182),
        18500: ('SELL', 28, 182),
        21500: ('SELL', 30, 180),
        21600: ('SELL', 26, 180),
        21700: ('SELL', 27, 180),
        21800: ('SELL', 34, 181),
        21900: ('SELL', 23, 181),
        22000: ('SELL', 25, 180),
        22100: ('SELL', 10, 180),
        23400: ('BUY', 16, 178),
        23500: ('BUY', 2, 176),
        23600: ('BUY', 7, 177),
        28000: ('BUY', 8, 177),
        30300: ('BUY', 35, 177),
        30400: ('BUY', 31, 177),
        30500: ('BUY', 6, 177),
        30600: ('BUY', 9, 176),
        30700: ('BUY', 6, 175),
        30800: ('BUY', 8, 174),
        30900: ('BUY', 6, 175),
        31000: ('BUY', 29, 174),
        31100: ('BUY', 33, 174),
        31200: ('BUY', 29, 174),
        31300: ('BUY', 9, 175),
        31400: ('BUY', 30, 176),
        31500: ('BUY', 26, 176),
        31600: ('BUY', 6, 176),
        31700: ('BUY', 9, 177),
        31800: ('BUY', 30, 177),
        31900: ('BUY', 32, 178),
        33900: ('SELL', 27, 179),
        34000: ('SELL', 22, 179),
        34100: ('SELL', 28, 180),
        34200: ('SELL', 29, 181),
        34300: ('SELL', 33, 181),
        34400: ('SELL', 8, 181),
        34500: ('SELL', 33, 180),
        34600: ('SELL', 30, 179),
        34700: ('SELL', 33, 179),
        34800: ('SELL', 6, 178),
        34900: ('SELL', 9, 178),
        35200: ('SELL', 2, 178),
        35400: ('SELL', 33, 178),
        35500: ('SELL', 31, 178),
        35600: ('SELL', 31, 178),
        36600: ('SELL', 6, 178),
        37200: ('SELL', 6, 178),
        40900: ('BUY', 6, 169),
        41200: ('BUY', 29, 169),
        41300: ('BUY', 8, 169),
        41400: ('BUY', 25, 169),
        41500: ('BUY', 26, 168),
        41600: ('BUY', 11, 167),
        41700: ('BUY', 33, 168),
        41800: ('BUY', 9, 168),
        41900: ('BUY', 2, 164),
        42000: ('BUY', 29, 166),
        42100: ('BUY', 7, 167),
        42200: ('BUY', 23, 169),
        42400: ('BUY', 10, 169),
        42700: ('BUY', 29, 169),
        42800: ('BUY', 31, 169),
        42900: ('BUY', 4, 167),
        43000: ('BUY', 24, 169),
        43100: ('BUY', 22, 169),
        43200: ('BUY', 22, 169),
        43300: ('BUY', 25, 169),
        43400: ('BUY', 26, 170),
        43500: ('BUY', 10, 168),
        43600: ('BUY', 35, 169),
        43700: ('BUY', 22, 168),
        43800: ('BUY', 19, 167),
        43900: ('BUY', 7, 167),
        44000: ('BUY', 33, 168),
        44100: ('BUY', 23, 169),
        44200: ('BUY', 18, 170),
        44300: ('BUY', 32, 170),
        49900: ('SELL', 12, 171),
        50000: ('SELL', 8, 171),
        50100: ('SELL', 25, 171),
        50400: ('SELL', 10, 171),
        50600: ('SELL', 6, 172),
        50700: ('SELL', 12, 172),
        50800: ('SELL', 11, 174),
        50900: ('SELL', 11, 175),
        51000: ('SELL', 10, 174),
        51100: ('SELL', 6, 174),
        51200: ('SELL', 24, 173),
        51300: ('SELL', 25, 174),
        51400: ('SELL', 27, 174),
        51500: ('SELL', 10, 173),
        51600: ('SELL', 23, 174),
        51700: ('SELL', 8, 173),
        51800: ('SELL', 6, 173),
        51900: ('SELL', 11, 172),
        52000: ('SELL', 9, 172),
        52100: ('SELL', 27, 172),
        52200: ('SELL', 29, 172),
        52300: ('SELL', 36, 172),
        52400: ('SELL', 32, 172),
        52500: ('SELL', 29, 171),
        52600: ('SELL', 7, 171),
        52900: ('SELL', 1, 170),
        53000: ('SELL', 11, 170),
        53100: ('SELL', 8, 171),
        53200: ('SELL', 10, 172),
        53300: ('SELL', 19, 172),
        53400: ('SELL', 9, 172),
        53500: ('SELL', 21, 171),
        53600: ('SELL', 21, 170),
        53700: ('SELL', 7, 170),
        53800: ('SELL', 9, 170),
        54200: ('SELL', 24, 170),
        54300: ('SELL', 9, 170),
        54400: ('SELL', 12, 170),
        54500: ('SELL', 18, 171),
        54600: ('SELL', 7, 171),
        58400: ('BUY', 8, 164),
        58500: ('BUY', 6, 164),
        58600: ('BUY', 6, 164),
        58700: ('BUY', 24, 163),
        58800: ('BUY', 29, 161),
        58900: ('BUY', 10, 160),
        59000: ('BUY', 28, 161),
        59100: ('BUY', 24, 160),
        59200: ('BUY', 6, 159),
        59300: ('BUY', 31, 161),
        59400: ('BUY', 8, 160),
        59500: ('BUY', 7, 159),
        59600: ('BUY', 9, 159),
        59700: ('BUY', 6, 159),
        59800: ('BUY', 7, 160),
        59900: ('BUY', 28, 160),
        60000: ('BUY', 34, 161),
        60100: ('BUY', 12, 160),
        60200: ('BUY', 8, 160),
        60300: ('BUY', 18, 160),
        60400: ('BUY', 10, 161),
        60500: ('BUY', 18, 162),
        60600: ('BUY', 20, 163),
        60700: ('BUY', 34, 163),
        60800: ('BUY', 29, 164),
        60900: ('BUY', 10, 163),
        61000: ('BUY', 7, 163),
        61100: ('BUY', 12, 164),
        61600: ('BUY', 7, 164),
        61700: ('BUY', 5, 165),
        62000: ('BUY', 10, 165),
        62100: ('BUY', 25, 165),
        62200: ('BUY', 12, 165),
        62300: ('BUY', 36, 165),
        62400: ('BUY', 24, 165),
        62500: ('BUY', 32, 165),
        64600: ('SELL', 10, 166),
        65000: ('BUY', 10, 166),
        67600: ('SELL', 9, 170),
        67700: ('SELL', 32, 170),
        67800: ('SELL', 8, 170),
        67900: ('SELL', 8, 170),
        68000: ('SELL', 24, 170),
        68100: ('SELL', 22, 170),
        68200: ('SELL', 11, 170),
        68300: ('SELL', 28, 169),
        68400: ('SELL', 12, 169),
        69600: ('SELL', 8, 169),
        69900: ('SELL', 8, 169),
        70000: ('SELL', 10, 169),
        70400: ('SELL', 8, 169),
        70500: ('SELL', 8, 169),
        71400: ('BUY', 8, 168),
        71500: ('BUY', 11, 168),
        71600: ('BUY', 8, 168),
        71900: ('BUY', 21, 169),
        72600: ('SELL', 12, 170),
        72800: ('SELL', 10, 170),
        75200: ('BUY', 4, 168),
        76200: ('BUY', 8, 169),
        76900: ('BUY', 9, 169),
        77000: ('BUY', 10, 169),
        77100: ('BUY', 35, 169),
        77200: ('BUY', 11, 168),
        77300: ('BUY', 25, 168),
        77400: ('BUY', 25, 168),
        77500: ('BUY', 12, 169),
        77600: ('BUY', 10, 169),
        77700: ('BUY', 9, 169),
        78600: ('BUY', 12, 169),
        82100: ('SELL', 23, 179),
        82200: ('SELL', 12, 181),
        82300: ('SELL', 6, 181),
        82400: ('SELL', 12, 181),
        82500: ('SELL', 24, 179),
        82600: ('SELL', 29, 180),
        82700: ('SELL', 12, 180),
        84400: ('SELL', 8, 180),
        84500: ('SELL', 20, 181),
        84600: ('SELL', 30, 182),
        84700: ('SELL', 10, 184),
        84800: ('SELL', 31, 182),
        84900: ('SELL', 8, 180),
        85500: ('SELL', 19, 179),
        85600: ('SELL', 27, 179),
        85700: ('SELL', 20, 180),
        87300: ('SELL', 11, 180),
        87400: ('SELL', 22, 179),
        87500: ('SELL', 20, 179),
        87600: ('SELL', 10, 180),
        87700: ('SELL', 25, 179),
        87800: ('SELL', 35, 179),
        87900: ('SELL', 11, 180),
        88000: ('SELL', 19, 179),
        88600: ('SELL', 8, 179),
        88700: ('SELL', 9, 179),
        88800: ('SELL', 10, 179),
        88900: ('SELL', 33, 179),
        89200: ('SELL', 10, 179),
        92800: ('SELL', 9, 179),
        92900: ('SELL', 28, 179),
        93000: ('SELL', 9, 180),
        93100: ('SELL', 12, 180),
        93800: ('SELL', 9, 179),
        93900: ('SELL', 9, 180),
        94000: ('SELL', 10, 179),
        95200: ('BUY', 8, 176),
        95300: ('BUY', 28, 176),
        95400: ('BUY', 8, 176),
        95800: ('BUY', 11, 176),
        95900: ('BUY', 8, 176),
        96000: ('BUY', 23, 176),
        96100: ('BUY', 11, 176),
        97300: ('BUY', 28, 176),
        97400: ('BUY', 10, 175),
        97500: ('BUY', 6, 176),
        97600: ('BUY', 11, 176),
        97700: ('BUY', 24, 176),
        97800: ('BUY', 33, 176),
        97900: ('BUY', 21, 176),
    },
    'VEV_5200': {
        400: ('BUY', 22, 104),
        500: ('BUY', 23, 103),
        600: ('BUY', 23, 102),
        700: ('BUY', 7, 102),
        800: ('BUY', 22, 103),
        900: ('BUY', 25, 103),
        1000: ('BUY', 24, 103),
        1100: ('BUY', 23, 103),
        1200: ('BUY', 8, 102),
        1300: ('BUY', 21, 102),
        1400: ('BUY', 12, 103),
        1500: ('BUY', 33, 104),
        1600: ('BUY', 20, 104),
        1800: ('BUY', 12, 105),
        1900: ('BUY', 25, 105),
        3300: ('SELL', 18, 107),
        3400: ('SELL', 10, 108),
        3500: ('SELL', 33, 107),
        3600: ('SELL', 27, 107),
        3700: ('SELL', 22, 107),
        3800: ('SELL', 30, 107),
        3900: ('SELL', 22, 107),
        4000: ('SELL', 6, 107),
        4100: ('SELL', 32, 107),
        4200: ('SELL', 7, 108),
        4300: ('SELL', 9, 108),
        4900: ('SELL', 8, 107),
        5000: ('SELL', 9, 107),
        5100: ('SELL', 9, 107),
        5200: ('SELL', 12, 107),
        5300: ('SELL', 29, 107),
        5400: ('SELL', 10, 107),
        5500: ('SELL', 7, 109),
        5600: ('SELL', 9, 109),
        5700: ('SELL', 10, 109),
        5800: ('SELL', 11, 108),
        5900: ('SELL', 20, 108),
        6000: ('SELL', 27, 108),
        6100: ('SELL', 27, 108),
        6200: ('SELL', 24, 108),
        6300: ('SELL', 8, 108),
        6400: ('SELL', 26, 107),
        6500: ('SELL', 22, 107),
        6600: ('SELL', 10, 107),
        6900: ('SELL', 24, 107),
        7400: ('SELL', 7, 107),
        7500: ('SELL', 30, 107),
        7600: ('SELL', 7, 106),
        7700: ('SELL', 11, 107),
        7800: ('SELL', 2, 106),
        7900: ('SELL', 25, 106),
        9400: ('BUY', 27, 104),
        9500: ('BUY', 9, 103),
        9600: ('BUY', 31, 103),
        9700: ('BUY', 25, 103),
        9800: ('BUY', 30, 103),
        9900: ('BUY', 8, 102),
        10000: ('BUY', 21, 103),
        10100: ('BUY', 22, 103),
        10200: ('BUY', 11, 102),
        10300: ('BUY', 33, 102),
        10400: ('BUY', 6, 102),
        10500: ('BUY', 34, 102),
        10600: ('BUY', 30, 102),
        10700: ('BUY', 22, 103),
        10800: ('BUY', 22, 102),
        10900: ('BUY', 28, 102),
        11000: ('BUY', 34, 103),
        11100: ('BUY', 30, 104),
        11200: ('BUY', 8, 104),
        13100: ('BUY', 3, 103),
        13600: ('BUY', 4, 105),
        13700: ('BUY', 32, 105),
        13800: ('BUY', 24, 105),
        14000: ('BUY', 8, 105),
        14200: ('BUY', 7, 105),
        14400: ('BUY', 11, 105),
        14500: ('BUY', 28, 105),
        14600: ('BUY', 25, 104),
        14700: ('BUY', 10, 105),
        14900: ('BUY', 8, 105),
        15000: ('BUY', 9, 105),
        16400: ('SELL', 9, 107),
        16600: ('SELL', 24, 107),
        16700: ('SELL', 11, 107),
        16800: ('SELL', 10, 107),
        16900: ('SELL', 28, 107),
        17000: ('SELL', 21, 107),
        17100: ('SELL', 24, 107),
        17200: ('SELL', 26, 108),
        17300: ('SELL', 22, 108),
        17400: ('SELL', 26, 109),
        17500: ('SELL', 27, 109),
        17600: ('SELL', 23, 108),
        17700: ('SELL', 26, 107),
        17800: ('SELL', 26, 107),
        17900: ('SELL', 32, 107),
        18000: ('SELL', 31, 108),
        18100: ('SELL', 31, 108),
        18200: ('SELL', 28, 108),
        18300: ('SELL', 25, 108),
        18400: ('SELL', 23, 107),
        18500: ('SELL', 28, 107),
        19700: ('BUY', 22, 106),
        19800: ('BUY', 6, 106),
        21500: ('SELL', 8, 106),
        21600: ('SELL', 26, 106),
        21700: ('SELL', 27, 106),
        21800: ('SELL', 34, 106),
        21900: ('SELL', 23, 106),
        22000: ('SELL', 9, 106),
        23400: ('BUY', 32, 103),
        23500: ('BUY', 2, 102),
        23600: ('BUY', 26, 103),
        28000: ('BUY', 26, 103),
        29500: ('BUY', 2, 103),
        30200: ('BUY', 6, 103),
        30300: ('BUY', 35, 103),
        30400: ('BUY', 7, 102),
        30500: ('BUY', 21, 103),
        30600: ('BUY', 22, 102),
        30700: ('BUY', 6, 101),
        30800: ('BUY', 27, 101),
        30900: ('BUY', 6, 101),
        31000: ('BUY', 29, 100),
        31100: ('BUY', 10, 100),
        31200: ('BUY', 29, 100),
        31300: ('BUY', 9, 101),
        31400: ('BUY', 30, 102),
        31500: ('BUY', 26, 102),
        31600: ('BUY', 22, 102),
        31700: ('BUY', 27, 103),
        31800: ('BUY', 30, 103),
        33000: ('SELL', 15, 104),
        33900: ('SELL', 27, 105),
        34000: ('SELL', 22, 105),
        34100: ('SELL', 28, 106),
        34200: ('SELL', 9, 107),
        34300: ('SELL', 33, 106),
        34400: ('SELL', 22, 106),
        34500: ('SELL', 12, 106),
        34600: ('SELL', 30, 105),
        34700: ('SELL', 33, 105),
        34800: ('SELL', 26, 104),
        34900: ('SELL', 9, 104),
        35200: ('SELL', 2, 104),
        35400: ('SELL', 33, 104),
        35500: ('SELL', 31, 104),
        35600: ('SELL', 31, 104),
        36400: ('SELL', 9, 104),
        36500: ('SELL', 12, 104),
        36600: ('SELL', 26, 104),
        37200: ('SELL', 20, 104),
        40900: ('BUY', 25, 97),
        41000: ('BUY', 12, 97),
        41100: ('BUY', 28, 97),
        41200: ('BUY', 12, 96),
        41300: ('BUY', 31, 97),
        41400: ('BUY', 25, 97),
        41500: ('BUY', 26, 96),
        41600: ('BUY', 31, 95),
        41700: ('BUY', 11, 95),
        41800: ('BUY', 25, 96),
        41900: ('BUY', 2, 93),
        42000: ('BUY', 29, 94),
        42100: ('BUY', 7, 95),
        42200: ('BUY', 10, 96),
        42300: ('BUY', 6, 97),
        42400: ('BUY', 20, 97),
        42700: ('BUY', 11, 97),
        42800: ('BUY', 31, 97),
        42900: ('BUY', 4, 95),
        43000: ('BUY', 7, 96),
        43100: ('BUY', 22, 97),
        43200: ('BUY', 22, 97),
        43300: ('BUY', 6, 96),
        43400: ('BUY', 30, 97),
        43500: ('BUY', 24, 96),
        43600: ('BUY', 35, 96),
        43700: ('BUY', 22, 96),
        43800: ('BUY', 19, 95),
        43900: ('BUY', 24, 95),
        44000: ('BUY', 9, 95),
        44100: ('BUY', 6, 96),
        44200: ('BUY', 18, 97),
        44300: ('BUY', 10, 97),
        50100: ('SELL', 12, 99),
        50600: ('SELL', 27, 99),
        50700: ('SELL', 26, 99),
        50800: ('SELL', 11, 101),
        50900: ('SELL', 24, 101),
        51000: ('SELL', 10, 101),
        51100: ('SELL', 6, 101),
        51200: ('SELL', 24, 100),
        51300: ('SELL', 25, 101),
        51400: ('SELL', 27, 101),
        51500: ('SELL', 23, 100),
        51600: ('SELL', 23, 101),
        51700: ('SELL', 8, 100),
        51800: ('SELL', 6, 100),
        51900: ('SELL', 28, 99),
        52000: ('SELL', 27, 99),
        52100: ('SELL', 9, 100),
        52200: ('SELL', 29, 99),
        52300: ('SELL', 12, 100),
        52400: ('SELL', 32, 99),
        52900: ('SELL', 19, 98),
        53100: ('SELL', 21, 98),
        53200: ('SELL', 31, 99),
        53300: ('SELL', 19, 99),
        53400: ('SELL', 28, 99),
        53500: ('SELL', 7, 99),
        53600: ('SELL', 21, 98),
        53700: ('SELL', 7, 98),
        54200: ('SELL', 24, 98),
        54300: ('SELL', 9, 98),
        54400: ('SELL', 12, 98),
        54500: ('SELL', 6, 99),
        54600: ('SELL', 7, 99),
        58700: ('BUY', 24, 92),
        58800: ('BUY', 29, 91),
        58900: ('BUY', 34, 90),
        59000: ('BUY', 8, 90),
        59100: ('BUY', 24, 90),
        59200: ('BUY', 6, 89),
        59300: ('BUY', 8, 90),
        59400: ('BUY', 21, 90),
        59500: ('BUY', 7, 89),
        59600: ('BUY', 25, 89),
        59700: ('BUY', 23, 89),
        59800: ('BUY', 31, 90),
        59900: ('BUY', 28, 90),
        60000: ('BUY', 34, 91),
        60100: ('BUY', 35, 90),
        60200: ('BUY', 28, 90),
        60300: ('BUY', 18, 90),
        60400: ('BUY', 28, 91),
        60500: ('BUY', 18, 91),
        60600: ('BUY', 20, 92),
        60700: ('BUY', 34, 92),
        60800: ('BUY', 7, 92),
        60900: ('BUY', 27, 92),
        61000: ('BUY', 21, 92),
        61600: ('BUY', 12, 93),
        62100: ('BUY', 6, 93),
        62300: ('BUY', 12, 93),
        62400: ('BUY', 24, 93),
        62500: ('BUY', 8, 93),
        64200: ('SELL', 9, 94),
        64400: ('SELL', 2, 94),
        65000: ('BUY', 11, 94),
        67600: ('SELL', 9, 98),
        67700: ('SELL', 32, 98),
        67800: ('SELL', 32, 97),
        67900: ('SELL', 32, 97),
        68000: ('SELL', 24, 98),
        68100: ('SELL', 8, 98),
        68200: ('SELL', 32, 97),
        68300: ('SELL', 28, 97),
        69600: ('SELL', 8, 97),
        69900: ('SELL', 8, 97),
        70000: ('SELL', 31, 97),
        70300: ('SELL', 10, 97),
        70400: ('SELL', 20, 97),
        70500: ('SELL', 20, 97),
        71400: ('BUY', 20, 96),
        71500: ('BUY', 32, 96),
        71600: ('BUY', 31, 96),
        71700: ('BUY', 9, 96),
        72200: ('SELL', 12, 97),
        72400: ('SELL', 8, 97),
        72500: ('SELL', 29, 97),
        72600: ('SELL', 12, 98),
        72700: ('SELL', 26, 97),
        72800: ('SELL', 10, 98),
        72900: ('SELL', 1, 97),
        73100: ('SELL', 4, 97),
        75200: ('BUY', 4, 96),
        77000: ('BUY', 22, 97),
        77100: ('BUY', 11, 96),
        77200: ('BUY', 31, 96),
        77300: ('BUY', 25, 96),
        77400: ('BUY', 25, 96),
        77500: ('BUY', 32, 97),
        77600: ('BUY', 31, 97),
        77700: ('BUY', 30, 97),
        78000: ('BUY', 31, 97),
        78500: ('BUY', 6, 97),
        78600: ('BUY', 35, 97),
        78700: ('BUY', 21, 97),
        82100: ('SELL', 23, 105),
        82200: ('SELL', 27, 106),
        82300: ('SELL', 18, 106),
        82400: ('SELL', 33, 106),
        82500: ('SELL', 24, 105),
        82600: ('SELL', 29, 106),
        82700: ('SELL', 26, 105),
        84400: ('SELL', 7, 105),
        84500: ('SELL', 8, 107),
        84600: ('SELL', 30, 107),
        84700: ('SELL', 25, 108),
        84800: ('SELL', 31, 107),
        85700: ('SELL', 8, 106),
        87900: ('SELL', 11, 106),
        88600: ('SELL', 25, 105),
        88700: ('SELL', 27, 105),
        88800: ('SELL', 22, 105),
        88900: ('SELL', 33, 105),
        89200: ('SELL', 22, 105),
        89300: ('SELL', 11, 105),
        89400: ('SELL', 8, 105),
        92800: ('SELL', 33, 105),
        92900: ('SELL', 28, 105),
        93000: ('SELL', 22, 105),
        93100: ('SELL', 12, 106),
        93200: ('SELL', 6, 105),
        93800: ('SELL', 9, 105),
        93900: ('SELL', 9, 106),
        94000: ('SELL', 33, 105),
        95300: ('BUY', 28, 102),
        95800: ('BUY', 11, 102),
        95900: ('BUY', 8, 102),
        96000: ('BUY', 9, 102),
        97300: ('BUY', 8, 102),
        97400: ('BUY', 22, 102),
        97500: ('BUY', 6, 102),
        97700: ('BUY', 24, 102),
        97800: ('BUY', 33, 102),
        97900: ('BUY', 8, 102),
    },
    'VEV_5300': {
        100: ('BUY', 6, 53),
        200: ('BUY', 6, 53),
        400: ('BUY', 26, 53),
        500: ('BUY', 5, 52),
        600: ('BUY', 24, 52),
        700: ('BUY', 18, 52),
        800: ('BUY', 20, 52),
        900: ('BUY', 24, 52),
        1000: ('BUY', 26, 52),
        1100: ('BUY', 29, 53),
        1200: ('BUY', 21, 52),
        1300: ('BUY', 16, 52),
        1400: ('BUY', 21, 53),
        1500: ('BUY', 25, 53),
        1600: ('BUY', 19, 53),
        1800: ('BUY', 6, 53),
        2500: ('SELL', 21, 54),
        2600: ('SELL', 16, 54),
        2700: ('SELL', 3, 54),
        3300: ('SELL', 6, 55),
        3400: ('SELL', 25, 55),
        3600: ('SELL', 23, 55),
        3800: ('SELL', 10, 55),
        3900: ('SELL', 8, 55),
        4100: ('SELL', 8, 55),
        4200: ('SELL', 26, 55),
        4300: ('SELL', 27, 55),
        5500: ('SELL', 28, 55),
        5600: ('SELL', 5, 56),
        5700: ('SELL', 7, 56),
        5800: ('SELL', 25, 55),
        5900: ('SELL', 23, 55),
        6000: ('SELL', 28, 55),
        6100: ('SELL', 21, 55),
        6200: ('SELL', 23, 55),
        6300: ('SELL', 24, 55),
        6400: ('SELL', 25, 54),
        6500: ('SELL', 22, 54),
        6600: ('SELL', 23, 54),
        6700: ('SELL', 22, 54),
        6800: ('SELL', 20, 54),
        6900: ('SELL', 19, 54),
        7000: ('SELL', 26, 54),
        7400: ('SELL', 20, 54),
        7500: ('SELL', 8, 55),
        7600: ('SELL', 23, 54),
        7700: ('SELL', 19, 54),
        7800: ('SELL', 2, 54),
        7900: ('SELL', 6, 54),
        9500: ('BUY', 21, 52),
        9600: ('BUY', 20, 52),
        9700: ('BUY', 24, 52),
        9800: ('BUY', 20, 52),
        9900: ('BUY', 25, 52),
        10000: ('BUY', 24, 52),
        10100: ('BUY', 19, 52),
        10200: ('BUY', 25, 52),
        10300: ('BUY', 26, 51),
        10400: ('BUY', 25, 52),
        10500: ('BUY', 5, 51),
        10600: ('BUY', 27, 51),
        10700: ('BUY', 20, 52),
        10800: ('BUY', 24, 51),
        10900: ('BUY', 10, 51),
        11000: ('BUY', 18, 52),
        11100: ('BUY', 10, 52),
        12800: ('BUY', 19, 53),
        12900: ('BUY', 8, 53),
        13000: ('BUY', 25, 53),
        13100: ('BUY', 3, 52),
        13500: ('BUY', 25, 53),
        13600: ('BUY', 20, 53),
        13700: ('BUY', 28, 53),
        13800: ('BUY', 21, 53),
        13900: ('BUY', 6, 53),
        14000: ('BUY', 22, 53),
        14100: ('BUY', 10, 53),
        14200: ('BUY', 9, 53),
        14400: ('BUY', 5, 53),
        14500: ('BUY', 24, 53),
        14600: ('BUY', 7, 52),
        14700: ('BUY', 9, 53),
        14900: ('BUY', 7, 53),
        15000: ('BUY', 9, 53),
        16300: ('SELL', 8, 54),
        16400: ('SELL', 26, 54),
        16500: ('SELL', 25, 54),
        16600: ('SELL', 18, 54),
        16700: ('SELL', 18, 54),
        16800: ('SELL', 20, 54),
        16900: ('SELL', 27, 54),
        17000: ('SELL', 19, 54),
        17100: ('SELL', 25, 54),
        17200: ('SELL', 9, 55),
        17300: ('SELL', 19, 55),
        17400: ('SELL', 20, 55),
        17500: ('SELL', 24, 55),
        17600: ('SELL', 23, 55),
        17700: ('SELL', 24, 54),
        17800: ('SELL', 23, 54),
        17900: ('SELL', 25, 54),
        18000: ('SELL', 16, 55),
        18100: ('SELL', 5, 55),
        18200: ('SELL', 6, 55),
        18300: ('SELL', 7, 55),
        18400: ('SELL', 28, 54),
        18500: ('SELL', 21, 54),
        19800: ('BUY', 21, 53),
        21500: ('SELL', 20, 53),
        21600: ('SELL', 24, 53),
        21700: ('SELL', 27, 53),
        21800: ('SELL', 23, 54),
        21900: ('SELL', 23, 54),
        22000: ('SELL', 19, 53),
        22100: ('SELL', 24, 53),
        22200: ('SELL', 16, 53),
        22300: ('SELL', 9, 53),
        23400: ('BUY', 12, 52),
        23500: ('BUY', 2, 51),
        26000: ('SELL', 6, 52),
        26900: ('SELL', 8, 52),
        28000: ('BUY', 10, 51),
        30300: ('BUY', 6, 51),
        30400: ('BUY', 20, 51),
        30600: ('BUY', 26, 51),
        30700: ('BUY', 18, 51),
        30800: ('BUY', 20, 50),
        30900: ('BUY', 17, 51),
        31000: ('BUY', 21, 50),
        31100: ('BUY', 22, 50),
        31200: ('BUY', 20, 50),
        31300: ('BUY', 21, 51),
        31400: ('BUY', 22, 51),
        31500: ('BUY', 18, 51),
        31600: ('BUY', 16, 51),
        31700: ('BUY', 27, 51),
        31800: ('BUY', 23, 51),
        33000: ('SELL', 7, 52),
        34000: ('SELL', 17, 52),
        34100: ('SELL', 24, 53),
        34200: ('SELL', 26, 53),
        34300: ('SELL', 19, 53),
        34400: ('SELL', 21, 53),
        34500: ('SELL', 26, 53),
        34600: ('SELL', 6, 53),
        34700: ('SELL', 27, 52),
        34800: ('SELL', 15, 52),
        34900: ('SELL', 7, 52),
        35400: ('SELL', 18, 52),
        35500: ('SELL', 18, 52),
        35600: ('SELL', 22, 52),
        36500: ('SELL', 10, 52),
        36600: ('SELL', 24, 52),
        37200: ('SELL', 20, 52),
        40900: ('BUY', 8, 47),
        41200: ('BUY', 20, 47),
        41300: ('BUY', 9, 47),
        41400: ('BUY', 5, 47),
        41500: ('BUY', 27, 47),
        41600: ('BUY', 20, 47),
        41700: ('BUY', 27, 47),
        41800: ('BUY', 29, 47),
        41900: ('BUY', 2, 45),
        42000: ('BUY', 22, 46),
        42100: ('BUY', 22, 47),
        42200: ('BUY', 20, 47),
        42400: ('BUY', 8, 47),
        42700: ('BUY', 22, 47),
        42800: ('BUY', 17, 47),
        42900: ('BUY', 4, 46),
        43000: ('BUY', 25, 47),
        43100: ('BUY', 19, 47),
        43200: ('BUY', 24, 47),
        43300: ('BUY', 19, 47),
        43500: ('BUY', 24, 47),
        43600: ('BUY', 25, 47),
        43700: ('BUY', 20, 47),
        43800: ('BUY', 19, 46),
        43900: ('BUY', 8, 46),
        44000: ('BUY', 17, 47),
        44100: ('BUY', 30, 47),
        46100: ('BUY', 2, 48),
        46200: ('BUY', 19, 48),
        50800: ('SELL', 17, 49),
        50900: ('SELL', 21, 50),
        51000: ('SELL', 23, 49),
        51100: ('SELL', 20, 49),
        51200: ('SELL', 24, 49),
        51300: ('SELL', 22, 49),
        51400: ('SELL', 28, 49),
        51500: ('SELL', 24, 49),
        51600: ('SELL', 19, 49),
        51700: ('SELL', 6, 49),
        51800: ('SELL', 9, 49),
        52000: ('SELL', 21, 48),
        52100: ('SELL', 7, 49),
        52200: ('SELL', 23, 48),
        52300: ('SELL', 25, 48),
        52400: ('SELL', 20, 48),
        52500: ('SELL', 21, 48),
        52600: ('SELL', 7, 48),
        53100: ('SELL', 19, 48),
        53200: ('SELL', 24, 48),
        53300: ('SELL', 21, 48),
        53400: ('SELL', 26, 48),
        53500: ('SELL', 19, 48),
        53600: ('SELL', 7, 48),
        54200: ('SELL', 8, 48),
        54500: ('SELL', 30, 48),
        54600: ('SELL', 22, 48),
        58700: ('BUY', 19, 44),
        58800: ('BUY', 25, 43),
        58900: ('BUY', 25, 43),
        59000: ('BUY', 26, 43),
        59100: ('BUY', 24, 43),
        59200: ('BUY', 9, 42),
        59300: ('BUY', 24, 43),
        59400: ('BUY', 21, 43),
        59500: ('BUY', 21, 43),
        59600: ('BUY', 5, 42),
        59700: ('BUY', 21, 42),
        59800: ('BUY', 24, 43),
        59900: ('BUY', 19, 43),
        60000: ('BUY', 22, 43),
        60100: ('BUY', 21, 43),
        60200: ('BUY', 19, 43),
        60300: ('BUY', 24, 43),
        60400: ('BUY', 5, 43),
        60500: ('BUY', 6, 43),
        60600: ('BUY', 23, 44),
        60700: ('BUY', 29, 44),
        60800: ('BUY', 22, 44),
        60900: ('BUY', 18, 44),
        61000: ('BUY', 20, 44),
        62400: ('BUY', 7, 45),
        62500: ('BUY', 22, 45),
        62600: ('BUY', 23, 45),
        62800: ('BUY', 18, 45),
        62900: ('BUY', 5, 45),
        63000: ('BUY', 24, 45),
        63100: ('BUY', 29, 45),
        67500: ('SELL', 10, 47),
        67600: ('SELL', 27, 47),
        67700: ('SELL', 25, 47),
        67800: ('SELL', 25, 47),
        67900: ('SELL', 29, 47),
        68000: ('SELL', 20, 47),
        68100: ('SELL', 21, 47),
        68200: ('SELL', 18, 47),
        68300: ('SELL', 25, 47),
        69900: ('SELL', 9, 47),
        70000: ('SELL', 5, 47),
        70300: ('SELL', 6, 47),
        70400: ('SELL', 19, 47),
        70500: ('SELL', 23, 47),
        71400: ('BUY', 8, 46),
        71500: ('BUY', 5, 46),
        72500: ('SELL', 29, 47),
        72600: ('SELL', 22, 47),
        76900: ('BUY', 4, 47),
        77000: ('BUY', 20, 47),
        77100: ('BUY', 20, 47),
        77200: ('BUY', 21, 47),
        77300: ('BUY', 27, 46),
        77400: ('BUY', 24, 46),
        77500: ('BUY', 26, 47),
        77600: ('BUY', 28, 47),
        77700: ('BUY', 18, 47),
        77800: ('BUY', 6, 47),
        78000: ('BUY', 26, 47),
        78300: ('BUY', 5, 47),
        78400: ('BUY', 8, 47),
        78500: ('BUY', 25, 47),
        78600: ('BUY', 20, 47),
        78700: ('BUY', 22, 47),
        82100: ('SELL', 22, 52),
        82200: ('SELL', 5, 53),
        82300: ('SELL', 7, 53),
        82400: ('SELL', 10, 53),
        82500: ('SELL', 28, 52),
        82600: ('SELL', 23, 52),
        82700: ('SELL', 25, 52),
        84400: ('SELL', 15, 52),
        84500: ('SELL', 21, 53),
        84600: ('SELL', 26, 53),
        84700: ('SELL', 17, 54),
        84800: ('SELL', 21, 53),
        84900: ('SELL', 21, 52),
        85500: ('SELL', 22, 52),
        85600: ('SELL', 20, 52),
        85700: ('SELL', 17, 52),
        87600: ('SELL', 9, 52),
        87700: ('SELL', 17, 52),
        87800: ('SELL', 24, 52),
        87900: ('SELL', 21, 52),
        88000: ('SELL', 27, 52),
        88600: ('SELL', 6, 52),
        88700: ('SELL', 5, 52),
        88800: ('SELL', 5, 52),
        88900: ('SELL', 21, 52),
        89200: ('SELL', 27, 52),
        89400: ('SELL', 10, 52),
        92800: ('SELL', 25, 52),
        92900: ('SELL', 29, 52),
        93000: ('SELL', 20, 52),
        93100: ('SELL', 25, 52),
        93900: ('SELL', 20, 52),
        94000: ('SELL', 9, 52),
        95200: ('BUY', 25, 50),
        95300: ('BUY', 20, 50),
        95400: ('BUY', 19, 50),
        95800: ('BUY', 17, 50),
        95900: ('BUY', 25, 50),
        96000: ('BUY', 29, 50),
        96100: ('BUY', 29, 50),
        97300: ('BUY', 23, 50),
        97400: ('BUY', 25, 50),
        97500: ('BUY', 23, 50),
        97600: ('BUY', 17, 50),
        97700: ('BUY', 21, 50),
        97800: ('BUY', 25, 50),
        97900: ('BUY', 2, 50),
    },
    'VEV_5400': {
        400: ('BUY', 26, 17),
        500: ('BUY', 19, 17),
        600: ('BUY', 24, 17),
        700: ('BUY', 18, 17),
        800: ('BUY', 20, 17),
        900: ('BUY', 24, 17),
        1000: ('BUY', 26, 17),
        1100: ('BUY', 29, 17),
        1200: ('BUY', 21, 17),
        1300: ('BUY', 16, 17),
        1400: ('BUY', 21, 17),
        1500: ('BUY', 9, 17),
        1600: ('BUY', 7, 17),
        2500: ('SELL', 21, 18),
        2600: ('SELL', 16, 18),
        2700: ('SELL', 8, 18),
        3100: ('SELL', 23, 18),
        3200: ('SELL', 18, 18),
        3300: ('SELL', 18, 18),
        3400: ('SELL', 25, 18),
        3500: ('SELL', 20, 18),
        3600: ('SELL', 23, 18),
        3700: ('SELL', 21, 18),
        3800: ('SELL', 21, 18),
        3900: ('SELL', 19, 18),
        4000: ('SELL', 26, 18),
        4100: ('SELL', 1, 18),
        5800: ('SELL', 20, 18),
        5900: ('SELL', 23, 18),
        6000: ('SELL', 28, 18),
        6100: ('SELL', 21, 18),
        6200: ('SELL', 23, 18),
        6300: ('SELL', 24, 18),
        6400: ('SELL', 25, 18),
        6500: ('SELL', 22, 18),
        6600: ('SELL', 23, 18),
        6700: ('SELL', 9, 18),
        6800: ('SELL', 5, 18),
        6900: ('SELL', 19, 18),
        7400: ('SELL', 20, 18),
        7500: ('SELL', 19, 18),
        7700: ('SELL', 19, 18),
        9400: ('BUY', 19, 17),
        9500: ('BUY', 21, 17),
        9600: ('BUY', 20, 17),
        9700: ('BUY', 24, 17),
        9800: ('BUY', 20, 17),
        9900: ('BUY', 25, 17),
        10000: ('BUY', 24, 17),
        10100: ('BUY', 19, 17),
        10200: ('BUY', 25, 17),
        10300: ('BUY', 26, 17),
        10400: ('BUY', 25, 17),
        10500: ('BUY', 25, 17),
        10600: ('BUY', 27, 17),
        10700: ('BUY', 20, 17),
        10800: ('BUY', 24, 17),
        10900: ('BUY', 22, 17),
        11000: ('BUY', 18, 17),
        11100: ('BUY', 24, 17),
        11200: ('BUY', 30, 17),
        11300: ('BUY', 10, 17),
        13500: ('BUY', 25, 17),
        13700: ('BUY', 8, 17),
        14600: ('BUY', 19, 17),
        16300: ('SELL', 8, 18),
        16400: ('SELL', 26, 18),
        16500: ('SELL', 25, 18),
        16600: ('SELL', 18, 18),
        16700: ('SELL', 18, 18),
        16800: ('SELL', 20, 18),
        16900: ('SELL', 27, 18),
        17000: ('SELL', 19, 18),
        17100: ('SELL', 25, 18),
        17200: ('SELL', 14, 18),
        17500: ('SELL', 21, 18),
        17600: ('SELL', 23, 18),
        17700: ('SELL', 24, 18),
        17800: ('SELL', 23, 18),
        17900: ('SELL', 25, 18),
        18000: ('SELL', 16, 18),
        18100: ('SELL', 25, 18),
        18200: ('SELL', 21, 18),
        18300: ('SELL', 27, 18),
        18400: ('SELL', 28, 18),
        18500: ('SELL', 21, 18),
        21800: ('SELL', 23, 18),
        21900: ('SELL', 23, 18),
        23300: ('BUY', 22, 17),
        23400: ('BUY', 20, 17),
        23500: ('BUY', 23, 17),
        23600: ('BUY', 27, 17),
        23700: ('BUY', 18, 17),
        23800: ('BUY', 23, 17),
        23900: ('BUY', 21, 17),
        24000: ('BUY', 24, 17),
        24100: ('BUY', 27, 17),
        24200: ('BUY', 20, 17),
        24300: ('BUY', 3, 17),
        26000: ('SELL', 6, 17),
        26900: ('SELL', 20, 17),
        30800: ('BUY', 20, 16),
        30900: ('BUY', 7, 16),
        31000: ('BUY', 21, 16),
        31100: ('BUY', 22, 16),
        31200: ('BUY', 20, 16),
        31300: ('BUY', 8, 16),
        32200: ('BUY', 8, 17),
        34200: ('SELL', 8, 18),
        34300: ('SELL', 1, 17),
        34400: ('SELL', 21, 17),
        34500: ('SELL', 26, 17),
        34600: ('SELL', 24, 17),
        34700: ('SELL', 27, 17),
        34800: ('SELL', 15, 17),
        34900: ('SELL', 21, 17),
        35200: ('SELL', 2, 17),
        35400: ('SELL', 18, 17),
        35500: ('SELL', 18, 17),
        35600: ('SELL', 22, 17),
        36100: ('SELL', 23, 17),
        36200: ('SELL', 22, 17),
        36400: ('SELL', 6, 17),
        36500: ('SELL', 10, 17),
        36600: ('SELL', 24, 17),
        37200: ('SELL', 20, 17),
        40700: ('BUY', 23, 15),
        40800: ('BUY', 20, 15),
        40900: ('BUY', 19, 15),
        41000: ('BUY', 18, 15),
        41100: ('BUY', 22, 15),
        41200: ('BUY', 20, 15),
        41300: ('BUY', 27, 15),
        41400: ('BUY', 21, 15),
        41500: ('BUY', 27, 15),
        41600: ('BUY', 20, 15),
        41700: ('BUY', 27, 15),
        41800: ('BUY', 21, 15),
        41900: ('BUY', 5, 14),
        42000: ('BUY', 22, 14),
        43800: ('BUY', 8, 14),
        46100: ('BUY', 2, 15),
        46200: ('BUY', 19, 15),
        50900: ('SELL', 21, 16),
        51900: ('SELL', 16, 15),
        52000: ('SELL', 23, 15),
        52100: ('SELL', 26, 15),
        52200: ('SELL', 23, 15),
        52300: ('SELL', 25, 15),
        52400: ('SELL', 20, 15),
        52500: ('SELL', 21, 15),
        52600: ('SELL', 21, 15),
        53100: ('SELL', 19, 15),
        53200: ('SELL', 24, 15),
        53300: ('SELL', 21, 15),
        53400: ('SELL', 26, 15),
        53500: ('SELL', 19, 15),
        54500: ('SELL', 10, 15),
        54600: ('SELL', 6, 15),
        58700: ('BUY', 19, 13),
        58800: ('BUY', 25, 13),
        58900: ('BUY', 25, 13),
        59000: ('BUY', 26, 13),
        59100: ('BUY', 24, 13),
        59200: ('BUY', 28, 13),
        59300: ('BUY', 24, 13),
        59400: ('BUY', 21, 13),
        59500: ('BUY', 21, 13),
        59600: ('BUY', 17, 13),
        59700: ('BUY', 21, 13),
        59800: ('BUY', 24, 13),
        59900: ('BUY', 19, 13),
        60000: ('BUY', 22, 13),
        60100: ('BUY', 21, 13),
        60200: ('BUY', 19, 13),
        60300: ('BUY', 24, 13),
        60400: ('BUY', 22, 13),
        60500: ('BUY', 19, 13),
        60600: ('BUY', 23, 13),
        60700: ('BUY', 29, 13),
        60800: ('BUY', 22, 13),
        60900: ('BUY', 18, 13),
        61000: ('BUY', 20, 13),
        64600: ('SELL', 23, 14),
        65300: ('BUY', 1, 14),
        65400: ('BUY', 19, 14),
        65500: ('BUY', 6, 14),
        66000: ('BUY', 25, 14),
        66400: ('BUY', 19, 14),
        66500: ('BUY', 20, 14),
        67700: ('SELL', 25, 15),
        68000: ('SELL', 7, 15),
        77300: ('BUY', 27, 14),
        77400: ('BUY', 5, 14),
        82100: ('SELL', 22, 17),
        82200: ('SELL', 17, 17),
        82300: ('SELL', 17, 17),
        82400: ('SELL', 22, 17),
        82500: ('SELL', 28, 17),
        82600: ('SELL', 23, 17),
        82700: ('SELL', 25, 17),
        84400: ('SELL', 15, 17),
        84500: ('SELL', 21, 17),
        84600: ('SELL', 26, 17),
        84700: ('SELL', 17, 18),
        84800: ('SELL', 21, 17),
        84900: ('SELL', 21, 17),
        85500: ('SELL', 22, 17),
        85600: ('SELL', 3, 17),
        87800: ('SELL', 22, 17),
        87900: ('SELL', 21, 17),
        88000: ('SELL', 27, 17),
        88500: ('SELL', 7, 17),
        88600: ('SELL', 19, 17),
        88700: ('SELL', 22, 17),
        88800: ('SELL', 15, 17),
        88900: ('SELL', 21, 17),
        89200: ('SELL', 27, 17),
        92800: ('SELL', 10, 17),
        92900: ('SELL', 29, 17),
        93000: ('SELL', 20, 17),
        93100: ('SELL', 25, 17),
        93800: ('SELL', 6, 17),
        93900: ('SELL', 20, 17),
        94000: ('SELL', 9, 17),
        95200: ('BUY', 25, 16),
        95300: ('BUY', 20, 16),
        95400: ('BUY', 19, 16),
        95800: ('BUY', 17, 16),
        95900: ('BUY', 25, 16),
        96000: ('BUY', 29, 16),
        96100: ('BUY', 29, 16),
        97100: ('BUY', 7, 16),
        97200: ('BUY', 6, 16),
        97300: ('BUY', 23, 16),
        97400: ('BUY', 25, 16),
        97500: ('BUY', 23, 16),
        97600: ('BUY', 17, 16),
        97700: ('BUY', 21, 16),
        97800: ('BUY', 14, 16),
    },
    'VEV_5500': {
        21400: ('SELL', 10, 7),
        21500: ('SELL', 29, 7),
        21600: ('SELL', 24, 7),
        21700: ('SELL', 27, 7),
        21800: ('SELL', 23, 7),
        21900: ('SELL', 23, 7),
        22000: ('SELL', 19, 7),
        22100: ('SELL', 24, 7),
        22200: ('SELL', 5, 7),
        34100: ('SELL', 24, 7),
        34200: ('SELL', 26, 7),
        34300: ('SELL', 19, 7),
        34400: ('SELL', 21, 7),
        34500: ('SELL', 26, 7),
        40600: ('BUY', 28, 6),
        40700: ('BUY', 23, 6),
        40800: ('BUY', 20, 6),
        40900: ('BUY', 19, 6),
        41000: ('BUY', 18, 6),
        41100: ('BUY', 22, 6),
        41200: ('BUY', 20, 6),
        41300: ('BUY', 27, 6),
        41400: ('BUY', 21, 6),
        41500: ('BUY', 27, 6),
        41600: ('BUY', 20, 6),
        41700: ('BUY', 27, 6),
        41800: ('BUY', 28, 6),
        53000: ('SELL', 20, 6),
        53100: ('SELL', 19, 6),
        53200: ('SELL', 24, 6),
        53300: ('SELL', 21, 6),
        53400: ('SELL', 26, 6),
        53500: ('SELL', 19, 6),
        53600: ('SELL', 25, 6),
        53700: ('SELL', 20, 6),
        53800: ('SELL', 15, 6),
        54200: ('SELL', 19, 6),
        54300: ('SELL', 23, 6),
        54400: ('SELL', 17, 6),
        54500: ('SELL', 30, 6),
        54600: ('SELL', 22, 6),
        58800: ('BUY', 25, 5),
        58900: ('BUY', 25, 5),
        59000: ('BUY', 26, 5),
        59100: ('BUY', 24, 5),
        59200: ('BUY', 28, 5),
        59300: ('BUY', 24, 5),
        59400: ('BUY', 21, 5),
        59500: ('BUY', 21, 5),
        59600: ('BUY', 17, 5),
        59700: ('BUY', 21, 5),
        59800: ('BUY', 24, 5),
        59900: ('BUY', 19, 5),
        60000: ('BUY', 22, 5),
        60100: ('BUY', 21, 5),
        60200: ('BUY', 19, 5),
        60300: ('BUY', 24, 5),
        67500: ('SELL', 10, 6),
        67600: ('SELL', 27, 6),
        67700: ('SELL', 24, 6),
        78300: ('BUY', 17, 6),
        78400: ('BUY', 23, 6),
        78500: ('BUY', 25, 6),
        78600: ('BUY', 20, 6),
        78700: ('BUY', 22, 6),
        78800: ('BUY', 25, 6),
        78900: ('BUY', 25, 6),
        79000: ('BUY', 24, 6),
        79100: ('BUY', 25, 6),
        79200: ('BUY', 23, 6),
        79500: ('BUY', 19, 6),
        79700: ('BUY', 26, 6),
        79800: ('BUY', 21, 6),
        79900: ('BUY', 5, 6),
        82100: ('SELL', 7, 7),
        82200: ('SELL', 17, 7),
        82300: ('SELL', 17, 7),
        82400: ('SELL', 22, 7),
        82600: ('SELL', 23, 7),
        84400: ('SELL', 5, 7),
        84500: ('SELL', 21, 7),
        84600: ('SELL', 26, 7),
        84700: ('SELL', 17, 7),
        84800: ('SELL', 21, 7),
        84900: ('SELL', 21, 7),
        85700: ('SELL', 24, 7),
    },
}


class OracleDay2L1ReplayStrategy(BaseStrategy):
    """Replay the DP-optimal top-of-book taker schedule for day2 0..99900."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        action = ORACLE_L1_SCHEDULE.get(self.product, {}).get(int(state.timestamp))
        if action is None:
            return [], 0
        side, qty, price = action
        if side == "BUY":
            qty = min(int(qty), self.buy_capacity(position))
            if qty <= 0:
                return [], 0
            return [Order(self.product, int(price), qty)], 0
        qty = min(int(qty), self.sell_capacity(position))
        if qty <= 0:
            return [], 0
        return [Order(self.product, int(price), -qty)], 0


# ── prosperity/strategies/round_3/hydrogel_day2_selector_mm.py ────────────────────

class HydrogelDay2SelectorMMStrategy(BaseStrategy):
    """Route HYDRO between anchor, guarded Theo, and day2 L1 replay profiles."""

    ROUTE_CODES = {
        "guarded": 0,
        "anchor": 1,
        "oracle_day2": 2,
        "blocked_oracle": 3,
    }

    def __init__(self, product: str, params: Dict[str, Any]):
        super().__init__(product, params)
        limit = int(params.get("position_limit", 200))
        self._anchor = MMFirstV4ComboStrategy(
            product=product,
            params=self._child_params(params, "anchor_params", limit),
        )
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
        route = self._select_route(state, book, memory, p)
        memory["_selector_route"] = route
        memory["_selector_route_code"] = float(self.ROUTE_CODES.get(route, -1))

        if route == "oracle_day2":
            orders = self._oracle_orders(state, book, position, p, memory)
            if orders:
                return orders, 0
            memory["_selector_route"] = "blocked_oracle"
            memory["_selector_route_code"] = float(self.ROUTE_CODES["blocked_oracle"])
            return [], 0

        if route == "anchor":
            child_memory = memory.setdefault("_anchor_child", {})
            return self._anchor.on_tick(state, child_memory)

        child_memory = memory.setdefault("_guarded_child", {})
        return self._guarded.on_tick(state, child_memory)

    def _select_route(
        self,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
        p: Dict[str, Any],
    ) -> str:
        mode = p["selector_mode"]
        day2_like = self._is_day2_like(state, book, memory, p)

        if mode == "anchor_only":
            return "anchor"
        if mode == "day2_oracle_guarded":
            return "oracle_day2" if day2_like else "guarded"
        if mode == "hybrid_anchor_oracle":
            return "oracle_day2" if day2_like else "anchor"
        if mode == "hybrid_stationary":
            if day2_like:
                return "oracle_day2"
            return "anchor" if self._is_stationary(book, memory, p) else "guarded"
        return "guarded"

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
        target = p["day2_start_mid"]
        tol = p["day2_start_mid_tolerance"]
        day2_like = abs(start_mid - target) <= tol
        memory["_selector_day2_like"] = float(day2_like)
        memory["_selector_start_mid"] = start_mid
        return day2_like

    def _is_stationary(self, book: BookSnapshot, memory: Dict[str, Any], p: Dict[str, Any]) -> bool:
        anchor = p["anchor_price"]
        drift = float(book.mid_price) - anchor
        alpha = p["stationary_ewma_alpha"]
        prev = float(memory.get("_stationary_drift_ewma", drift))
        ewma = alpha * drift + (1.0 - alpha) * prev
        memory["_stationary_drift_ewma"] = ewma
        return abs(ewma) <= p["stationary_max_abs_drift"]

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

        side, raw_qty, replay_price = action
        tol = p["oracle_price_tolerance"]
        use_live_l1 = p["oracle_use_live_l1"]

        if side == "BUY":
            if book.best_ask is None:
                return []
            live_price = int(book.best_ask)
            if abs(live_price - int(replay_price)) > tol:
                memory["_selector_oracle_blocked_px"] = float(replay_price)
                memory["_selector_oracle_live_px"] = float(live_price)
                return []
            qty = min(int(raw_qty), self.buy_capacity(position))
            if qty <= 0:
                return []
            return [Order(self.product, live_price if use_live_l1 else int(replay_price), qty)]

        if book.best_bid is None:
            return []
        live_price = int(book.best_bid)
        if abs(live_price - int(replay_price)) > tol:
            memory["_selector_oracle_blocked_px"] = float(replay_price)
            memory["_selector_oracle_live_px"] = float(live_price)
            return []
        qty = min(int(raw_qty), self.sell_capacity(position))
        if qty <= 0:
            return []
        return [Order(self.product, live_price if use_live_l1 else int(replay_price), -qty)]

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "selector_mode": str(params.get("selector_mode", "day2_oracle_guarded")),
            "day2_start_mid": float(params.get("day2_start_mid", 10011.0)),
            "day2_start_mid_tolerance": float(params.get("day2_start_mid_tolerance", 0.25)),
            "oracle_price_tolerance": int(params.get("oracle_price_tolerance", 2)),
            "oracle_use_live_l1": bool(params.get("oracle_use_live_l1", True)),
            "anchor_price": float(params.get("anchor_price", 10000.0)),
            "stationary_ewma_alpha": float(params.get("stationary_ewma_alpha", 0.01)),
            "stationary_max_abs_drift": float(params.get("stationary_max_abs_drift", 55.0)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key in (
            "_selector_route_code",
            "_selector_day2_like",
            "_selector_start_mid",
            "_stationary_drift_ewma",
            "_selector_oracle_blocked_px",
            "_selector_oracle_live_px",
        ):
            value = memory.get(key)
            if value is not None:
                out[key.removeprefix("_selector_").removeprefix("_")] = float(value)

        route = memory.get("_selector_route")
        if route == "anchor":
            child = memory.get("_anchor_child", {})
            out.update({f"anchor_{k}": v for k, v in self._anchor.feature_prices(child).items()})
        elif route == "guarded":
            child = memory.get("_guarded_child", {})
            out.update({f"guarded_{k}": v for k, v in self._guarded.feature_prices(child).items()})
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
                   'anchor_price': 10000.0,
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
                   'selector_mode': 'hybrid_anchor_oracle',
                   'stationary_ewma_alpha': 0.01,
                   'stationary_max_abs_drift': 55.0,
                   'strategy': 'hydrogel_day2_selector_mm',
                   'tighten_ticks': 1,
                   'ts_increment': 100}}

STRATEGY_CLASSES = {"hydrogel_day2_selector_mm": HydrogelDay2SelectorMMStrategy}

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
