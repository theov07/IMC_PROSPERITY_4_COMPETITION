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


# ── prosperity/strategies/round_3/tibo/mm_first_v4_combo.py ───────────────────────

class MMFirstV4ComboStrategy(BaseStrategy):

    def _compute_quote_prices(
        self,
        book: BookSnapshot,
        inventory_ratio: float,
        mid_smooth: float,
    ) -> Tuple[Optional[int], Optional[int], str]:
        bid_price = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price = (book.best_ask - 1) if book.best_ask is not None else None
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
        max_scale  = float(self.params.get("zscore_max_scale", 3.0))
        excess = max(0.0, abs(z) - threshold)
        scale  = min(max_scale, 1.0 + size_scale * excess)
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

    def _compute_anchor_signal(
        self,
        mid: float,
        book: BookSnapshot,
        mid_smooth: float,
        memory: Dict[str, Any],
    ) -> float:
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

    def _compute_asym_take_edges(
        self,
        base_edge: float,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[float, float]:
        unwind = float(self.params.get("unwind_take_edge", 0.0))
        if unwind <= 0:
            return base_edge, base_edge
        limit = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if position > 0:
            sell_edge = max(0.0, base_edge - unwind * pressure)
            buy_edge  = base_edge + unwind * pressure
        elif position < 0:
            buy_edge  = max(0.0, base_edge - unwind * pressure)
            sell_edge = base_edge + unwind * pressure
        else:
            return base_edge, base_edge
        return buy_edge, sell_edge

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
        taker_buy_threshold  = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")
        orders: List[Order] = []
        taker_buy_px:  Set[int] = set()
        taker_sell_px: Set[int] = set()
        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
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
            volume     = order_depth.buy_orders[bid_p]
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
        gap_min     = float(self.params.get("gap_trigger_min", 10))
        shift       = float(self.params.get("OB_cleared_shift", 10))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))
        z           = memory.get("zscore")
        gap_gate    = float(self.params.get("zscore_gap_gate",
                            self.params.get("zscore_threshold", 1.0)))
        bid_z_ok = z is None or z >= -gap_gate
        ask_z_ok = z is None or z <= gap_gate
        orders: List[Order] = []
        memory["_gap_buy_px"]  = []
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
                bid1_vol   = order_depth.buy_orders[bid1]
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
                ask1_vol   = -order_depth.sell_orders[ask1]
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
        final_remaining_bids = [p for p in remaining_bids if p not in gap_swept_bids]
        final_remaining_asks = [p for p in remaining_asks if p not in gap_swept_asks]
        if final_remaining_asks:
            ask_price = final_remaining_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + int(shift)
        if final_remaining_bids:
            bid_price = final_remaining_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - int(shift)
        return orders, buy_cap, sell_cap, bid_price, ask_price

    def _apply_toxic_flow(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        toxic_threshold = float(self.params.get("toxic_threshold", 0.0))
        if toxic_threshold <= 0:
            return buy_size, sell_size
        toxic_window    = int(self.params.get("toxic_window", 6))
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
            total  = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total
        memory["_flow_score"] = flow_score
        if flow_score > toxic_threshold and sell_size > 0:
            sell_size = max(1.0, sell_size * toxic_size_frac)
        elif flow_score < -toxic_threshold and buy_size > 0:
            buy_size = max(1.0, buy_size * toxic_size_frac)
        return buy_size, sell_size

    def _apply_jump_filter(
        self,
        book: BookSnapshot,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        threshold = float(self.params.get("trend_jump_threshold", 0.0))
        if threshold <= 0:
            return buy_size, sell_size
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))
        prev_best_bid  = memory.get("_prev_best_bid")
        prev_best_ask  = memory.get("_prev_best_ask")
        bid_jumped = prev_best_bid is not None and book.best_bid == prev_best_bid + 1
        ask_jumped = prev_best_ask is not None and book.best_ask == prev_best_ask - 1
        if bid_jumped and sell_size > 0:
            sell_size = max(1.0, sell_size * jump_size_frac)
        if ask_jumped and buy_size > 0:
            buy_size = max(1.0, buy_size * jump_size_frac)
        return buy_size, sell_size

    def _compute_base_mid(self, raw_mid: float, book: BookSnapshot) -> float:
        vol_filter = int(self.params.get("mid_vol_filter", 0))
        if vol_filter <= 0:
            return raw_mid
        wall_bid = wall_ask = None
        for (p, v) in book.bid_levels:
            if v >= vol_filter:
                wall_bid = p
                break
        for (p, v) in book.ask_levels:
            if v >= vol_filter:
                wall_ask = p
                break
        if wall_bid is None or wall_ask is None:
            return raw_mid
        return (wall_bid + wall_ask) / 2.0

    def _taker_cooldown_active(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[bool, bool]:
        cooldown = int(self.params.get("taker_cooldown_ticks", 0))
        if cooldown <= 0:
            return False, False
        now          = int(state.timestamp)
        ts_increment = int(self.params.get("ts_increment", 100))
        last_buy     = memory.get("_last_taker_buy_ts")
        last_sell    = memory.get("_last_taker_sell_ts")
        buy_blocked  = last_buy  is not None and (now - last_buy)  < cooldown * ts_increment
        sell_blocked = last_sell is not None and (now - last_sell) < cooldown * ts_increment
        return buy_blocked, sell_blocked

    def _update_taker_cooldown(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> None:
        now = int(state.timestamp)
        if taker_buy_px:
            memory["_last_taker_buy_ts"]  = now
        if taker_sell_px:
            memory["_last_taker_sell_ts"] = now

    def _apply_inventory_bias(
        self,
        fair_value: float,
        position: int,
        memory: Dict[str, Any],
    ) -> float:
        gamma = float(self.params.get("inventory_aversion_gamma", 0.0))
        if gamma <= 0 or position == 0:
            return fair_value
        sigma = memory.get("sigma_smoothed", 1.0)
        return fair_value - gamma * position * (sigma ** 2)

    def _microprice_size_tilt(
        self,
        book: BookSnapshot,
        raw_mid: float,
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        gain = float(self.params.get("microprice_size_gain", 0.0))
        if gain <= 0:
            return bid_size, ask_size
        threshold = float(self.params.get("microprice_size_threshold", 0.2))
        micro = self._microprice(book)
        delta = micro - raw_mid
        if abs(delta) < threshold:
            return bid_size, ask_size
        scale = 1.0 + gain * (abs(delta) - threshold)
        if delta > 0:
            return bid_size / scale, ask_size * scale
        else:
            return bid_size * scale, ask_size / scale

    def _apply_spread_widening(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        threshold = float(self.params.get("spread_widen_vol_threshold", 0.0))
        if threshold <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        sigma = memory.get("sigma_smoothed", 0.0)
        if sigma < threshold:
            return bid_price, ask_price
        extra   = int(self.params.get("spread_widen_extra_ticks", 1))
        new_bid = max(1, bid_price - extra)
        new_ask = ask_price + extra
        if book.best_ask is not None:
            new_bid = min(new_bid, book.best_ask - 1)
        if book.best_bid is not None:
            new_ask = max(new_ask, book.best_bid + 1)
        return new_bid, new_ask

    def _effective_position(self, position: int) -> int:
        target = int(self.params.get("inventory_target", 0))
        return position - target

    def _apply_fill_rate_toxicity(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        window = int(self.params.get("fill_toxicity_window", 0))
        if window <= 0:
            return bid_size, ask_size
        history = memory.setdefault("_fill_history", [])
        for trade in state.own_trades.get(self.product, []):
            qty = float(trade.quantity)
            if trade.buyer == "SUBMISSION":
                history.append(qty)
            elif trade.seller == "SUBMISSION":
                history.append(-qty)
        if len(history) > window:
            del history[:-window]
        if not history:
            return bid_size, ask_size
        signed  = sum(history)
        total   = sum(abs(x) for x in history)
        if total <= 0:
            return bid_size, ask_size
        imbalance = signed / total
        threshold = float(self.params.get("fill_toxicity_threshold", 0.7))
        frac      = float(self.params.get("fill_toxicity_frac", 0.5))
        if imbalance > threshold and bid_size > 0:
            bid_size = max(1.0, bid_size * frac)
        elif imbalance < -threshold and ask_size > 0:
            ask_size = max(1.0, ask_size * frac)
        return bid_size, ask_size

    def _apply_spread_zscore_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
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
        var  = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        std  = var ** 0.5
        if std < 1e-9:
            return bid_price, ask_price
        z         = (spread - mean) / std
        threshold = float(self.params.get("spread_zscore_threshold", 1.5))
        if z < threshold:
            return bid_price, ask_price
        shift   = int(self.params.get("spread_zscore_shift", 1))
        new_bid = min(book.best_ask - 1, bid_price + shift)
        new_ask = max(book.best_bid + 1, ask_price - shift)
        if new_bid >= new_ask:
            new_ask = new_bid + 1
        return new_bid, new_ask

    def _probe_tick0(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        distances = self.params.get("probe_t0_distances")
        if not distances or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap
        max_ts = int(self.params.get("probe_t0_max_ts", 500))
        now    = int(state.timestamp)
        if now > max_ts:
            return [], buy_cap, sell_cap
        if memory.get("_probe_t0_fired", False):
            return [], buy_cap, sell_cap
        qty    = int(self.params.get("probe_t0_qty", 1))
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

    def _apply_momentum_follower(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        window = int(self.params.get("momentum_window", 0))
        if window <= 0:
            return [], buy_cap, sell_cap
        history   = memory.setdefault("_momentum_history", [])
        prev_bid  = memory.get("_prev_best_bid")
        prev_ask  = memory.get("_prev_best_ask")
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
        total  = sum(abs(x) for x in history)
        if total <= 0:
            return [], buy_cap, sell_cap
        flow      = signed / total
        threshold = float(self.params.get("momentum_threshold", 0.8))
        qty       = int(self.params.get("momentum_qty", 3))
        orders: List[Order] = []
        if flow > threshold and buy_cap > 0:
            asks = sorted(order_depth.sell_orders.keys())
            if asks:
                ask_p     = asks[0]
                available = -order_depth.sell_orders[ask_p]
                q = min(qty, buy_cap, available)
                if q > 0:
                    orders.append(Order(self.product, ask_p, q))
                    buy_cap -= q
        elif flow < -threshold and sell_cap > 0:
            bids = sorted(order_depth.buy_orders.keys(), reverse=True)
            if bids:
                bid_p  = bids[0]
                volume = order_depth.buy_orders[bid_p]
                q = min(qty, sell_cap, volume)
                if q > 0:
                    orders.append(Order(self.product, bid_p, -q))
                    sell_cap -= q
        return orders, buy_cap, sell_cap

    def _probe_quotes(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        probe_dist = int(self.params.get("probe_distance", 0))
        if probe_dist <= 0 or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap
        probe_qty      = int(self.params.get("probe_qty", 1))
        probe_interval = int(self.params.get("probe_interval_ticks", 100))
        ts_increment   = int(self.params.get("ts_increment", 100))
        now            = int(state.timestamp)
        last_probe     = memory.get("_last_probe_ts", -(10 ** 9))
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

    def _asym_passive_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        position: int,
        book: BookSnapshot,
    ) -> Tuple[Optional[int], Optional[int]]:
        skew_max = int(self.params.get("passive_unwind_skew_ticks", 0))
        if skew_max <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        trigger  = float(self.params.get("passive_unwind_trigger", 0.3))
        limit    = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if pressure < trigger:
            return bid_price, ask_price
        scaled = (pressure - trigger) / max(1e-9, 1.0 - trigger)
        skew   = int(round(skew_max * scaled))
        if skew <= 0:
            return bid_price, ask_price
        if position > 0:
            ask_price = max(book.best_bid + 1, ask_price - skew)
        elif position < 0:
            bid_price = min(book.best_ask - 1, bid_price + skew)
        return bid_price, ask_price

    def _apply_eod_flatten(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        position: int,
    ) -> Optional[List[Order]]:
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
        quote_buy  = min(buy_cap,  int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))
        inv_abs    = abs(position) / float(limit) if limit else 0.0
        hard_stop  = 1.0 - float(self.params.get("pct_kept_for_takers", 0.2))
        if inv_abs >= hard_stop:
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
        prev_taker_buy_px  = set(memory.get("_taker_buy_px", []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        prev_gap_buy_px    = set(memory.get("_gap_buy_px_prev", []))
        prev_gap_sell_px   = set(memory.get("_gap_sell_px_prev", []))
        memory["_taker_buy_px"]      = list(this_taker_buy_px)
        memory["_taker_sell_px"]     = list(this_taker_sell_px)
        memory["_gap_buy_px_prev"]   = list(memory.get("_gap_buy_px", []))
        memory["_gap_sell_px_prev"]  = list(memory.get("_gap_sell_px", []))
        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY", trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                is_gap = (
                    (side == "BUY"  and trade.price in prev_gap_buy_px)
                    or (side == "SELL" and trade.price in prev_gap_sell_px)
                )
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                    gap_exploit=is_gap,
                )

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
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
        if self.params.get("use_microprice_as_fair", False):
            micro    = self._microprice(book)
            base_mid = micro if micro else mid
        else:
            base_mid = self._compute_base_mid(mid, book)
        mid_smooth = self._smooth_mid(base_mid, memory)
        self._compute_zscore(base_mid, memory)
        sigma      = self._update_volatility(base_mid, memory)
        fair_value = self._compute_anchor_signal(base_mid, book, mid_smooth, memory)
        eff_position = self._effective_position(position)
        fair_value   = self._apply_inventory_bias(fair_value, eff_position, memory)
        limit         = self.position_limit()
        inventory_ratio = position / float(limit) if limit else 0.0
        bid_price, ask_price, _ = self._compute_quote_prices(book, inventory_ratio, fair_value)
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        bid_size, ask_size = self._compute_sizes(position, limit)
        bid_factor, ask_factor = self._zscore_size_factors(memory)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)
        bid_size, ask_size = self._microprice_size_tilt(book, mid, bid_size, ask_size)
        base_edge       = self._dynamic_take_edge(memory)
        buy_edge, sell_edge = self._compute_asym_take_edges(base_edge, eff_position, memory)
        buy_blocked, sell_blocked = self._taker_cooldown_active(state, memory)
        if buy_blocked:
            buy_edge = 1_000_000.0
        if sell_blocked:
            sell_edge = 1_000_000.0
        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._fire_takers(
            order_depth, fair_value, bid_size, ask_size, buy_cap, sell_cap,
            buy_edge=buy_edge, sell_edge=sell_edge,
        )
        self._update_taker_cooldown(state, memory, taker_buy_px, taker_sell_px)
        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap,
            taker_buy_px, taker_sell_px,
        )
        bid_price, ask_price = self._asym_passive_skew(bid_price, ask_price, eff_position, book)
        bid_price, ask_price = self._apply_spread_widening(bid_price, ask_price, book, memory)
        bid_price, ask_price = self._apply_spread_zscore_skew(bid_price, ask_price, book, memory)
        bid_size, ask_size   = self._apply_toxic_flow(state, memory, bid_size, ask_size)
        bid_size, ask_size   = self._apply_jump_filter(book, memory, bid_size, ask_size)
        bid_size, ask_size   = self._apply_fill_rate_toxicity(state, memory, bid_size, ask_size)
        passive_orders, buy_cap, sell_cap = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit
        )
        probe_orders, buy_cap, sell_cap = self._probe_quotes(
            book, state, memory, position, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_orders)
        probe_t0_orders, buy_cap, sell_cap = self._probe_tick0(
            book, state, memory, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_t0_orders)
        momentum_orders, buy_cap, sell_cap = self._apply_momentum_follower(
            state, order_depth, memory, buy_cap, sell_cap,
        )
        taker_orders.extend(momentum_orders)
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
                "fair":     round(fair_value, 2),
                "buy_edge": round(buy_edge, 2),
                "sell_edge":round(sell_edge, 2),
                "bid_size": int(bid_size),
                "ask_size": int(ask_size),
                "zscore":   round(z, 4) if z is not None else None,
                "sigma":    round(sigma, 4),
                "flow_score": round(memory.get("_flow_score", 0.0), 3),
            },
        )
        return taker_orders + gap_orders + passive_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed"))  is not None: out["MidSmooth"]  = float(m)
        if (a := memory.get("_anchor_ema"))   is not None: out["AnchorEMA"]  = float(a)
        z = memory.get("zscore")
        if z is not None:
            out["Z"] = float(z)
        return out


class R3GuardedAnchorMMStrategy(MMFirstV4ComboStrategy):
    """Guarded Anchor MM: disables AR + takers when price trends away from anchor.

    Guard logic (_use_anchor):
      - near_anchor: |mid - anchor| <= near_band (default 0)
      - reverting:   price is between [min_dist, max_dist] from anchor AND
                     trending back toward it (dist × trend_ema <= -threshold)
      - wrong_way_inventory: inventory pushes in the wrong direction
      - Guard ON (use anchor) = (near_anchor OR reverting) AND NOT wrong_way
      - Guard OFF: set ar_gain=0, take_edges=∞  → pure passive MM only
    """

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        mid    = book.mid_price
        anchor = self.params.get("anchor_price")
        if mid is None or anchor is None:
            return super().compute_orders(state, book, order_depth, position, memory)
        use_anchor = self._use_anchor(float(mid), float(anchor), position, memory)
        memory["_guard_use_anchor"] = int(use_anchor)
        if use_anchor:
            return super().compute_orders(state, book, order_depth, position, memory)
        old_anchor   = self.params.get("anchor_price")
        old_ar       = self.params.get("ar_gain")
        old_take_lo  = self.params.get("take_edge_lo")
        old_take_hi  = self.params.get("take_edge_hi")
        try:
            self.params["anchor_price"] = None
            self.params["ar_gain"]      = 0.0
            self.params["take_edge_lo"] = 1_000_000.0
            self.params["take_edge_hi"] = 1_000_000.0
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = old_anchor
            self.params["ar_gain"]      = old_ar
            self.params["take_edge_lo"] = old_take_lo
            self.params["take_edge_hi"] = old_take_hi

    def _use_anchor(
        self,
        mid: float,
        anchor: float,
        position: int,
        memory: Dict[str, Any],
    ) -> bool:
        prev_mid = memory.get("_guard_prev_mid")
        memory["_guard_prev_mid"] = mid
        raw_trend = 0.0 if prev_mid is None else mid - float(prev_mid)
        alpha = float(self.params.get("guard_trend_alpha", 0.3))
        trend = float(memory.get("_guard_trend_ema", raw_trend))
        trend = alpha * raw_trend + (1.0 - alpha) * trend
        memory["_guard_trend_ema"] = trend
        dist = mid - anchor
        memory["_guard_dist"]  = dist
        memory["_guard_trend"] = trend
        near_band       = float(self.params.get("guard_near_band", 0.0))
        min_dist        = float(self.params.get("guard_min_dist", 0.0))
        max_dist        = float(self.params.get("guard_max_dist", 80.0))
        threshold       = float(self.params.get("guard_reversion_threshold", 0.0))
        inventory_dist  = float(self.params.get("guard_inventory_dist", 40.0))
        near_anchor = abs(dist) <= near_band
        reverting   = min_dist <= abs(dist) <= max_dist and (dist * trend) <= -threshold
        wrong_way   = (position > 0 and dist < -inventory_dist) or (
                       position < 0 and dist > inventory_dist)
        return (near_anchor or reverting) and not wrong_way

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (d := memory.get("_guard_dist"))       is not None: out["GuardDist"]  = float(d)
        if (t := memory.get("_guard_trend"))      is not None: out["GuardTrend"] = float(t)
        if (u := memory.get("_guard_use_anchor")) is not None: out["GuardOn"]    = float(u)
        return out


class DynamicAnchorMMStrategy(R3GuardedAnchorMMStrategy):
    """R3GuardedAnchorMMStrategy with anchor replaced by a slow EWMA of mid price.

    Instead of a fixed anchor_price=5250, the anchor tracks a very slow
    exponential moving average of the mid price. This lets the strategy
    adapt when VELVETFRUIT drifts over multi-day periods.

    Key param:
      anchor_slow_alpha  EWMA alpha for the slow anchor (default 0.0002,
                         half-life ≈ 3500 ticks ≈ 0.35 days).
                         Smaller = slower / more stable anchor.

    Set anchor_alpha=0.0 and anchor_drift_bound=0.0 in config so the parent's
    fast-drift logic is bypassed (the slow EMA is already smooth enough).
    """

    def _get_dynamic_anchor(self, mid: float, memory: Dict[str, Any]) -> float:
        alpha = float(self.params.get("anchor_slow_alpha", 0.0002))
        prev = memory.get("_dynamic_anchor")
        if prev is None:
            memory["_dynamic_anchor"] = float(mid)
            return float(mid)
        ema = (1.0 - alpha) * float(prev) + alpha * mid
        memory["_dynamic_anchor"] = ema
        return ema

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
            return super().compute_orders(state, book, order_depth, position, memory)
        anchor = self._get_dynamic_anchor(float(mid), memory)
        old_anchor = self.params.get("anchor_price")
        try:
            self.params["anchor_price"] = anchor
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = old_anchor

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (a := memory.get("_dynamic_anchor")) is not None:
            out["DynAnchor"] = float(a)
        return out


# ── prosperity/strategies/round_3/tibo/hydro_strat_v200.py ────────────────────────

class HydroMMV200(R3GuardedAnchorMMStrategy):
    pass

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'anchor_alpha': 0.02,
                   'anchor_drift_bound': 1.5,
                   'anchor_price': 10000.0,
                   'ar_gain': 0.2,
                   'ar_shift_source': 'mid_smooth',
                   'full_capacity_on_empty': True,
                   'guard_inventory_dist': 40.0,
                   'guard_max_dist': 80.0,
                   'guard_min_dist': 0.0,
                   'guard_near_band': 0.0,
                   'guard_reversion_threshold': 3.0,
                   'guard_trend_alpha': 0.45,
                   'inventory_aversion_gamma': 0.001,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'maker_size_base_pct': 0.15,
                   'passive_unwind_skew_ticks': 1,
                   'passive_unwind_trigger': 0.38,
                   'pct_kept_for_takers': 0.005,
                   'position_limit': 200,
                   'strategy': 'hydro_mm_v200',
                   'take_edge_hi': 0.8,
                   'take_edge_lo': 0.3,
                   'tighten_ticks': 1,
                   'toxic_size_frac': 0.68,
                   'toxic_threshold': 0.6,
                   'toxic_window': 8,
                   'ts_increment': 100,
                   'unwind_take_edge': 3.0}}

STRATEGY_CLASSES = {"hydro_mm_v200": HydroMMV200}

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
