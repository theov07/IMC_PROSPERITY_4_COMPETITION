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

    # ── broken-book gap quotes (Theo-style) ────────────────────────────

    def _handle_broken_book(
        self,
        book: BookSnapshot,
        position: int,
        memory: Dict[str, Any],
    ) -> Optional[List[Order]]:
        """If one/both sides of the OB are empty, post wide gap-quotes at
        last_bid - shift / last_ask + shift to catch counterparties that
        cross back through the hole. Returns None when book is two-sided."""
        if book.best_bid is None:
            pass
        elif book.best_ask is None:
            pass
        else:
            return None

        shift = int(self.params.get("empty_side_shift", 0))
        if shift <= 0:
            return []
        size = int(self.params.get("gap_size", 20))
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        last_bid = memory.get("_last_bid")
        last_ask = memory.get("_last_ask")

        orders: List[Order] = []
        if book.best_bid is None and book.best_ask is None:
            if last_bid is not None and buy_cap > 0:
                orders.append(Order(self.product, last_bid - shift, min(size, buy_cap)))
            if last_ask is not None and sell_cap > 0:
                orders.append(Order(self.product, last_ask + shift, -min(size, sell_cap)))
            return orders
        if book.best_bid is None:
            if last_bid is not None and buy_cap > 0:
                orders.append(Order(self.product, last_bid - shift, min(size, buy_cap)))
            return orders
        if book.best_ask is None:
            if last_ask is not None and sell_cap > 0:
                orders.append(Order(self.product, last_ask + shift, -min(size, sell_cap)))
            return orders
        return []

    # ── orchestrator ───────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is not None:
            memory["_last_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_ask"] = book.best_ask

        if book.best_bid is None or book.best_ask is None:
            broken_orders = self._handle_broken_book(book, position, memory)
            return broken_orders or [], 0

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

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'ASH_COATED_OSMIUM': {'aggravate_min_frac': 0.2,
                       'anchor_alpha': 0.0,
                       'anchor_price': 10000.0,
                       'ar_gain': 0.3,
                       'empty_side_shift': 85,
                       'gap_size': 30,
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
                       'unwind_take_edge': 1.0}}

STRATEGY_CLASSES = {"osmium_modulaire": OsmiumModulaireStrategy}

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
