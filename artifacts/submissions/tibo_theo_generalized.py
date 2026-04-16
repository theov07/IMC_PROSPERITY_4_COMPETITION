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


# ── prosperity/strategies/metal_winner/mm_first_v2.py ─────────────────────────────


class MMFirstStrategy(BaseStrategy):

    # ── helpers ──────────────────────────────────────────────────────────

    def _compute_quote_prices(
        self,
        book: BookSnapshot,
        inventory_ratio: float,
        mid_smooth: float,
    ) -> Tuple[Optional[int], Optional[int], str]:
        """Select L1/L2 passive prices + apply crossing prevention.

        L1 (default): penny-improve — post one tick inside the market.
        L2 (high inventory): join best on the inventory-increasing side.
          Long  → back off bid to best_bid (join), keep ask at best_ask-1.
          Short → back off ask to best_ask (join), keep bid at best_bid+1.

        Returns (bid_price, ask_price, level_label).
        """
        penny = int(self.params.get("penny_improve_ticks", 1))
        bid_price: Optional[int] = (book.best_bid + penny) if book.best_bid is not None else None
        ask_price: Optional[int] = (book.best_ask - penny) if book.best_ask is not None else None
        level = "L1"

        step_threshold = float(self.params.get("inv_step_threshold", 999.0))
        if inventory_ratio >= step_threshold:
            if book.best_bid is not None:
                bid_price = book.best_bid
            level = "L2"
        elif inventory_ratio <= -step_threshold:
            if book.best_ask is not None:
                ask_price = book.best_ask
            level = "L2"

        return bid_price, ask_price, level

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        """Rolling z-score of mid price.

        z = (mid - rolling_mean) / rolling_std  over the last zscore_window ticks.
        Returns None until the warm-up period completes (window // 4 samples),
        or when std ~ 0 (flat price series).

        Stored values (all accessible via memory):
          memory["zscore"]    — current z  (None if not ready)
          memory["_zs_mean"]  — rolling mean (for band overlay in dashboard)
          memory["_zs_std"]   — rolling std

        Params:
          zscore_window — rolling window size (default 50)
        """
        window = int(self.params.get("zscore_window", 50))
        buf: List[float] = memory.setdefault("_zscore_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]

        warmup = int(self.params.get("zscore_warmup", max(3, window // 4)))
        if len(buf) < warmup:
            memory["zscore"] = None
            return None

        n    = len(buf)
        mean = sum(buf) / n
        var  = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)  # sample variance
        std  = var ** 0.5

        if std < 1e-9:
            memory["zscore"] = None
            return None

        z = (mid - mean) / std
        memory["zscore"]   = z
        memory["_zs_mean"] = mean
        memory["_zs_std"]  = std
        return z

    def _zscore_size_factors(self, memory: Dict[str, Any]) -> Tuple[float, float]:
        """Return (bid_factor, ask_factor) multipliers based on the current z-score.

        Neutral  (|z| <= threshold):  both 1.0 — no adjustment.
        z >  threshold (price high):  ask_factor > 1, bid_factor < 1  (lean short).
        z < -threshold (price low):   bid_factor > 1, ask_factor < 1  (lean long).

        Scale ramps linearly with excess z beyond the threshold, capped at zscore_max_scale.

        Params:
          zscore_threshold  — |z| must exceed this to trigger scaling (default 1.0)
          zscore_size_scale — slope of scale vs excess z (default 0.5)
          zscore_max_scale  — cap on the multiplier (default 3.0)
        """
        z = memory.get("zscore")
        if z is None:
            return 1.0, 1.0

        threshold  = float(self.params.get("zscore_threshold",  1.0))
        size_scale = float(self.params.get("zscore_size_scale", 0.5))
        max_scale  = float(self.params.get("zscore_max_scale",  3.0))

        excess = max(0.0, abs(z) - threshold)
        scale  = min(max_scale, 1.0 + size_scale * excess)

        if z > threshold:
            return 1.0 / scale, scale      # lean short: boost ask, shrink bid
        if z < -threshold:
            return scale, 1.0 / scale      # lean long:  boost bid, shrink ask
        return 1.0, 1.0

    def _compute_sizes(self, position: int, limit: int) -> Tuple[float, float]:
        """Inventory-adaptive bid/ask sizes.

        bid_size shrinks when long (we're already holding enough).
        ask_size shrinks when short (we're already selling enough).

        Returns (bid_size, ask_size) as floats — callers cast to int as needed.
        """
        base = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base * (1.0 - position / limit)
        ask_size = base * (1.0 + position / limit)
        return bid_size, ask_size

    def _fire_takers(
        self,
        order_depth: OrderDepth,
        mid_smooth: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        """Emit aggressive taker orders when price vs fair-value edge is sufficient.

        Two OR-conditions trigger a taker:
          1. mid_smooth edge:    ask <= mid_smooth - take_edge  (buy)
                                 bid >= mid_smooth + take_edge  (sell)
          2. absolute threshold: ask <= taker_buy_threshold     (buy, optional)
                                 bid >= taker_sell_threshold    (sell, optional)

        Size is capped at 30% of the inventory-adaptive quote size.
        Returns (orders, remaining_buy_cap, remaining_sell_cap, buy_px_set, sell_px_set).
        """
        take_edge            = float(self.params.get("take_edge", 1.0))
        taker_buy_threshold  = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")
        taker_size_pct       = float(self.params.get("taker_size_pct", 0.3))

        orders: List[Order] = []
        taker_buy_px:  Set[int] = set()
        taker_sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= mid_smooth - take_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, int(bid_size * taker_size_pct))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                taker_buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume     = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= mid_smooth + take_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, int(ask_size * taker_size_pct))
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
        """Re-anchor passive prices and optionally sweep a thin level when the gap is large.

        Step 1 — Re-anchor (absorbs the old _reanchor_passive):
          Build the effective remaining book by filtering out levels already swept
          by this tick's taker orders.  Passive prices are always updated to the
          first remaining level ±1; if a side is completely cleared, the passive
          is anchored far from the last known best (advantageous pricing for us).

        Step 2 — Gap check on effective book:
          If effective L1 is thin AND gap to effective L2 is ≥ gap_trigger_min,
          sweep L1 aggressively and re-anchor the passive to L2 ±1.

        Z-score gate: suppress gap sweeps when price is already stretched against
        the sweep direction.

        Returns (orders, buy_cap, sell_cap, bid_price, ask_price).
        """
        gap_min     = float(self.params.get("gap_trigger_min", 10))
        shift       = int(self.params.get("OB_cleared_shift", 85))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

        z        = memory.get("zscore")
        gap_gate = float(self.params.get("zscore_gap_gate", self.params.get("zscore_threshold", 1.0)))
        bid_z_ok = z is None or z >= -gap_gate   # ok to sell unless price already stretched low
        ask_z_ok = z is None or z <=  gap_gate   # ok to buy  unless price already stretched high

        orders: List[Order] = []
        memory["_gap_buy_px"]  = []
        memory["_gap_sell_px"] = []

        # Track last known market best from the original book (before our actions)
        all_bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        all_asks = sorted(order_depth.sell_orders.keys())
        if all_bids:
            memory["_last_best_bid"] = all_bids[0]
        if all_asks:
            memory["_last_best_ask"] = all_asks[0]
        last_best_bid = memory.get("_last_best_bid")
        last_best_ask = memory.get("_last_best_ask")

        # Effective remaining book: exclude levels swept by this tick's takers
        remaining_bids = [p for p in all_bids if p not in taker_sell_px]
        remaining_asks = [p for p in all_asks if p not in taker_buy_px]

        # Which levels gap exploit fully clears (tracked so re-anchor uses the true final book)
        gap_swept_bids: Set[int] = set()
        gap_swept_asks: Set[int] = set()

        # ── GAP CHECK ON EFFECTIVE (POST-TAKER) BOOK ──────────────────
        if gap_min > 0 and gap_max_vol > 0:

            # Bid side: sell into thin effective L1 when gap to L2 is large
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
                    if qty >= bid1_vol:      # fully cleared → exclude from final remaining
                        gap_swept_bids.add(bid1)

            # Ask side: buy into thin effective L1 when gap to L2 is large
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
                    if qty >= ask1_vol:      # fully cleared → exclude from final remaining
                        gap_swept_asks.add(ask1)

        # ── RE-ANCHOR: post-taker AND post-gap effective book ──────────
        # Done last so it reflects all sweeps this tick.  When a side is fully
        # empty we post `shift` ticks away from the last known market price —
        # an advantageous quote that captures a wide spread if anyone hits it.
        final_remaining_bids = [p for p in remaining_bids if p not in gap_swept_bids]
        final_remaining_asks = [p for p in remaining_asks if p not in gap_swept_asks]

        if final_remaining_asks:
            ask_price = final_remaining_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + shift    # empty ask side: post far above

        if final_remaining_bids:
            bid_price = final_remaining_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - shift    # empty bid side: post far below

        return orders, buy_cap, sell_cap, bid_price, ask_price

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
        """Size and emit passive bid/ask orders with a hard inventory stop.

        Hard stop: when |position| >= limit * (1 - pct_kept_for_takers), suppress
        the inventory-increasing side to preserve capacity for taker unwinds.

        Returns (orders, remaining_buy_cap, remaining_sell_cap) so this function
        can be called in any order relative to _fire_takers / _gap_exploit without
        risking a position-limit breach — each caller chains the returned caps into
        the next call, exactly like _fire_takers and _gap_exploit already do.
        """
        quote_buy  = min(buy_cap,  int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))

        inv_abs = abs(position) / float(limit) if limit else 0.0
        hard_stop_thr = 1.0 - float(self.params.get("pct_kept_for_takers", 0.2))
        if inv_abs >= hard_stop_thr:
            if position > 0:
                quote_buy  = 0
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
        """Detect and log taker fills by comparing own_trades against last tick's taker prices.

        Gap-exploit fills are identified by cross-referencing against the gap prices
        recorded by _gap_exploit on the previous tick (T-1 prices fill as own_trades on T).
        """
        prev_taker_buy_px  = set(memory.get("_taker_buy_px",  []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        prev_gap_buy_px    = set(memory.get("_gap_buy_px_prev",  []))
        prev_gap_sell_px   = set(memory.get("_gap_sell_px_prev", []))

        memory["_taker_buy_px"]     = list(this_taker_buy_px)
        memory["_taker_sell_px"]    = list(this_taker_sell_px)
        memory["_gap_buy_px_prev"]  = list(memory.get("_gap_buy_px",  []))
        memory["_gap_sell_px_prev"] = list(memory.get("_gap_sell_px", []))

        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY",  trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                is_gap = (
                    (side == "BUY"  and trade.price in prev_gap_buy_px) or
                    (side == "SELL" and trade.price in prev_gap_sell_px)
                )
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                )

    # ── order construction ───────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0   # no price reference at all yet — skip tick
            # fall through with stale mid so passive anchoring still runs

        raw_mid = book.mid_price
        if raw_mid is None and book.best_bid is not None:
            raw_mid = float(book.best_bid)
        if raw_mid is None and book.best_ask is not None:
            raw_mid = float(book.best_ask)
        mid = raw_mid if raw_mid is not None else memory["_last_mid"]
        if raw_mid is not None:
            memory["_last_mid"] = raw_mid

        mid_smooth = self._smooth_mid(mid, memory)
        self._compute_zscore(mid, memory)  # result stored in memory["zscore"]

        limit     = self.position_limit()
        inventory_ratio = position / float(limit) if limit else 0.0

        # ── QUOTE LEVEL SELECTION ──────────────────────────────────────
        bid_price, ask_price, _ = self._compute_quote_prices(book, inventory_ratio, mid_smooth)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── DYNAMIC SIZING / Ideal order size ─────────────────────────────────────────────
        bid_size, ask_size = self._compute_sizes(position, limit)

        # ── Z-SCORE SIZE TILT ─────────────────────────────────────────
        bid_factor, ask_factor = self._zscore_size_factors(memory)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)

        # ── TAKER ORDERS ───────────────────────────────────────────────
        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._fire_takers(
            order_depth, mid_smooth, bid_size, ask_size, buy_cap, sell_cap
        )

        # ── GAP EXPLOIT + PASSIVE RE-ANCHOR ───────────────────────────
        # _gap_exploit absorbs the old _reanchor_passive: it builds the effective
        # remaining book (excluding taker-swept levels), always re-anchors passive
        # prices, then optionally sweeps a thin level if the gap is large enough.
        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap,
            taker_buy_px, taker_sell_px,
        )

        # ── PASSIVE QUOTING ────────────────────────────────────────────
        passive_orders, buy_cap, sell_cap = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit
        )

        # ── LOGGING ────────────────────────────────────────────────────
        self._log_taker_fills(state, memory, taker_buy_px, taker_sell_px)
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position":   position,
                "mid_smooth": round(mid_smooth, 2),
                "bid_size":   int(bid_size),
                "ask_size":   int(ask_size),
            },
        )

        return taker_orders + gap_orders + passive_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        return out


# ── Regression base (from regression_mm_v5) ─────────────────────────────────────

class Round1RegressionMMV5Strategy(BaseStrategy):
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

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        return [], 0


# ── TestTheo Strategy: Leo fusion buy logic + v34 trim system ────────────────────

def _ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


class TestTheoStrategy(Round1RegressionMMV5Strategy):
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

        mid = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        trend_ticks = stats["trend_ticks"]
        residual_z = stats["residual_z"]
        fv = stats["fair_value"]

        # ── Short-term EMA for stretch detection ──
        short_alpha = float(self.params.get("short_alpha", 0.15))
        short_ema = _ewma(memory.get("short_ema"), mid, short_alpha)
        memory["short_ema"] = short_ema
        stretch = mid - short_ema

        base_target = self._inventory_target(state=state, stats=stats, position=position)

        # ── Trend detection: direction-agnostic ──
        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        bear_threshold = float(self.params.get("bear_threshold", -bull_threshold))
        bullish = trend_ticks > bull_threshold
        bearish = trend_ticks < bear_threshold
        trending = bullish or bearish
        trend_sign = 1 if bullish else (-1 if bearish else 0)

        # ── Build phase: accumulate in trend direction ──
        fastfill_target = int(self.params.get("fastfill_target", self.position_limit()))
        fastfill_end_ts = int(self.params.get("fastfill_end_ts", 15000))
        limit = self.position_limit()

        if bullish:
            build_phase = position < fastfill_target or int(state.timestamp) <= fastfill_end_ts
            inv_target = max(base_target, fastfill_target) if build_phase else base_target
        elif bearish:
            build_phase = position > -fastfill_target or int(state.timestamp) <= fastfill_end_ts
            inv_target = min(base_target, -fastfill_target) if build_phase else base_target
        else:
            build_phase = False
            inv_target = base_target

        # ── Trim parameters ──
        trim_start_position = int(self.params.get("trim_start_position", 80))
        trim_floor_position = int(self.params.get("trim_floor_position", 78))
        trim_sell_size = int(self.params.get("trim_sell_size", 1))
        trim_cooldown_ticks = int(self.params.get("trim_cooldown_ticks", 30))
        trim_stretch_threshold = float(self.params.get("trim_stretch_threshold", 2.0))
        trim_take_stretch = float(self.params.get("trim_take_stretch", 3.5))
        trim_take_sell_size = int(self.params.get("trim_take_sell_size", 2))
        rebuy_block_ticks = int(self.params.get("rebuy_block_ticks", 8))
        trim_take_enabled = bool(self.params.get("trim_take_enabled", False))
        trim_ask_mid_offset = float(self.params.get("trim_ask_mid_offset", 5.0))

        last_trim_ts = int(memory.get("last_trim_ts", -10**9))
        rebuy_block_until = int(memory.get("rebuy_block_until", -10**9))
        rebuy_blocked = trending and int(state.timestamp) < rebuy_block_until

        # ── Quote prices: direction-adaptive spreads ──
        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))

        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
        elif bearish:
            raw_bid = round(fv - ask_spread_bull)
            raw_ask = round(fv + bid_spread_bull)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)

        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Signal-adaptive tick adjustments ──
        bid_extra = 0
        ask_relax = 0
        strong = float(self.params.get("strong_trend_ticks", 1.1))
        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        cheap_z = float(self.params.get("cheap_residual_z", 0.9))
        rich_z = float(self.params.get("rich_residual_z", 1.0))

        if trend_ticks >= strong:
            bid_extra += 1
        if trend_ticks >= very_strong:
            bid_extra += 1
        if trend_ticks <= -strong:
            ask_relax -= 1
        if trend_ticks <= -very_strong:
            ask_relax -= 1
        if residual_z <= -cheap_z:
            bid_extra += 1
        if residual_z >= rich_z:
            ask_relax -= 1

        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        max_ask_relax = int(self.params.get("max_ask_relax_ticks", 2))
        bid_extra = max(-max_bid_extra, min(max_bid_extra, bid_extra))
        ask_relax = max(-max_ask_relax, min(max_ask_relax, ask_relax))

        bid_price = min(book.best_ask - 1, bid_price + bid_extra)
        ask_price = max(book.best_bid + 1, ask_price + ask_relax)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Build phase: penny-improve in trend direction ──
        build_bid_offset = int(self.params.get("build_bid_offset", 1))
        if build_phase and bullish:
            bid_price = book.best_ask - build_bid_offset
        elif build_phase and bearish:
            ask_price = book.best_bid + build_bid_offset

        # ── Taker edges ──
        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -8.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull", 6.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 10.0))
        fastfill_buy_edge_boost = float(self.params.get("fastfill_buy_edge_boost", 0.0))
        build_block_counter_edge = float(self.params.get("build_block_counter_edge", 1_000_000.0))

        if bullish:
            buy_edge = take_buy_edge_bull
            sell_edge = take_sell_edge_bull
            if build_phase:
                buy_edge -= fastfill_buy_edge_boost
                sell_edge = build_block_counter_edge
            elif residual_z >= rich_z:
                buy_edge = take_buy_edge_neut
        elif bearish:
            sell_edge = take_buy_edge_bull
            buy_edge = take_sell_edge_bull
            if build_phase:
                sell_edge -= fastfill_buy_edge_boost
                buy_edge = build_block_counter_edge
            elif residual_z <= -cheap_z:
                sell_edge = take_buy_edge_neut
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut

        # ── Unwind pressure when offside ──
        if (not bullish) and position > inv_target:
            pressure = min(1.0, (position - inv_target) / max(1.0, float(limit)))
            sell_edge = sell_edge - unwind_take_edge * pressure
        if (not bearish) and position < inv_target:
            pressure = min(1.0, (inv_target - position) / max(1.0, float(limit)))
            buy_edge = buy_edge - unwind_take_edge * pressure

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── Trim detection (direction-agnostic) ──
        trim_quote_mode = False
        if bullish and not build_phase and position >= trim_start_position and stretch >= trim_stretch_threshold:
            trim_quote_mode = True
        elif bearish and not build_phase and position <= -trim_start_position and stretch <= -trim_stretch_threshold:
            trim_quote_mode = True

        trim_take_mode = False
        if trim_take_enabled:
            if bullish and not build_phase and position >= trim_start_position and stretch >= trim_take_stretch:
                trim_take_mode = True
            elif bearish and not build_phase and position <= -trim_start_position and stretch <= -trim_take_stretch:
                trim_take_mode = True

        # ── Taker orders (buy side) ──
        pending_buy = 0
        first_take_ask: int | None = None
        deep_take_blocked = False
        deep_take_guard_end_ts = int(self.params.get("fastfill_deep_take_guard_end_ts", 0))
        deep_take_max_gap = int(self.params.get("fastfill_deep_take_max_gap_ticks", 999999))
        deep_take_guard = build_phase and bullish and int(state.timestamp) <= deep_take_guard_end_ts

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0:
                break
            room = max(0, inv_target - position - pending_buy)
            if build_phase and bullish and room <= 0:
                break
            if first_take_ask is None:
                first_take_ask = ask_p
            elif deep_take_guard and ask_p - first_take_ask > deep_take_max_gap:
                deep_take_blocked = True
                break
            qty = min(-order_depth.sell_orders[ask_p], buy_cap, room if (build_phase and bullish) else buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            buy_cap -= qty
            pending_buy += qty

        # ── Taker orders (sell side) ──
        pending_sell = 0
        if not (build_phase and bullish) and not trim_quote_mode:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fv + sell_edge or sell_cap <= 0:
                    break
                room_sell = max(0, position + pending_sell - pending_buy - inv_target) if (build_phase and bearish) else sell_cap
                qty = min(order_depth.buy_orders[bid_p], sell_cap, room_sell)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap -= qty
                pending_sell += qty

        # ── Trim take (configurable, disabled by default) ──
        trim_take_qty = 0
        if trim_take_mode:
            if position > 0:
                trim_take_qty = min(sell_cap, max(0, position - trim_floor_position), max(1, trim_take_sell_size))
                if trim_take_qty > 0:
                    orders.append(Order(self.product, book.best_bid, -trim_take_qty))
                    sell_cap -= trim_take_qty
                    pending_sell += trim_take_qty
            elif position < 0:
                trim_take_qty = min(buy_cap, max(0, -position - trim_floor_position), max(1, trim_take_sell_size))
                if trim_take_qty > 0:
                    orders.append(Order(self.product, book.best_ask, trim_take_qty))
                    buy_cap -= trim_take_qty
                    pending_buy += trim_take_qty
            if trim_take_qty > 0:
                memory["last_trim_ts"] = int(state.timestamp)
                memory["rebuy_block_until"] = int(state.timestamp) + rebuy_block_ticks * 100
                rebuy_blocked = True

        # ── Passive sizing ──
        buy_size, sell_size = self._size_from_target(
            position=position + pending_buy - pending_sell,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        # ── Build phase: suppress counter-trend passive, boost trend passive ──
        if build_phase and bullish:
            sell_size = 0
            buy_size = max(buy_size, min(buy_cap, int(self.params.get("fastfill_min_passive_buy", 20))))
            buy_size = min(buy_size, max(0, inv_target - position - pending_buy))
        elif build_phase and bearish:
            buy_size = 0
            sell_size = max(sell_size, min(sell_cap, int(self.params.get("fastfill_min_passive_buy", 20))))
            sell_size = min(sell_size, max(0, -inv_target + position - pending_sell))

        # ── Trim quote mode: passive trim inside spread ──
        if trim_quote_mode and not build_phase:
            if position > 0:
                allowed_sell = max(0, position - trim_floor_position)
                sell_size = min(sell_cap, allowed_sell, max(1, trim_sell_size))
                trim_ask = max(book.best_bid + 1, book.best_ask - 1, round(mid + trim_ask_mid_offset))
                ask_price = trim_ask
            elif position < 0:
                allowed_buy = max(0, -position - trim_floor_position)
                buy_size = min(buy_cap, allowed_buy, max(1, trim_sell_size))
                trim_bid = min(book.best_ask - 1, book.best_bid + 1, round(mid - trim_ask_mid_offset))
                bid_price = trim_bid

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["inv_target"] = inv_target
        memory["bullish"] = int(bullish)
        memory["bearish"] = int(bearish)
        memory["build_phase"] = int(build_phase)
        memory["trim_quote_mode"] = int(trim_quote_mode)
        memory["trim_take_mode"] = int(trim_take_mode)
        memory["rebuy_blocked"] = int(rebuy_blocked)
        memory["stretch"] = stretch

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "reg_slope": round(stats["slope"], 4),
                "reg_r2": round(stats["r2"], 3),
                "trend_ticks": round(trend_ticks, 2),
                "residual_z": round(residual_z, 2),
                "block_count": int(stats["block_count"]),
                "fair_value": round(fv, 2),
                "inv_target": inv_target,
                "bullish": int(bullish),
                "bearish": int(bearish),
                "build_phase": int(build_phase),
                "buy_size": buy_size,
                "sell_size": sell_size,
                "stretch": round(stretch, 2),
                "trim_quote_mode": int(trim_quote_mode),
                "trim_take_mode": int(trim_take_mode),
                "trim_take_qty": trim_take_qty,
                "rebuy_blocked": int(rebuy_blocked),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        stats = memory.get("regression_stats")
        if not stats:
            return {}
        out = {
            "reg_fitted_now": float(stats["fitted_now"]),
            "reg_forecast": float(stats["forecast"]),
            "reg_fair_value": float(stats["fair_value"]),
        }
        if memory.get("short_ema") is not None:
            out["short_ema"] = memory["short_ema"]
        return out


# ── Config ────────────────────────────────────────────────────────────────────

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {
    'ASH_COATED_OSMIUM': {'OB_cleared_shift': 85,
                       'gap_trigger_confirm_ticks': 1,
                       'gap_trigger_max_vol_pct': 0.1,
                       'gap_trigger_min': 10,
                       'last_ts_value': 99900,
                       'log_flush_ts': 1000,
                       'maker_size': 20,
                       'maker_size_base_pct': 0.5,
                       'mid_smooth_half_life': 10,
                       'mid_smooth_window': 50,
                       'pct_kept_for_takers': 0.1,
                       'position_limit': 80,
                       'quote_trace_enabled': True,
                       'strategy': 'mm_first_v2',
                       'take_edge': 0.6,
                       'taker_buy_threshold': 9990,
                       'taker_sell_threshold': 10025,
                       'tighten_ticks': 1,
                       'ts_increment': 100,
                       'zscore_gap_gate': 1.5,
                       'zscore_max_scale': 5.0,
                       'zscore_size_scale': 0.5,
                       'zscore_threshold': 1,
                       'zscore_window': 50,
                       'penny_improve_ticks': 1,
                       'inv_step_threshold': 999.0,
                       'taker_size_pct': 0.3,
                       'zscore_warmup': 12,
                       },
    'INTARIAN_PEPPER_ROOT': {
        'aggravate_cut': 0.04,
        'ask_spread_bull': 9.0,
        'bid_spread_bull': 1.0,
        'block_size': 200,
        'bootstrap_confidence': 0.55,
        'bull_threshold': 1.0,
        'cheap_buy_boost_per_z': 0.18,
        'cheap_residual_z': 0.9,
        'fastfill_buy_edge_boost': 0.0,
        'fastfill_deep_take_guard_end_ts': 1000,
        'fastfill_deep_take_max_gap_ticks': 1,
        'fastfill_end_ts': 12000,
        'fastfill_min_passive_buy': 10,
        'fastfill_target': 80,
        'last_ts_value': 999900,
        'log_flush_ts': 1000,
        'maker_size': 80,
        'max_ask_relax_ticks': 2,
        'max_bid_extra_ticks': 2,
        'min_completed_blocks': 5,
        'neut_spread_ask': 5.0,
        'neut_spread_bid': 2.0,
        'one_sided_target_gap': 24,
        'position_limit': 80,
        'reg_horizon': 25,
        'reg_r2_cap': 0.98,
        'reg_r2_floor': 0.85,
        'reg_residual_reversion': 0.25,
        'reg_rmse_floor': 1.0,
        'resid_inv_per_z': 14.0,
        'rich_residual_z': 1.0,
        'rich_sell_boost_per_z': 0.14,
        'seed_slope': 0.1015,
        'startup_end_ts': 30000,
        'startup_target': 80,
        'strategy': 'test_theo',
        'strong_trend_ticks': 0.9,
        'take_buy_edge_bull': -8.0,
        'take_buy_edge_neut': 2.0,
        'take_sell_edge_bull': 6.0,
        'take_sell_edge_neut': 2.0,
        'target_gap_scale': 26.0,
        'tighten_ticks': 1,
        'trend_buy_boost_per_tick': 0.24,
        'trend_inv_per_tick': 16.0,
        'trend_inventory_cap': 80,
        'trend_sell_boost_per_tick': 0.2,
        'ts_increment': 100,
        'unwind_take_edge': 10.0,
        'very_strong_trend_ticks': 1.6,
        'short_alpha': 0.15,
        'trim_start_position': 80,
        'trim_floor_position': 79,
        'trim_stretch_threshold': 1.5,
        'trim_sell_size': 1,
        'trim_cooldown_ticks': 20,
        'trim_take_stretch': 999.0,
        'trim_take_sell_size': 1,
        'rebuy_block_ticks': 3,
        'bear_threshold': -1.0,
        'build_bid_offset': 1,
        'build_block_counter_edge': 1000000.0,
        'trim_take_enabled': False,
        'trim_ask_mid_offset': 5.0,
    },
}

STRATEGY_CLASSES = {"mm_first_v2": MMFirstStrategy, "test_theo": TestTheoStrategy}

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
