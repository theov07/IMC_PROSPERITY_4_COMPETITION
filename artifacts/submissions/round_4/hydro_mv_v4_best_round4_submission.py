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


# ── prosperity/strategies/round_4/tibo/hydro_mv_v4.py ─────────────────────────────

class HydroMVV4(BaseStrategy):

    # ── AR model (same as v2/v3) ──────────────────────────────────────────

    def _update_ar(
        self, raw_mid: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        ms_hl    = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms  = memory.get("_mid_smooth")
        mid_s    = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        anchor_fixed = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.02))
        drift_bound  = float(self.params.get("anchor_drift_bound", 1.5))
        anchor_ema   = float(memory.get("_anchor_ema", anchor_fixed))
        if anchor_alpha > 0:
            anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
            if drift_bound > 0:
                anchor_ema = max(anchor_fixed - drift_bound,
                                 min(anchor_fixed + drift_bound, anchor_ema))
        memory["_anchor_ema"] = anchor_ema

        ar_hl    = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta    = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom   = float(memory.get("_ar_momentum", 0.0))
        ar_mom   = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        ar_gain    = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev = mid_s - fair_value
        dev_hl    = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s     = float(memory.get("_dev_smooth", raw_dev))
        dev_s     = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s
        memory["_dev_raw"]    = raw_dev
        return mid_s, fair_value, dev_s

    # ── Mark 14 tracking ──────────────────────────────────────────────────

    def _update_m14(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> int:
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:   net += trade.quantity
            elif trade.seller == trader: net -= trade.quantity
        this_tick = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_this"] = this_tick
        lookback = int(self.params.get("m14_lookback_ticks", 20))
        hist: List[int] = memory.setdefault("_m14_hist", [])
        hist.append(this_tick)
        if len(hist) > lookback:
            hist[:] = hist[-lookback:]
        return this_tick

    def _m14_recent(self, memory: Dict[str, Any]) -> int:
        hist = memory.get("_m14_hist", [])
        net  = sum(hist)
        return 1 if net > 0 else (-1 if net < 0 else 0)

    # ── Feature 1: Trend guard ────────────────────────────────────────────

    def _update_trend(self, raw_mid: float, memory: Dict[str, Any]) -> float:
        alpha    = float(self.params.get("trend_alpha", 0.3))
        prev_mid = memory.get("_trend_prev_mid", raw_mid)
        delta    = raw_mid - float(prev_mid)
        trend    = float(memory.get("_trend_ema", 0.0))
        trend    = alpha * delta + (1.0 - alpha) * trend
        memory["_trend_ema"]      = trend
        memory["_trend_prev_mid"] = raw_mid
        return trend

    def _trend_blocks(self, direction: int, memory: Dict[str, Any]) -> bool:
        thresh = float(self.params.get("trend_guard_threshold", 0.0))
        if thresh <= 0:
            return False
        trend = float(memory.get("_trend_ema", 0.0))
        if direction > 0 and trend < -thresh:   return True   # BUY blocked: falling
        if direction < 0 and trend >  thresh:   return True   # SELL blocked: rising
        return False

    # ── Feature 3: Toxic flow gate ────────────────────────────────────────

    def _update_flow(self, state: TradingState, memory: Dict[str, Any]) -> float:
        thresh = float(self.params.get("toxic_flow_threshold", 0.0))
        if thresh <= 0:
            return 0.0
        window   = int(self.params.get("toxic_window", 8))
        prev_bid = memory.get("_prev_best_bid")
        prev_ask = memory.get("_prev_best_ask")
        hist: List[float] = memory.setdefault("_flow_hist", [])
        if prev_bid is not None and prev_ask is not None:
            for trade in state.market_trades.get(self.product, []):
                if trade.price >= prev_ask:   hist.append(trade.quantity)
                elif trade.price <= prev_bid:  hist.append(-trade.quantity)
        if len(hist) > window:
            hist[:] = hist[-window:]
        if not hist:
            return 0.0
        total  = sum(abs(x) for x in hist)
        score  = sum(hist) / total if total > 0 else 0.0
        memory["_flow_score"] = score
        return score

    def _flow_blocks(self, direction: int, memory: Dict[str, Any]) -> bool:
        thresh = float(self.params.get("toxic_flow_threshold", 0.0))
        if thresh <= 0:
            return False
        score = float(memory.get("_flow_score", 0.0))
        if direction > 0 and score < -thresh:  return True   # buying into selling flow
        if direction < 0 and score >  thresh:  return True   # selling into buying flow
        return False

    # ── Feature 4: Deviation size scaling ────────────────────────────────

    def _scaled_size(self, dev: float, entry_thresh: float) -> int:
        base      = int(self.params.get("entry_size", 20))
        scale_f   = float(self.params.get("dev_size_scale", 0.0))
        if scale_f <= 0:
            return base
        max_mult  = float(self.params.get("dev_size_max_mult", 3.0))
        excess    = max(0.0, abs(dev) - entry_thresh)
        mult      = min(max_mult, 1.0 + scale_f * excess / entry_thresh)
        return int(base * mult)

    # ── Feature 5: Vol-scaled threshold ──────────────────────────────────

    def _effective_threshold(self, memory: Dict[str, Any]) -> float:
        base = float(self.params.get("entry_threshold", 20.0))
        scale_v = float(self.params.get("vol_thresh_scale", 0.0))
        if scale_v <= 0:
            return base
        sigma   = float(memory.get("sigma_smoothed", 0.0))
        vol_ref = float(self.params.get("vol_ref", 3.0))
        return base * (1.0 + scale_v * sigma / max(vol_ref, 1e-6))

    # ── Order helpers ─────────────────────────────────────────────────────

    def _taker_buy(self, position: int, book: BookSnapshot, size: int) -> List[Order]:
        qty = min(self.buy_capacity(position), size)
        if qty > 0 and book.best_ask is not None:
            return [Order(self.product, book.best_ask, qty)]
        return []

    def _taker_sell(self, position: int, book: BookSnapshot, size: int) -> List[Order]:
        qty = min(self.sell_capacity(position), size)
        if qty > 0 and book.best_bid is not None:
            return [Order(self.product, book.best_bid, -qty)]
        return []

    # ── Main entry ────────────────────────────────────────────────────────

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
            return [], 0

        mid_s, fair_value, dev = self._update_ar(float(mid), memory)
        m14_this   = self._update_m14(state, memory)
        m14_recent = self._m14_recent(memory)
        trend      = self._update_trend(float(mid), memory)
        flow       = self._update_flow(state, memory)
        sigma      = self._update_volatility(float(mid), memory)

        # Store book prices for flow detector
        if book.best_bid is not None: memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None: memory["_prev_best_ask"] = book.best_ask

        entry_thresh = self._effective_threshold(memory)
        exit_thresh  = float(self.params.get("exit_threshold", 2.0))
        base_size    = int(self.params.get("entry_size", 20))
        stop_mult    = float(self.params.get("stop_loss_mult", 0.0))

        mv_state = memory.get("_mv_state", "flat")
        intent   = memory.get("_intent",   0)
        orders: List[Order] = []

        # ── Stop loss (feature 2) ─────────────────────────────────────────
        if mv_state in ("entering", "holding") and stop_mult > 0:
            entry_dev = float(memory.get("_entry_dev", 0.0))
            stop_hit  = (
                (intent > 0 and dev > entry_dev + stop_mult * entry_thresh) or
                (intent < 0 and dev < entry_dev - stop_mult * entry_thresh)
            )
            if stop_hit:
                mv_state = "exiting"
                memory["_mv_state"] = "exiting"
                memory["_stop_hit"] = 1

        # ── Normal exit ───────────────────────────────────────────────────
        if mv_state in ("entering", "holding"):
            if (intent > 0 and dev > -exit_thresh) or (intent < 0 and dev < exit_thresh):
                mv_state = "exiting"
                memory["_mv_state"] = "exiting"

        # ── State machine ─────────────────────────────────────────────────
        if mv_state == "flat":
            direction = 0
            if dev < -entry_thresh:   direction = 1
            elif dev > entry_thresh:  direction = -1

            if direction != 0:
                # Mark 14: agree → scale up, oppose → skip
                agree_factor = float(self.params.get("m14_agree_factor", 3.0))
                if m14_recent != 0 and m14_recent != direction:
                    direction = 0  # M14 opposes → cancel entry

            if direction != 0 and not self._trend_blocks(direction, memory) \
                    and not self._flow_blocks(direction, memory):
                # Size: base × dev_scale × m14_scale
                size = self._scaled_size(dev, entry_thresh)  # feature 4 (dev scaling)
                if m14_recent == direction:
                    size = int(size * agree_factor)           # M14 agrees → amplify

                if direction > 0:
                    orders = self._taker_buy(position, book, size)
                    if orders:
                        memory["_intent"]       = 1
                        memory["_entry_target"] = size
                        memory["_entry_dev"]    = dev
                        memory["_mv_state"]     = "entering"
                else:
                    orders = self._taker_sell(position, book, size)
                    if orders:
                        memory["_intent"]       = -1
                        memory["_entry_target"] = size
                        memory["_entry_dev"]    = dev
                        memory["_mv_state"]     = "entering"

        elif mv_state == "entering":
            target_abs = memory.get("_entry_target", int(self.params.get("entry_size", 20)))
            target     = target_abs if intent > 0 else -target_abs
            remaining  = target - position
            if abs(remaining) <= 0:
                memory["_mv_state"] = "holding"
            elif remaining > 0:
                orders = self._taker_buy(position, book, remaining)
            else:
                orders = self._taker_sell(position, book, abs(remaining))

        elif mv_state == "holding":
            pass

        elif mv_state == "exiting":
            if position > 0:
                orders = self._taker_sell(position, book, position)
            elif position < 0:
                orders = self._taker_buy(position, book, abs(position))
            else:
                memory["_mv_state"] = "flat"
                memory["_intent"]   = 0
                memory.pop("_stop_hit", None)

        # ── Logging ───────────────────────────────────────────────────────
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":   position,
                "deviation":  round(dev, 3),
                "trend_ema":  round(trend, 4),
                "flow_score": round(float(memory.get("_flow_score", 0)), 4),
                "m14_recent": m14_recent,
                "mv_state":   mv_state,
                "entry_thresh": round(entry_thresh, 2),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))  is not None: out["FairValue"]  = float(v)
        if (v := memory.get("_dev_smooth"))  is not None: out["DevSmooth"]  = float(v)
        if (v := memory.get("_trend_ema"))   is not None: out["TrendEMA"]   = float(v)
        if (v := memory.get("_flow_score"))  is not None: out["FlowScore"]  = float(v)
        if (v := memory.get("_m14_this"))    is not None: out["M14This"]    = float(v)
        st = memory.get("_mv_state", "flat")
        out["MvStateN"] = {"flat": 0, "entering": 1, "holding": 2, "exiting": 3}.get(st, -1)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'anchor_alpha': 0.02,
                   'anchor_drift_bound': 1.5,
                   'anchor_price': 10000.0,
                   'ar_gain': 8.0,
                   'ar_smooth_half_life': 5,
                   'dev_size_max_mult': 5.0,
                   'dev_size_scale': 2.0,
                   'dev_smooth_half_life': 5,
                   'entry_size': 20,
                   'entry_threshold': 20.0,
                   'exit_threshold': 2.0,
                   'informed_trader_name': 'Mark 14',
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'm14_agree_factor': 3.0,
                   'm14_lookback_ticks': 20,
                   'mark14_mode': 'scale',
                   'mid_smooth_half_life': 20,
                   'position_limit': 200,
                   'quote_trace_enabled': True,
                   'stop_loss_mult': 0.0,
                   'strategy': 'hydro_mv_v4',
                   'toxic_flow_threshold': 0.0,
                   'trend_guard_threshold': 0.0,
                   'ts_increment': 100,
                   'vol_thresh_scale': 0.0}}

STRATEGY_CLASSES = {"hydro_mv_v4": HydroMVV4}

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
