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


# ── prosperity/strategies/naive_tight_mm_v10.py ───────────────────────────────────

class NaiveTightMarketMakerV10Strategy(BaseStrategy):

    # ------------------------------------------------------------------
    # Helpers (identical to V9)
    # ------------------------------------------------------------------

    def _take_orders(
        self,
        order_depth: OrderDepth,
        adjusted_mid: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        orders: List[Order] = []
        take_count = 0

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > adjusted_mid - buy_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < adjusted_mid + sell_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            take_count += 1

        return orders, buy_cap, sell_cap, take_count

    def _apply_inventory_sizing(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.35))
        aggravate_min_frac = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost_frac = float(self.params.get("unwind_boost_frac", 0.25))

        limit = float(self.position_limit())
        pressure = abs(position - inv_target) / max(1.0, limit)

        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        aggravate_frac = 1.0 - (1.0 - aggravate_min_frac) * scaled
        unwind_mult = 1.0 + unwind_boost_frac * scaled

        if position > inv_target:
            if buy_size > 0:
                buy_size = max(1, int(round(buy_size * aggravate_frac)))
            if sell_size > 0:
                sell_size = min(sell_cap, max(1, int(round(sell_size * unwind_mult))))
        elif position < inv_target:
            if sell_size > 0:
                sell_size = max(1, int(round(sell_size * aggravate_frac)))
            if buy_size > 0:
                buy_size = min(buy_cap, max(1, int(round(buy_size * unwind_mult))))

        return buy_size, sell_size

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        take_edge = float(self.params.get("take_edge", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 0.0))
        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_threshold = float(self.params.get("toxic_threshold", 0.6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.5))
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))

        # Signal params
        signal_mode = str(self.params.get("signal_mode", "trend"))
        anchor_price = float(self.params.get("anchor_price", 0.0))
        trend_alpha = float(self.params.get("trend_alpha", 0.0))
        trend_sensitivity = float(self.params.get("trend_sensitivity", 1.0))
        trend_max_shift = float(self.params.get("trend_max_shift", 5.0))
        trend_inv_target_per_tick = float(self.params.get("trend_inv_target_per_tick", 0.0))
        trend_take_boost = float(self.params.get("trend_take_boost", 0.0))
        trend_jump_threshold = float(self.params.get("trend_jump_threshold", 0.0))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        # ── Signal (trend or mean-reversion) ──────────────────────────
        trend_shift = 0.0
        inv_target = 0
        limit = self.position_limit()

        if signal_mode == "mean_rev" and anchor_price != 0.0:
            # Mean-reversion: want to be long when below anchor, short when above
            raw_signal = anchor_price - mid
            trend_shift = max(-trend_max_shift, min(trend_max_shift, raw_signal * trend_sensitivity))
            inv_target = int(round(max(-limit, min(limit, trend_shift * trend_inv_target_per_tick))))

        elif signal_mode == "trend" and trend_alpha > 0.0:
            # Trend-following: EMA of mid price
            trend_ema = memory.get("trend_ema")
            if trend_ema is None:
                trend_ema = mid
            trend_ema = trend_alpha * mid + (1.0 - trend_alpha) * trend_ema
            memory["trend_ema"] = trend_ema

            raw_signal = mid - trend_ema
            trend_shift = max(-trend_max_shift, min(trend_max_shift, raw_signal * trend_sensitivity))
            inv_target = int(round(max(-limit, min(limit, trend_shift * trend_inv_target_per_tick))))

        adjusted_mid = mid + trend_shift

        # ── Take edges ─────────────────────────────────────────────────
        buy_edge = take_edge
        sell_edge = take_edge

        pressure = abs(position - inv_target) / max(1.0, float(limit))
        if position < inv_target:
            buy_edge = max(0.0, buy_edge - unwind_take_edge * pressure)
        elif position > inv_target:
            sell_edge = max(0.0, sell_edge - unwind_take_edge * pressure)

        if trend_shift > 0.0:
            buy_edge = buy_edge - trend_shift * trend_take_boost
        elif trend_shift < 0.0:
            sell_edge = sell_edge - (-trend_shift) * trend_take_boost

        # ── Selective takes ────────────────────────────────────────────
        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth,
            adjusted_mid=adjusted_mid,
            buy_edge=buy_edge,
            sell_edge=sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )
        orders.extend(take_orders)

        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}

        real_best_ask = book.best_ask
        for ask_price, _ in book.ask_levels:
            if ask_price not in swept_ask_prices:
                real_best_ask = ask_price
                break

        real_best_bid = book.best_bid
        for bid_price, _ in book.bid_levels:
            if bid_price not in swept_bid_prices:
                real_best_bid = bid_price
                break

        # ── Passive quote prices ───────────────────────────────────────
        spread = real_best_ask - real_best_bid
        if spread >= 2:
            bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1)
            ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1)
        else:
            bid_price = real_best_bid
            ask_price = real_best_ask

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Passive quote sizes ────────────────────────────────────────
        buy_size, sell_size = self._apply_inventory_sizing(
            position=position,
            inv_target=inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        # ── Toxicity filter ────────────────────────────────────────────
        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")
        bid_jumped = bool(prev_best_bid is not None and real_best_bid == prev_best_bid + 1)
        ask_jumped = bool(prev_best_ask is not None and real_best_ask == prev_best_ask - 1)

        flow_history = memory.setdefault("flow_history", [])
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None and trades:
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

        # Suppress toxicity filter when flow aligns with our signal direction
        suppress_toxic = (
            (flow_score > 0 and trend_shift > 1.0)
            or (flow_score < 0 and trend_shift < -1.0)
        )
        if not suppress_toxic:
            if flow_score > toxic_threshold and sell_size > 0:
                sell_size = max(1, int(round(sell_size * toxic_size_frac)))
            elif flow_score < -toxic_threshold and buy_size > 0:
                buy_size = max(1, int(round(buy_size * toxic_size_frac)))

        # Jump filter — suppressed in the trend direction when signal is strong
        # bid_jumped = bid went up (bullish): reduces sell. Fine even in uptrend.
        # ask_jumped = ask went down (bearish): reduces buy. WRONG in uptrend.
        if bid_jumped and sell_size > 0:
            if trend_shift >= -trend_jump_threshold:
                sell_size = max(1, int(round(sell_size * jump_size_frac)))
        if ask_jumped and buy_size > 0:
            # In a strong uptrend, a 1-tick dip in the ask is a buy opportunity
            if trend_shift <= trend_jump_threshold:
                buy_size = max(1, int(round(buy_size * jump_size_frac)))

        # ── Emit passive orders ────────────────────────────────────────
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        # ── State bookkeeping ──────────────────────────────────────────
        memory["prev_best_bid"] = real_best_bid
        memory["prev_best_ask"] = real_best_ask
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_flow_score"] = flow_score
        memory["last_take_count"] = take_count
        memory["inv_target"] = inv_target
        memory["trend_shift"] = trend_shift

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "flow_score": flow_score,
                "takes": take_count,
                "trend_shift": round(trend_shift, 2),
                "inv_target": inv_target,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if memory.get("trend_ema") is not None:
            out["trend_ema"] = memory["trend_ema"]
        trend_shift = memory.get("trend_shift", 0.0)
        prev_bid = memory.get("last_bid_price")
        prev_ask = memory.get("last_ask_price")
        if prev_bid is not None and prev_ask is not None and trend_shift:
            out["adjusted_mid"] = (prev_bid + prev_ask) / 2.0 + trend_shift
        return out


# ── prosperity/strategies/osmium_mr.py ────────────────────────────────────────────

class OsmiumMeanRevStrategy(NaiveTightMarketMakerV10Strategy):

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

        mid = (book.best_bid + book.best_ask) / 2.0

        # EOD flatten: aggressive liquidation near end of day
        eod_ts = int(self.params.get("eod_flatten_ts", 0))
        if eod_ts > 0 and state.timestamp >= eod_ts and position != 0:
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
            return orders, 0

        ar_gain = float(self.params.get("ar_gain", 0.0))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.0))
        fixed_anchor = float(self.params.get("anchor_price", 10000.0))

        # Rolling EMA anchor
        if anchor_alpha > 0.0:
            ema = memory.get("anchor_ema")
            if ema is None:
                ema = fixed_anchor if fixed_anchor else mid
            ema = anchor_alpha * mid + (1.0 - anchor_alpha) * ema
            memory["anchor_ema"] = ema
            self.params["anchor_price"] = ema

        # AR1 bias encoded as a mid shift BEFORE calling parent
        prev_mid = memory.get("osm_prev_mid")
        ar_shift = 0.0
        if prev_mid is not None and ar_gain > 0.0:
            last_return = mid - prev_mid
            # last_return > 0 (price went UP) → next move down → want to sell:
            # push adjusted_mid DOWN so buy_edge widens / sell_edge narrows.
            ar_shift = -ar_gain * last_return
        memory["osm_prev_mid"] = mid

        # Temporarily patch params so parent picks up extra trend_shift via
        # a fake increment on trend_sensitivity? No — simpler: override the
        # mean_rev trend_max_shift path by pre-biasing the anchor.
        # The parent computes: trend_shift = clamp((anchor - mid) * sens).
        # To add ar_shift, we move the anchor by ar_shift / sens.
        if ar_shift != 0.0:
            sens = float(self.params.get("trend_sensitivity", 1.0)) or 1.0
            self.params["anchor_price"] = float(self.params.get("anchor_price", fixed_anchor)) + ar_shift / sens

        try:
            result = super().compute_orders(state, book, order_depth, position, memory)
        finally:
            if anchor_alpha == 0.0:
                self.params["anchor_price"] = fixed_anchor

        return result

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'ASH_COATED_OSMIUM': {'aggravate_min_frac': 0.2,
                       'anchor_alpha': 0.0,
                       'anchor_price': 10000.0,
                       'ar_gain': 0.6,
                       'inventory_soft_ratio': 0.6,
                       'jump_size_frac': 0.5,
                       'last_ts_value': 999900,
                       'log_flush_ts': 10000,
                       'maker_size': 80,
                       'position_limit': 80,
                       'signal_mode': 'mean_rev',
                       'strategy': 'osmium_mr',
                       'take_edge': 1.75,
                       'tighten_ticks': 1,
                       'total_ticks': 10000000,
                       'toxic_size_frac': 0.75,
                       'toxic_threshold': 0.6,
                       'toxic_window': 6,
                       'trend_inv_target_per_tick': 12.0,
                       'trend_jump_threshold': 1.0,
                       'trend_max_shift': 5.0,
                       'trend_sensitivity': 0.6,
                       'trend_take_boost': 0.2,
                       'ts_increment': 100,
                       'unwind_boost_frac': 0.3,
                       'unwind_take_edge': 1.0}}

STRATEGY_CLASSES = {"osmium_mr": OsmiumMeanRevStrategy}

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
