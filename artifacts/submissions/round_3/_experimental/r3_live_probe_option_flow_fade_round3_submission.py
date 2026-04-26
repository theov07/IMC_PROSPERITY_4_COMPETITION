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


# ── prosperity/strategies/round_3/option_live_probe_mm.py ─────────────────────────

class OptionLiveProbeMMStrategy(BaseStrategy):
    """Diagnostic option probe for IMC live-only alpha."""

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

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        gap_orders, buy_cap, sell_cap = self._gap_sweep(order_depth, memory, buy_cap, sell_cap)
        orders.extend(gap_orders)

        flow_orders, buy_cap, sell_cap = self._flow_probe(
            state, order_depth, memory, buy_cap, sell_cap
        )
        orders.extend(flow_orders)

        far_orders, buy_cap, sell_cap = self._far_probes(
            state, book, memory, buy_cap, sell_cap
        )
        orders.extend(far_orders)

        memory["_prev_best_bid"] = int(book.best_bid)
        memory["_prev_best_ask"] = int(book.best_ask)
        memory["_last_position"] = int(position)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=book.best_bid,
            ask_price=book.best_ask,
            extras={
                "position": int(position),
                "gap_bid_streak": int(memory.get("_gap_bid_streak", 0)),
                "gap_ask_streak": int(memory.get("_gap_ask_streak", 0)),
                "flow_score": round(float(memory.get("_flow_score", 0.0)), 3),
                "far_probe": int(bool(far_orders)),
                "gap_sweep": int(bool(gap_orders)),
                "flow_probe": int(bool(flow_orders)),
            },
        )
        return orders, 0

    def _far_probes(
        self,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        distances = self.params.get("far_probe_distances") or []
        if not distances:
            return [], buy_cap, sell_cap

        interval_ticks = int(self.params.get("far_probe_interval_ticks", 200))
        ts_increment = int(self.params.get("ts_increment", 100))
        now = int(state.timestamp)
        last_ts = int(memory.get("_last_far_probe_ts", -10**12))
        if now - last_ts < interval_ticks * ts_increment:
            return [], buy_cap, sell_cap

        qty = max(1, int(self.params.get("far_probe_qty", 1)))
        orders: List[Order] = []
        for dist in distances:
            d = int(dist)
            if d <= 0:
                continue
            if buy_cap > 0:
                bid_px = max(1, int(book.best_bid) - d)
                q = min(qty, buy_cap)
                orders.append(Order(self.product, bid_px, q))
                buy_cap -= q
                memory["_last_far_bid"] = bid_px
            if sell_cap > 0:
                ask_px = int(book.best_ask) + d
                q = min(qty, sell_cap)
                orders.append(Order(self.product, ask_px, -q))
                sell_cap -= q
                memory["_last_far_ask"] = ask_px

        if orders:
            memory["_last_far_probe_ts"] = now
            memory["_far_probe_count"] = int(memory.get("_far_probe_count", 0)) + 1
        return orders, buy_cap, sell_cap

    def _gap_sweep(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        gap_min = int(self.params.get("gap_sweep_min", 0))
        if gap_min <= 0:
            return [], buy_cap, sell_cap

        max_l1 = int(self.params.get("gap_sweep_max_l1_qty", 6))
        confirm = max(1, int(self.params.get("gap_sweep_confirm_ticks", 1)))
        size = max(1, int(self.params.get("gap_sweep_size", 1)))
        orders: List[Order] = []

        bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        asks = sorted(order_depth.sell_orders.keys())

        bid_ok = False
        if len(bids) >= 2:
            bid1, bid2 = int(bids[0]), int(bids[1])
            bid1_qty = int(order_depth.buy_orders[bid1])
            bid_ok = (bid1 - bid2) >= gap_min and bid1_qty <= max_l1
        bid_streak = int(memory.get("_gap_bid_streak", 0))
        bid_streak = bid_streak + 1 if bid_ok else 0
        memory["_gap_bid_streak"] = bid_streak

        ask_ok = False
        if len(asks) >= 2:
            ask1, ask2 = int(asks[0]), int(asks[1])
            ask1_qty = int(-order_depth.sell_orders[ask1])
            ask_ok = (ask2 - ask1) >= gap_min and ask1_qty <= max_l1
        ask_streak = int(memory.get("_gap_ask_streak", 0))
        ask_streak = ask_streak + 1 if ask_ok else 0
        memory["_gap_ask_streak"] = ask_streak

        if ask_streak >= confirm and ask_ok and buy_cap > 0 and asks:
            ask1 = int(asks[0])
            available = int(-order_depth.sell_orders[ask1])
            q = min(size, buy_cap, available)
            if q > 0:
                orders.append(Order(self.product, ask1, q))
                buy_cap -= q
                memory["_last_gap_side"] = 1
        if bid_streak >= confirm and bid_ok and sell_cap > 0 and bids:
            bid1 = int(bids[0])
            available = int(order_depth.buy_orders[bid1])
            q = min(size, sell_cap, available)
            if q > 0:
                orders.append(Order(self.product, bid1, -q))
                sell_cap -= q
                memory["_last_gap_side"] = -1

        if orders:
            memory["_gap_sweep_count"] = int(memory.get("_gap_sweep_count", 0)) + 1
        return orders, buy_cap, sell_cap

    def _flow_probe(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        mode = str(self.params.get("flow_mode", "off"))
        if mode not in {"follow", "fade"}:
            return [], buy_cap, sell_cap

        prev_bid = memory.get("_prev_best_bid")
        prev_ask = memory.get("_prev_best_ask")
        if prev_bid is None or prev_ask is None:
            return [], buy_cap, sell_cap

        hist = memory.setdefault("_flow_hist", [])
        for trade in state.market_trades.get(self.product, []):
            qty = int(trade.quantity)
            if int(trade.price) >= int(prev_ask):
                hist.append(qty)
            elif int(trade.price) <= int(prev_bid):
                hist.append(-qty)

        window = max(1, int(self.params.get("flow_window", 30)))
        if len(hist) > window:
            del hist[:-window]
        total = sum(abs(x) for x in hist)
        if total <= 0:
            memory["_flow_score"] = 0.0
            return [], buy_cap, sell_cap

        flow = sum(hist) / total
        memory["_flow_score"] = flow
        threshold = float(self.params.get("flow_threshold", 0.75))
        if abs(flow) < threshold:
            return [], buy_cap, sell_cap

        interval_ticks = int(self.params.get("flow_interval_ticks", 20))
        ts_increment = int(self.params.get("ts_increment", 100))
        now = int(state.timestamp)
        last_ts = int(memory.get("_last_flow_probe_ts", -10**12))
        if now - last_ts < interval_ticks * ts_increment:
            return [], buy_cap, sell_cap

        direction = 1 if flow > 0 else -1
        if mode == "fade":
            direction *= -1

        qty = max(1, int(self.params.get("flow_size", 1)))
        orders: List[Order] = []
        if direction > 0 and buy_cap > 0 and order_depth.sell_orders:
            ask = int(min(order_depth.sell_orders))
            available = int(-order_depth.sell_orders[ask])
            q = min(qty, buy_cap, available)
            if q > 0:
                orders.append(Order(self.product, ask, q))
                buy_cap -= q
        elif direction < 0 and sell_cap > 0 and order_depth.buy_orders:
            bid = int(max(order_depth.buy_orders))
            available = int(order_depth.buy_orders[bid])
            q = min(qty, sell_cap, available)
            if q > 0:
                orders.append(Order(self.product, bid, -q))
                sell_cap -= q

        if orders:
            memory["_last_flow_probe_ts"] = now
            memory["_flow_probe_count"] = int(memory.get("_flow_probe_count", 0)) + 1
        return orders, buy_cap, sell_cap

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        out["flow_score"] = float(memory.get("_flow_score", 0.0))
        out["far_probe_count"] = float(memory.get("_far_probe_count", 0))
        out["gap_sweep_count"] = float(memory.get("_gap_sweep_count", 0))
        out["flow_probe_count"] = float(memory.get("_flow_probe_count", 0))
        if memory.get("_last_far_bid") is not None:
            out["last_far_bid"] = float(memory["_last_far_bid"])
        if memory.get("_last_far_ask") is not None:
            out["last_far_ask"] = float(memory["_last_far_ask"])
        if memory.get("_last_gap_side") is not None:
            out["last_gap_side"] = float(memory["_last_gap_side"])
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'VEV_4000': {'enable_takers': False,
              'flow_interval_ticks': 20,
              'flow_mode': 'fade',
              'flow_size': 1,
              'flow_threshold': 0.75,
              'flow_window': 30,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_live_probe_mm',
              'strike': 4000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_4500': {'enable_takers': False,
              'flow_interval_ticks': 20,
              'flow_mode': 'fade',
              'flow_size': 1,
              'flow_threshold': 0.75,
              'flow_window': 30,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_live_probe_mm',
              'strike': 4500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5000': {'enable_takers': False,
              'flow_interval_ticks': 20,
              'flow_mode': 'fade',
              'flow_size': 1,
              'flow_threshold': 0.75,
              'flow_window': 30,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_live_probe_mm',
              'strike': 5000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5100': {'enable_takers': False,
              'flow_interval_ticks': 20,
              'flow_mode': 'fade',
              'flow_size': 1,
              'flow_threshold': 0.75,
              'flow_window': 30,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_live_probe_mm',
              'strike': 5100,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5200': {'enable_takers': False,
              'flow_interval_ticks': 20,
              'flow_mode': 'fade',
              'flow_size': 1,
              'flow_threshold': 0.75,
              'flow_window': 30,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_live_probe_mm',
              'strike': 5200,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True}}

STRATEGY_CLASSES = {"option_live_probe_mm": OptionLiveProbeMMStrategy}

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
