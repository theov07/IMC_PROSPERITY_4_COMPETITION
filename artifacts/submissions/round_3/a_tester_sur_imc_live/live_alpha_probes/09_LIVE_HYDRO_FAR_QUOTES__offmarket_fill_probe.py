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

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'anchor_alpha': 0.02,
                   'anchor_drift_bound': 2.0,
                   'anchor_price': 10000.0,
                   'ar_gain': 0.3,
                   'ar_shift_source': 'mid_smooth',
                   'full_capacity_on_empty': False,
                   'gap_trigger_min': 0,
                   'inventory_aversion_gamma': 0.0015,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'maker_size_base_pct': 0.04,
                   'pct_kept_for_takers': 0.8,
                   'position_limit': 60,
                   'probe_distance': 80,
                   'probe_interval_ticks': 150,
                   'probe_qty': 1,
                   'probe_t0_distances': [30, 60, 100, 150],
                   'probe_t0_max_ts': 1000,
                   'probe_t0_qty': 1,
                   'quote_trace_enabled': True,
                   'strategy': 'mm_first_v4_combo',
                   'take_edge': 1000000.0,
                   'take_edge_hi': 1000000.0,
                   'take_edge_lo': 1000000.0,
                   'taker_buy_threshold': -1000000,
                   'taker_sell_threshold': 1000000,
                   'tighten_ticks': 1,
                   'ts_increment': 100,
                   'unwind_take_edge': 3.0}}

STRATEGY_CLASSES = {"mm_first_v4_combo": MMFirstV4ComboStrategy}

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
