from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
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


# ── prosperity/strategies/round_2/leo/osmium_modulaire.py ─────────────────────────

class OsmiumModulaireStrategy(BaseStrategy):

    # ── signal ─────────────────────────────────────────────────────────

    def _compute_signal(
        self,
        mid: float,
        memory: Dict[str, Any],
    ) -> Tuple[float, float, int]:
        """Compute adjusted_mid = mid + trend_shift and derived inv_target.

        Two signal modes share a common shift computation:
          - mean_rev: raw = anchor - mid  (reverts toward the anchor)
          - trend:   raw = mid - EMA      (chases the trend)

        Mean-reversion around the anchor is further nudged by an AR(1) term
        so strong last-tick moves pull the fair value against them.
        """
        signal_mode = str(self.params.get("signal_mode", "trend"))
        sens = float(self.params.get("trend_sensitivity", 1.0))
        max_shift = float(self.params.get("trend_max_shift", 5.0))
        inv_per_tick = float(self.params.get("trend_inv_target_per_tick", 0.0))
        limit = self.position_limit()

        fixed_anchor = float(self.params.get("anchor_price", 10000.0))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.0))
        if anchor_alpha > 0.0:
            ema = memory.get("anchor_ema")
            if ema is None:
                ema = fixed_anchor if fixed_anchor else mid
            ema = anchor_alpha * mid + (1.0 - anchor_alpha) * ema
            memory["anchor_ema"] = ema
            anchor_value = ema
        else:
            anchor_value = fixed_anchor

        ar_gain = float(self.params.get("ar_gain", 0.0))
        prev_mid = memory.get("osm_prev_mid")
        ar_shift = 0.0
        if prev_mid is not None and ar_gain > 0.0:
            ar_shift = -ar_gain * (mid - prev_mid)
        memory["osm_prev_mid"] = mid
        if ar_shift != 0.0 and sens != 0.0:
            anchor_value = anchor_value + ar_shift / sens

        trend_shift = 0.0
        if signal_mode == "mean_rev" and anchor_value != 0.0:
            raw = anchor_value - mid
            trend_shift = max(-max_shift, min(max_shift, raw * sens))
        elif signal_mode == "trend":
            alpha = float(self.params.get("trend_alpha", 0.0))
            if alpha > 0.0:
                ema = memory.get("trend_ema")
                if ema is None:
                    ema = mid
                ema = alpha * mid + (1.0 - alpha) * ema
                memory["trend_ema"] = ema
                raw = mid - ema
                trend_shift = max(-max_shift, min(max_shift, raw * sens))

        inv_target = int(round(max(-limit, min(limit, trend_shift * inv_per_tick))))
        adjusted_mid = mid + trend_shift
        return adjusted_mid, trend_shift, inv_target

    # ── end-of-day flatten ─────────────────────────────────────────────

    def _apply_eod_flatten(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        position: int,
    ) -> Optional[List[Order]]:
        """Liquidate the inventory past `eod_flatten_ts`. None if inactive."""
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

    # ── taker modules ──────────────────────────────────────────────────

    def _take_abs(
        self,
        order_depth: OrderDepth,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Unconditional takes when best price crosses absolute thresholds."""
        orders: List[Order] = []
        take_abs_buy = self.params.get("take_abs_buy")
        take_abs_sell = self.params.get("take_abs_sell")

        if take_abs_buy is not None and buy_cap > 0:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > float(take_abs_buy) or buy_cap <= 0:
                    break
                available = -order_depth.sell_orders[ask_p]
                qty = min(available, buy_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, ask_p, qty))
                order_depth.sell_orders[ask_p] += qty
                if order_depth.sell_orders[ask_p] == 0:
                    del order_depth.sell_orders[ask_p]
                buy_cap -= qty

        if take_abs_sell is not None and sell_cap > 0:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < float(take_abs_sell) or sell_cap <= 0:
                    break
                volume = order_depth.buy_orders[bid_p]
                qty = min(volume, sell_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                order_depth.buy_orders[bid_p] -= qty
                if order_depth.buy_orders[bid_p] == 0:
                    del order_depth.buy_orders[bid_p]
                sell_cap -= qty

        return orders, buy_cap, sell_cap

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Sweep thin L1 when L1→L2 gap exceeds threshold."""
        gap_min = float(self.params.get("gap_trigger_min", 0))
        if gap_min <= 0:
            return [], buy_cap, sell_cap

        orders: List[Order] = []
        limit = self.position_limit()
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.15))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

        bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        bid_gap_ok = False
        if len(bids) >= 2:
            b1, b2 = bids[0], bids[1]
            bid_gap_ok = (b1 - b2) >= gap_min and order_depth.buy_orders[b1] <= gap_max_vol
        bs = memory.get("_gap_bid_streak", 0)
        bs = bs + 1 if bid_gap_ok else 0
        memory["_gap_bid_streak"] = bs
        if bs >= gap_confirm and bid_gap_ok and sell_cap > 0:
            b1 = bids[0]
            qty = min(order_depth.buy_orders[b1], sell_cap)
            if qty > 0:
                orders.append(Order(self.product, b1, -qty))
                order_depth.buy_orders[b1] -= qty
                if order_depth.buy_orders[b1] == 0:
                    del order_depth.buy_orders[b1]
                sell_cap -= qty

        asks = sorted(order_depth.sell_orders.keys())
        ask_gap_ok = False
        if len(asks) >= 2:
            a1, a2 = asks[0], asks[1]
            ask_gap_ok = (a2 - a1) >= gap_min and -order_depth.sell_orders[a1] <= gap_max_vol
        asr = memory.get("_gap_ask_streak", 0)
        asr = asr + 1 if ask_gap_ok else 0
        memory["_gap_ask_streak"] = asr
        if asr >= gap_confirm and ask_gap_ok and buy_cap > 0:
            a1 = asks[0]
            qty = min(-order_depth.sell_orders[a1], buy_cap)
            if qty > 0:
                orders.append(Order(self.product, a1, qty))
                order_depth.sell_orders[a1] += qty
                if order_depth.sell_orders[a1] == 0:
                    del order_depth.sell_orders[a1]
                buy_cap -= qty

        return orders, buy_cap, sell_cap

    def _compute_take_edges(
        self,
        position: int,
        inv_target: int,
        trend_shift: float,
    ) -> Tuple[float, float]:
        """Return (buy_edge, sell_edge) adjusted by inventory pressure + trend."""
        take_edge = float(self.params.get("take_edge", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 0.0))
        trend_take_boost = float(self.params.get("trend_take_boost", 0.0))
        limit = self.position_limit()

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
        return buy_edge, sell_edge

    def _take_edge_orders(
        self,
        order_depth: OrderDepth,
        adjusted_mid: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        """Mean-rev taker: buy below adjusted_mid - edge, sell above + edge."""
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

    # ── price anchoring ────────────────────────────────────────────────

    def _reanchor_passive_prices(
        self,
        book: BookSnapshot,
        taker_orders: List[Order],
    ) -> Tuple[int, int]:
        """Compute passive bid/ask using the first book level not swept."""
        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        swept_ask_prices = {o.price for o in taker_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in taker_orders if o.quantity < 0}

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

        spread = real_best_ask - real_best_bid
        if spread >= 2:
            bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1)
            ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1)
        else:
            bid_price = real_best_bid
            ask_price = real_best_ask
        if bid_price >= ask_price:
            ask_price = bid_price + 1
        return bid_price, ask_price

    # ── inventory-adaptive sizing ──────────────────────────────────────

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

    # ── flow / jump filters ────────────────────────────────────────────

    def _apply_toxic_flow(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        trend_shift: float,
        buy_size: int,
        sell_size: int,
    ) -> Tuple[int, int, float]:
        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_threshold = float(self.params.get("toxic_threshold", 0.6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.5))

        flow_history = memory.setdefault("flow_history", [])
        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")
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

        suppress_toxic = (
            (flow_score > 0 and trend_shift > 1.0)
            or (flow_score < 0 and trend_shift < -1.0)
        )
        if not suppress_toxic:
            if flow_score > toxic_threshold and sell_size > 0:
                sell_size = max(1, int(round(sell_size * toxic_size_frac)))
            elif flow_score < -toxic_threshold and buy_size > 0:
                buy_size = max(1, int(round(buy_size * toxic_size_frac)))
        return buy_size, sell_size, flow_score

    def _apply_jump_filter(
        self,
        real_best_bid: int,
        real_best_ask: int,
        memory: Dict[str, Any],
        trend_shift: float,
        buy_size: int,
        sell_size: int,
    ) -> Tuple[int, int]:
        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))
        trend_jump_threshold = float(self.params.get("trend_jump_threshold", 0.0))

        bid_jumped = bool(prev_best_bid is not None and real_best_bid == prev_best_bid + 1)
        ask_jumped = bool(prev_best_ask is not None and real_best_ask == prev_best_ask - 1)
        if bid_jumped and sell_size > 0 and trend_shift >= -trend_jump_threshold:
            sell_size = max(1, int(round(sell_size * jump_size_frac)))
        if ask_jumped and buy_size > 0 and trend_shift <= trend_jump_threshold:
            buy_size = max(1, int(round(buy_size * jump_size_frac)))
        return buy_size, sell_size

    def _passive_quotes(
        self,
        bid_price: int,
        ask_price: int,
        buy_size: int,
        sell_size: int,
    ) -> List[Order]:
        orders: List[Order] = []
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))
        return orders

    # ── orchestrator ───────────────────────────────────────────────────

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

        eod_orders = self._apply_eod_flatten(state, order_depth, position)
        if eod_orders is not None:
            return eod_orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0
        adjusted_mid, trend_shift, inv_target = self._compute_signal(mid, memory)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        abs_orders, buy_cap, sell_cap = self._take_abs(order_depth, buy_cap, sell_cap)
        gap_orders, buy_cap, sell_cap = self._gap_exploit(order_depth, memory, buy_cap, sell_cap)

        if not order_depth.buy_orders or not order_depth.sell_orders:
            memory["inv_target"] = inv_target
            memory["trend_shift"] = trend_shift
            return abs_orders + gap_orders, 0

        buy_edge, sell_edge = self._compute_take_edges(position, inv_target, trend_shift)
        take_orders, buy_cap, sell_cap, take_count = self._take_edge_orders(
            order_depth, adjusted_mid, buy_edge, sell_edge, buy_cap, sell_cap,
        )

        bid_price, ask_price = self._reanchor_passive_prices(book, take_orders)

        buy_size, sell_size = self._apply_inventory_sizing(
            position, inv_target, buy_cap, sell_cap,
        )
        buy_size, sell_size, flow_score = self._apply_toxic_flow(
            state, memory, trend_shift, buy_size, sell_size,
        )
        buy_size, sell_size = self._apply_jump_filter(
            book.best_bid, book.best_ask, memory, trend_shift, buy_size, sell_size,
        )

        passive_orders = self._passive_quotes(bid_price, ask_price, buy_size, sell_size)

        memory["prev_best_bid"] = book.best_bid
        memory["prev_best_ask"] = book.best_ask
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

        return abs_orders + gap_orders + take_orders + passive_orders, 0


# ── prosperity/strategies/round_1/regression_mm_v5.py ─────────────────────────────

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

    def _quote_prices(
        self,
        *,
        book: BookSnapshot,
        stats: Dict[str, float],
        position: int,
        inv_target: int,
    ) -> Tuple[int, int, int, int]:
        best_bid = int(book.best_bid)
        best_ask = int(book.best_ask)
        tighten_ticks = int(self.params.get("tighten_ticks", 1))

        spread = best_ask - best_bid
        if spread >= 2:
            bid_price = min(best_bid + tighten_ticks, best_ask - 1)
            ask_price = max(best_ask - tighten_ticks, best_bid + 1)
        else:
            bid_price = best_bid
            ask_price = best_ask

        bid_extra = 0
        ask_relax = 0
        if stats["trend_ticks"] >= float(self.params.get("strong_trend_ticks", 1.1)):
            bid_extra += 1
            ask_relax += 1
        if stats["trend_ticks"] >= float(self.params.get("very_strong_trend_ticks", 2.0)):
            bid_extra += 1
        if stats["residual_z"] <= -float(self.params.get("cheap_residual_z", 0.9)):
            bid_extra += 1
        if stats["residual_z"] >= float(self.params.get("rich_residual_z", 1.0)):
            ask_relax = max(0, ask_relax - 1)

        if position < inv_target:
            ask_relax = max(ask_relax, 1)
        elif position > inv_target:
            bid_extra = max(0, bid_extra - 1)

        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        max_ask_relax = int(self.params.get("max_ask_relax_ticks", 2))
        bid_extra = max(0, min(max_bid_extra, bid_extra))
        ask_relax = max(0, min(max_ask_relax, ask_relax))

        bid_price = min(best_ask - 1, bid_price + bid_extra)
        ask_price = min(best_ask, ask_price + ask_relax)
        ask_price = max(ask_price, best_bid + 1)

        if bid_price >= ask_price:
            bid_price = min(best_ask - 1, best_bid + 1)
            ask_price = max(best_bid + 1, bid_price + 1)

        return bid_price, ask_price, bid_extra, ask_relax

    def _selective_take(
        self,
        *,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []

        take_edge = float(self.params.get("take_edge", 8.0))
        max_take = int(self.params.get("max_take_size", 8))
        take_only_toward_target = bool(self.params.get("take_only_toward_target", True))

        if buy_cap > 0:
            for ask_price in sorted(order_depth.sell_orders):
                if ask_price > fair_value - take_edge:
                    break
                if take_only_toward_target and position >= inv_target:
                    break
                qty = min(-order_depth.sell_orders[ask_price], buy_cap, max_take)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty
                position += qty
                if buy_cap <= 0:
                    break

        if sell_cap > 0:
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                if bid_price < fair_value + take_edge:
                    break
                if take_only_toward_target and position <= inv_target:
                    break
                qty = min(order_depth.buy_orders[bid_price], sell_cap, max_take)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_price, -qty))
                sell_cap -= qty
                position -= qty
                if sell_cap <= 0:
                    break

        return orders, buy_cap, sell_cap

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
        inv_target = self._inventory_target(state=state, stats=stats, position=position)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if bool(self.params.get("enable_selective_take", False)):
            take_orders, buy_cap, sell_cap = self._selective_take(
                order_depth=order_depth,
                fair_value=stats["fair_value"],
                position=position,
                inv_target=inv_target,
                buy_cap=buy_cap,
                sell_cap=sell_cap,
            )
            orders.extend(take_orders)

        bid_price, ask_price, bid_extra, ask_relax = self._quote_prices(
            book=book,
            stats=stats,
            position=position,
            inv_target=inv_target,
        )
        buy_size, sell_size = self._size_from_target(
            position=position,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["inv_target"] = inv_target
        memory["last_spread"] = book.spread

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "reg_slope": round(stats["slope"], 4),
                "reg_r2": round(stats["r2"], 3),
                "trend_ticks": round(stats["trend_ticks"], 2),
                "residual_z": round(stats["residual_z"], 2),
                "block_count": int(stats["block_count"]),
                "fair_value": round(stats["fair_value"], 2),
                "inv_target": inv_target,
                "bid_extra": bid_extra,
                "ask_relax": ask_relax,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        stats = memory.get("regression_stats")
        if not stats:
            return {}
        return {
            "reg_fitted_now": float(stats["fitted_now"]),
            "reg_forecast": float(stats["forecast"]),
            "reg_fair_value": float(stats["fair_value"]),
        }


# ── prosperity/strategies/round_2/leo/pepper_modulaire.py ─────────────────────────

class PepperModulaireStrategy(Round1RegressionMMV5Strategy):

    # ── memory helpers ─────────────────────────────────────────────────

    def _track_recent_best_asks(
        self,
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> None:
        if book.best_ask is None:
            return
        window = int(self.params.get("gap_scout_recent_ask_window", 6))
        recent = memory.setdefault("_recent_best_asks", [])
        recent.append(int(book.best_ask))
        if len(recent) > window:
            del recent[:-window]

    # ── quote price modules ────────────────────────────────────────────

    def _compute_fv_quotes(
        self,
        book: BookSnapshot,
        fv: float,
        bullish: bool,
    ) -> Tuple[int, int]:
        """Fair-value anchored bid/ask with bullish-biased spreads."""
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
        return bid_price, ask_price

    def _apply_price_step(
        self,
        bid_price: int,
        ask_price: int,
        book: BookSnapshot,
        trend_ticks: float,
        residual_z: float,
    ) -> Tuple[int, int]:
        """Tick-level nudges on top of fv quotes from trend/residual signals."""
        strong = float(self.params.get("strong_trend_ticks", 1.1))
        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        cheap_z = float(self.params.get("cheap_residual_z", 0.9))
        rich_z = float(self.params.get("rich_residual_z", 1.0))
        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        max_ask_relax = int(self.params.get("max_ask_relax_ticks", 2))

        bid_extra = 0
        ask_relax = 0
        if trend_ticks >= strong:
            bid_extra += 1
        if trend_ticks >= very_strong:
            bid_extra += 1
        if residual_z <= -cheap_z:
            bid_extra += 1
        if residual_z >= rich_z:
            ask_relax -= 1
        bid_extra = max(0, min(max_bid_extra, bid_extra))
        ask_relax = max(-max_ask_relax, min(max_ask_relax, ask_relax))

        bid_price = min(book.best_ask - 1, bid_price + bid_extra)
        ask_price = max(book.best_bid + 1, ask_price + ask_relax)
        if bid_price >= ask_price:
            ask_price = bid_price + 1
        return bid_price, ask_price

    # ── taker modules ──────────────────────────────────────────────────

    def _compute_take_edges(
        self,
        bullish: bool,
        residual_z: float,
        position: int,
        inv_target: int,
    ) -> Tuple[float, float]:
        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -8.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull", 6.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        rich_z = float(self.params.get("rich_residual_z", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 10.0))

        if bullish:
            buy_edge = take_buy_edge_bull
            sell_edge = take_sell_edge_bull
            if residual_z >= rich_z:
                buy_edge = take_buy_edge_neut
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut

        limit = self.position_limit()
        if (not bullish) and position > inv_target:
            pressure = min(1.0, (position - inv_target) / max(1.0, float(limit)))
            sell_edge = sell_edge - unwind_take_edge * pressure
        return buy_edge, sell_edge

    def _take_orders(
        self,
        order_depth: OrderDepth,
        fv: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0:
                break
            qty = min(-order_depth.sell_orders[ask_p], buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            buy_cap -= qty
        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fv + sell_edge or sell_cap <= 0:
                break
            qty = min(order_depth.buy_orders[bid_p], sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_p, -qty))
            sell_cap -= qty
        return orders, buy_cap, sell_cap

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        gap_min = float(self.params.get("gap_trigger_min", 0))
        if gap_min <= 0:
            return [], buy_cap, sell_cap

        orders: List[Order] = []
        limit = self.position_limit()
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.15))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

        bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        bid_gap_ok = False
        if len(bids) >= 2:
            b1, b2 = bids[0], bids[1]
            bid_gap_ok = (b1 - b2) >= gap_min and order_depth.buy_orders[b1] <= gap_max_vol
        bs = memory.get("_gap_bid_streak", 0)
        bs = bs + 1 if bid_gap_ok else 0
        memory["_gap_bid_streak"] = bs
        if bs >= gap_confirm and bid_gap_ok and sell_cap > 0:
            b1 = bids[0]
            qty = min(order_depth.buy_orders[b1], sell_cap)
            if qty > 0:
                orders.append(Order(self.product, b1, -qty))
                order_depth.buy_orders[b1] -= qty
                if order_depth.buy_orders[b1] == 0:
                    del order_depth.buy_orders[b1]
                sell_cap -= qty

        asks = sorted(order_depth.sell_orders.keys())
        ask_gap_ok = False
        if len(asks) >= 2:
            a1, a2 = asks[0], asks[1]
            ask_gap_ok = (a2 - a1) >= gap_min and -order_depth.sell_orders[a1] <= gap_max_vol
        asr = memory.get("_gap_ask_streak", 0)
        asr = asr + 1 if ask_gap_ok else 0
        memory["_gap_ask_streak"] = asr
        if asr >= gap_confirm and ask_gap_ok and buy_cap > 0:
            a1 = asks[0]
            qty = min(-order_depth.sell_orders[a1], buy_cap)
            if qty > 0:
                orders.append(Order(self.product, a1, qty))
                order_depth.sell_orders[a1] += qty
                if order_depth.sell_orders[a1] == 0:
                    del order_depth.sell_orders[a1]
                buy_cap -= qty

        return orders, buy_cap, sell_cap

    # ── scout / rebuy / hold ───────────────────────────────────────────

    def _gap_scout_sell(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        bullish: bool,
        memory: Dict[str, Any],
        current_orders: List[Order],
    ) -> List[Order]:
        floor_pos = int(self.params.get("gap_scout_floor_position", 78))
        if not bullish or position < floor_pos:
            return current_orders
        sell_cap = self.sell_capacity(position)
        for o in current_orders:
            if o.quantity < 0:
                sell_cap += o.quantity
        if sell_cap <= 0 or not book.ask_levels:
            return current_orders

        min_gap = int(self.params.get("gap_scout_min_gap", 3))
        ask_fragile = len(book.ask_levels) == 1
        if len(book.ask_levels) >= 2:
            ask_fragile = ask_fragile or (
                book.ask_levels[1][0] - book.ask_levels[0][0] >= min_gap
            )
        if not ask_fragile:
            return current_orders

        ts = int(state.timestamp)
        in_window = (
            int(self.params.get("gap_scout_early_start_ts", 3600))
            <= ts
            <= int(self.params.get("gap_scout_early_end_ts", 8500))
            or int(self.params.get("gap_scout_mid_start_ts", 56500))
            <= ts
            <= int(self.params.get("gap_scout_mid_end_ts", 57500))
            or int(self.params.get("gap_scout_late_start_ts", 143000))
            <= ts
            <= int(self.params.get("gap_scout_late_end_ts", 145000))
        )
        if not in_window:
            return current_orders

        recent = memory.get("_recent_best_asks", [])
        if not recent:
            return current_orders

        empty_side_shift = int(self.params.get("empty_side_shift", 85))
        candidate_price = min(recent) + empty_side_shift
        existing_sell_prices = [o.price for o in current_orders if o.quantity < 0]
        if existing_sell_prices and candidate_price <= max(existing_sell_prices):
            return current_orders

        size_limit = int(self.params.get("gap_scout_size_limit", 5))
        qty = min(sell_cap, size_limit, max(0, position - floor_pos + 1))
        if qty <= 0:
            return current_orders

        memory["_last_gap_sell_ts"] = ts
        memory["_last_gap_sell_price"] = candidate_price
        return current_orders + [Order(self.product, candidate_price, -qty)]

    def _gap_rebuy_buy(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        inv_target: int,
        bullish: bool,
        fv: float,
        memory: Dict[str, Any],
        current_orders: List[Order],
    ) -> List[Order]:
        if not bullish:
            return current_orders
        last_sell_ts = int(memory.get("_last_gap_sell_ts", -10**9))
        last_sell_price = memory.get("_last_gap_sell_price")
        if last_sell_price is None or book.best_ask is None:
            return current_orders

        window = int(self.params.get("gap_rebuy_window", 2500))
        age = int(state.timestamp) - last_sell_ts
        if age < 0 or age > window:
            return current_orders

        min_discount = float(self.params.get("gap_rebuy_min_discount", 20.0))
        if float(last_sell_price) - float(book.best_ask) < min_discount:
            return current_orders
        if position >= inv_target:
            return current_orders

        buy_cap = self.buy_capacity(position)
        for o in current_orders:
            if o.quantity > 0:
                buy_cap -= o.quantity
        if buy_cap <= 0:
            return current_orders

        rebuy_edge = float(self.params.get("gap_rebuy_buy_edge", -10.0))
        take_cap = min(buy_cap, int(self.params.get("gap_rebuy_take_cap", 8)),
                       max(0, inv_target - position))
        if take_cap <= 0:
            return current_orders

        extra: List[Order] = []
        queued_ask_qty: Dict[int, int] = {}
        for o in current_orders:
            if o.quantity > 0:
                queued_ask_qty[o.price] = queued_ask_qty.get(o.price, 0) + o.quantity

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - rebuy_edge or take_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_p] - queued_ask_qty.get(ask_p, 0)
            if available <= 0:
                continue
            qty = min(available, take_cap)
            extra.append(Order(self.product, ask_p, qty))
            take_cap -= qty
        return current_orders + extra

    def _hold_sell(
        self,
        book: BookSnapshot,
        position: int,
        bullish: bool,
        current_orders: List[Order],
    ) -> List[Order]:
        if not bullish or book.best_ask is None:
            return current_orders
        size = int(self.params.get("hold_sell_size", 1))
        if size <= 0:
            return current_orders
        limit = self.position_limit()
        if position < limit - size + 1:
            return current_orders
        sell_cap = self.sell_capacity(position)
        for o in current_orders:
            if o.quantity < 0:
                sell_cap += o.quantity
        if sell_cap <= 0:
            return current_orders

        offset = int(self.params.get("hold_sell_offset", 0))
        price = int(book.best_ask) + offset
        qty = min(size, sell_cap)
        existing_sell_prices = [o.price for o in current_orders if o.quantity < 0]
        if price in existing_sell_prices:
            return current_orders
        return current_orders + [Order(self.product, price, -qty)]

    def _passive_quotes(
        self,
        bid_price: int,
        ask_price: int,
        buy_size: int,
        sell_size: int,
    ) -> List[Order]:
        orders: List[Order] = []
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))
        return orders

    # ── orchestrator ───────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        self._track_recent_best_asks(book, memory)

        if book.best_bid is None or book.best_ask is None:
            return [], 0

        mid = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        trend_ticks = stats["trend_ticks"]
        residual_z = stats["residual_z"]
        fv = stats["fair_value"]

        inv_target = self._inventory_target(state=state, stats=stats, position=position)
        bullish = trend_ticks > float(self.params.get("bull_threshold", 1.0))

        # Gap exploit first (mutates order_depth), then delegate to the
        # fv-anchored MM on the post-gap book, using a virtual position that
        # reflects the gap fills. Mirrors leo_fusion_b_gap → leo_fusion_b.
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        gap_orders, buy_cap, sell_cap = self._gap_exploit(
            order_depth, memory, buy_cap, sell_cap,
        )
        virt_pos = position + sum(o.quantity for o in gap_orders)

        take_orders: List[Order] = []
        passive_orders: List[Order] = []
        bid_price = ask_price = None
        if order_depth.buy_orders and order_depth.sell_orders:
            bid_price, ask_price = self._compute_fv_quotes(book, fv, bullish)
            bid_price, ask_price = self._apply_price_step(
                bid_price, ask_price, book, trend_ticks, residual_z,
            )
            buy_edge, sell_edge = self._compute_take_edges(
                bullish, residual_z, virt_pos, inv_target,
            )
            mm_buy_cap = self.buy_capacity(virt_pos)
            mm_sell_cap = self.sell_capacity(virt_pos)
            take_orders, mm_buy_cap, mm_sell_cap = self._take_orders(
                order_depth, fv, buy_edge, sell_edge, mm_buy_cap, mm_sell_cap,
            )
            buy_size, sell_size = self._size_from_target(
                position=virt_pos,
                inv_target=inv_target,
                stats=stats,
                buy_cap=mm_buy_cap,
                sell_cap=mm_sell_cap,
            )
            passive_orders = self._passive_quotes(bid_price, ask_price, buy_size, sell_size)

        orders = gap_orders + take_orders + passive_orders
        orders = self._gap_rebuy_buy(
            state, book, order_depth, position, inv_target, bullish, fv, memory, orders,
        )
        orders = self._gap_scout_sell(
            state, book, position, bullish, memory, orders,
        )
        orders = self._hold_sell(book, position, bullish, orders)

        memory["last_bid_price"] = bid_price if bid_price is not None else memory.get("last_bid_price")
        memory["last_ask_price"] = ask_price if ask_price is not None else memory.get("last_ask_price")
        memory["inv_target"] = inv_target
        memory["bullish"] = int(bullish)

        if bid_price is None or ask_price is None:
            return orders, 0

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
            },
        )
        return orders, 0

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'ASH_COATED_OSMIUM': {'aggravate_min_frac': 0.2,
                       'anchor_alpha': 0.0,
                       'anchor_price': 10000.0,
                       'ar_gain': 0.3,
                       'gap_trigger_confirm_ticks': 2,
                       'gap_trigger_max_vol_pct': 0.15,
                       'gap_trigger_min': 20,
                       'inventory_soft_ratio': 0.9,
                       'jump_size_frac': 0.5,
                       'last_ts_value': 999900,
                       'log_flush_ts': 10000,
                       'maker_size': 80,
                       'position_limit': 80,
                       'signal_mode': 'mean_rev',
                       'strategy': 'osmium_modulaire',
                       'take_edge': 1.5,
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
                       'unwind_take_edge': 1.0},
 'INTARIAN_PEPPER_ROOT': {'aggravate_cut': 0.04,
                          'ask_spread_bull': 9.0,
                          'bid_spread_bull': 1.0,
                          'block_size': 200,
                          'bootstrap_confidence': 0.55,
                          'bull_threshold': 1.0,
                          'cheap_buy_boost_per_z': 0.18,
                          'cheap_residual_z': 0.9,
                          'empty_side_shift': 5,
                          'gap_rebuy_buy_edge': -10.0,
                          'gap_rebuy_min_discount': 20.0,
                          'gap_rebuy_take_cap': 8,
                          'gap_rebuy_window': 2500,
                          'gap_scout_early_end_ts': 999900,
                          'gap_scout_early_start_ts': 0,
                          'gap_scout_floor_position': 78,
                          'gap_scout_late_end_ts': 0,
                          'gap_scout_late_start_ts': 0,
                          'gap_scout_mid_end_ts': 0,
                          'gap_scout_mid_start_ts': 0,
                          'gap_scout_min_gap': 3,
                          'gap_scout_recent_ask_window': 6,
                          'gap_scout_size_limit': 7,
                          'gap_trigger_confirm_ticks': 1,
                          'gap_trigger_max_vol_pct': 0.15,
                          'gap_trigger_min': 8,
                          'hold_sell_offset': 0,
                          'hold_sell_size': 1,
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
                          'resid_inv_per_z': 18.0,
                          'rich_residual_z': 1.0,
                          'rich_sell_boost_per_z': 0.14,
                          'seed_slope': 0.1015,
                          'startup_end_ts': 30000,
                          'startup_target': 40,
                          'strategy': 'pepper_modulaire',
                          'strong_trend_ticks': 1.1,
                          'take_buy_edge_bull': -8.0,
                          'take_buy_edge_neut': 2.0,
                          'take_sell_edge_bull': 6.0,
                          'take_sell_edge_neut': 2.0,
                          'target_gap_scale': 26.0,
                          'tighten_ticks': 1,
                          'trend_buy_boost_per_tick': 0.24,
                          'trend_inv_per_tick': 14.0,
                          'trend_inventory_cap': 74,
                          'trend_sell_boost_per_tick': 0.2,
                          'ts_increment': 100,
                          'unwind_take_edge': 10.0,
                          'very_strong_trend_ticks': 2.0}}

STRATEGY_CLASSES = {"osmium_modulaire": OsmiumModulaireStrategy, "pepper_modulaire": PepperModulaireStrategy}

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
