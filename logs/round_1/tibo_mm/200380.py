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
        bid_price: Optional[int] = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price: Optional[int] = (book.best_ask - 1) if book.best_ask is not None else None
        level = "L1"

        # if inventory_ratio >= step_threshold:
        #     # Long: ease off buying, stay aggressive on selling
        #     if book.best_bid is not None:
        #         bid_price = book.best_bid       # join, no improvement
        #     level = "L2"
        # elif inventory_ratio <= -step_threshold:
        #     # Short: ease off selling, stay aggressive on buying
        #     if book.best_ask is not None:
        #         ask_price = book.best_ask       # join, no improvement
        #     level = "L2"

        # Crossing prevention
        # if bid_price is not None and book.best_ask is not None:
        #     bid_price = min(bid_price, mid_smooth - 1)
        # if ask_price is not None and book.best_bid is not None:
        #     ask_price = max(ask_price, mid_smooth + 1)
        # if bid_price is not None and ask_price is not None and ask_price <= bid_price:
        #     ask_price = bid_price + 1

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

        if len(buf) < max(3, window // 4):
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

        orders: List[Order] = []
        taker_buy_px:  Set[int] = set()
        taker_sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= mid_smooth - take_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, int(bid_size * 0.3)) # TODO could set the threshold with zscore
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
            qty = min(volume, sell_cap, int(ask_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                taker_sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px

    def _reanchor_passive(
        self,
        order_depth: OrderDepth,
        bid_price: Optional[int],
        ask_price: Optional[int],
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[Optional[int], Optional[int]]:
        """Re-anchor passive prices after taker sweeps.

        The pre-computed passive price is stale once a taker sweeps that level.
        Re-anchor to the first level NOT swept by this tick's taker orders.
        """
        if taker_buy_px:
            new_best_ask = next(
                (p for p in sorted(order_depth.sell_orders) if p not in taker_buy_px),
                None,
            )
            if new_best_ask is not None:
                ask_price = new_best_ask - 1
            # else: all ask levels cleared — gap exploit will handle it

        if taker_sell_px:
            new_best_bid = next(
                (p for p in sorted(order_depth.buy_orders, reverse=True) if p not in taker_sell_px),
                None,
            )
            if new_best_bid is not None:
                bid_price = new_best_bid + 1
            # else: all bid levels cleared — gap exploit will handle it

        return bid_price, ask_price

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
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        """Sweep a thin L1 when the gap to L2 is large.

        After clearing L1, normal passive quoting re-enters just above the new best,
        capturing the gap spread from any participant who then hits our quote.

        Mitigation: gap_trigger_confirm_ticks — only fire after the condition has
        held for N consecutive ticks, filtering transient thin levels.

        Also handles an empty book by anchoring passives far from last known best.

        Returns (orders, buy_cap, sell_cap, bid_price, ask_price).
        """
        gap_min     = float(self.params.get("gap_trigger_min", 10))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

        # Z-score gate: suppress gap exploit when price is already stretched
        # against the direction of the sweep.
        #   Bid-side = SELL → don't sell when z already strongly negative
        #   Ask-side = BUY  → don't buy  when z already strongly positive
        # z=None (warm-up) → no gate, allow through.
        z         = memory.get("zscore")
        gap_gate  = float(self.params.get("zscore_gap_gate", self.params.get("zscore_threshold", 1.0)))
        bid_z_ok  = z is None or z >= -gap_gate   # ok to sell unless price already stretched low
        ask_z_ok  = z is None or z <=  gap_gate   # ok to buy  unless price already stretched high

        orders: List[Order] = []

        if not (gap_min > 0 and gap_max_vol > 0):
            return orders, buy_cap, sell_cap, bid_price, ask_price

        # Track last known best bid/ask for empty-book anchoring
        bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        asks = sorted(order_depth.sell_orders.keys())
        if bids:
            memory["_last_best_bid"] = bids[0]
        if asks:
            memory["_last_best_ask"] = asks[0]
        last_best_bid = memory.get("_last_best_bid")
        last_best_ask = memory.get("_last_best_ask")

        # Bid side: sell into thin best bid when gap to L2 is large
        bid_gap_ok = False
        bid1 = bid2 = bid1_vol = None
        if len(bids) >= 2:
            bid1, bid2 = bids[0], bids[1]
            bid1_vol = order_depth.buy_orders[bid1]
            bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol
        # 1-level case: no L2 to measure gap against → skip aggressive clearing
        bid_streak = memory.get("_gap_bid_streak", 0)
        bid_streak = bid_streak + 1 if bid_gap_ok else 0
        memory["_gap_bid_streak"] = bid_streak
        if bid_streak >= gap_confirm and bid_gap_ok and sell_cap > 0 and bid_z_ok:
            qty = min(bid1_vol, sell_cap, int(ask_size))
            if qty > 0:
                orders.append(Order(self.product, bid1, -qty))
                sell_cap -= qty
                bid_price = (bid2 + 1) if bid2 is not None else (bid1 - int(gap_min))
        elif len(bids) == 0 and last_best_bid is not None:
            bid_price = last_best_bid - int(gap_min)

        # Ask side: buy into thin best ask when gap to L2 is large
        ask_gap_ok = False
        ask1 = ask2 = ask1_vol = None
        if len(asks) >= 2:
            ask1, ask2 = asks[0], asks[1]
            ask1_vol = -order_depth.sell_orders[ask1]
            ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol
        # 1-level case: no L2 to measure gap against → skip aggressive clearing
        ask_streak = memory.get("_gap_ask_streak", 0)
        ask_streak = ask_streak + 1 if ask_gap_ok else 0
        memory["_gap_ask_streak"] = ask_streak
        if ask_streak >= gap_confirm and ask_gap_ok and buy_cap > 0 and ask_z_ok:
            qty = min(ask1_vol, buy_cap, int(bid_size))
            if qty > 0:
                orders.append(Order(self.product, ask1, qty))
                buy_cap -= qty
                ask_price = (ask2 - 1) if ask2 is not None else (ask1 + int(gap_min))
        elif len(asks) == 0 and last_best_ask is not None:
            ask_price = last_best_ask + int(gap_min)

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
    ) -> List[Order]:
        """Size and emit passive bid/ask orders with a hard inventory stop.

        Hard stop: when |position| >= limit * (1 - pct_kept_for_takers), suppress
        the inventory-increasing side to preserve capacity for taker unwinds.
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
        return orders

    def _log_taker_fills(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        this_taker_buy_px: Set[int],
        this_taker_sell_px: Set[int],
    ) -> None:
        """Detect and log taker fills by comparing own_trades against last tick's taker prices."""
        prev_taker_buy_px  = set(memory.get("_taker_buy_px",  []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        memory["_taker_buy_px"]  = list(this_taker_buy_px)
        memory["_taker_sell_px"] = list(this_taker_sell_px)

        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY",  trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
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

        # ── GAP EXPLOIT TAKERS ─────────────────────────────────────────
        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap
        )

        # ── TAKER PASSIVE RE-ANCHOR ────────────────────────────────────
        bid_price, ask_price = self._reanchor_passive(
            order_depth, bid_price, ask_price, taker_buy_px, taker_sell_px
        )
        
        # ── PASSIVE QUOTING ────────────────────────────────────────────
        passive_orders = self._passive_quotes(
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

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'ASH_COATED_OSMIUM': {'gap_trigger_confirm_ticks': 1,
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
                       'take_edge': 0.5,
                       'taker_buy_threshold': 9990,
                       'taker_sell_threshold': 10025,
                       'tighten_ticks': 1,
                       'ts_increment': 100,
                       'zscore_gap_gate': 1.5,
                       'zscore_max_scale': 5.0,
                       'zscore_size_scale': 0.5,
                       'zscore_threshold': 1,
                       'zscore_window': 50}}

STRATEGY_CLASSES = {"mm_first_v2": MMFirstStrategy}

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