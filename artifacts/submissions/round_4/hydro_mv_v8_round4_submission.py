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


# ── prosperity/strategies/round_4/tibo/hydro_mv_v8.py ─────────────────────────────

class HydroMVV8(BaseStrategy):

    # ── Fast EWMA mid ─────────────────────────────────────────────────────

    def _compute_fast_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        hl = float(self.params.get("fast_mid_half_life", 5))
        alpha = 1.0 - 0.5 ** (1.0 / max(hl, 0.1))
        prev = float(memory.get("_fast_mid", mid))
        v = alpha * mid + (1.0 - alpha) * prev
        memory["_fast_mid"] = v
        return v

    # ── AR model (identical to v7) ────────────────────────────────────────

    def _update_slow_ar(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float]:
        ms_hl = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        anchor_price = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.005))
        anchor_ema = float(memory.get("_anchor_ema", anchor_price))
        limit = self.position_limit()
        pos_thr = float(self.params.get("anchor_pos_threshold", 0.20))
        if limit > 0 and abs(position) < limit * pos_thr:
            anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
        memory["_anchor_ema"] = anchor_ema

        ar_hl = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        ar_mom = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        ar_gain = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev = mid_s - fair_value
        dev_hl = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s = float(memory.get("_dev_smooth", raw_dev))
        dev_s = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s

        return fair_value, anchor_ema, ar_mom, dev_s

    # ── Taker gate (hysteresis + cooldown) ───────────────────────────────

    def _update_taker_gate(
        self, position: int, timestamp: int, memory: Dict[str, Any],
    ) -> Tuple[bool, bool]:
        """Returns (sell_taker_ok, buy_taker_ok).

        Two independent mechanisms:

        1. Hysteresis band (position-based):
           Sell taker deactivates when position <= -stop (default -80u).
           Re-activates only when position > -start (default -60u).
           Gap of 20u prevents the MM-vs-taker fight where 6u MM buys
           immediately enable 6u taker sells.

        2. Cooldown (time-based):
           After the taker fires, it cannot fire again for `cooldown_ticks`
           timestamps. Prevents tick-by-tick re-triggering even if the
           position briefly re-enters the hysteresis active band.
        """
        limit = self.position_limit()
        stop_pct  = float(self.params.get("ar_taker_stop_pct",  0.40))   # 80u
        start_pct = float(self.params.get("ar_taker_start_pct", 0.30))   # 60u
        cooldown  = int(self.params.get("taker_cooldown_ticks", 10))      # ticks
        stop  = int(stop_pct  * limit)
        start = int(start_pct * limit)

        sell_ok = bool(memory.get("_sell_taker_active", True))
        buy_ok  = bool(memory.get("_buy_taker_active",  True))

        # Short side hysteresis
        if sell_ok and position <= -stop:
            sell_ok = False
        elif not sell_ok and position > -start:
            sell_ok = True

        # Long side hysteresis (symmetric)
        if buy_ok and position >= stop:
            buy_ok = False
        elif not buy_ok and position < start:
            buy_ok = True

        # Cooldown gate (applied on top of hysteresis)
        if cooldown > 0:
            last_sell = int(memory.get("_sell_last_ts", -999999))
            last_buy  = int(memory.get("_buy_last_ts",  -999999))
            ts_increment = int(self.params.get("ts_increment", 100))
            ticks_since_sell = (timestamp - last_sell) // ts_increment
            ticks_since_buy  = (timestamp - last_buy)  // ts_increment
            if ticks_since_sell < cooldown:
                sell_ok = False
            if ticks_since_buy < cooldown:
                buy_ok = False

        memory["_sell_taker_active"] = sell_ok
        memory["_buy_taker_active"]  = buy_ok
        memory["_hysteresis_stop"]   = stop
        memory["_hysteresis_start"]  = start
        return sell_ok, buy_ok

    # ── AR takers with hysteresis gate ────────────────────────────────────

    def _ar_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
        sell_ok: bool,
        buy_ok: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int, int]:
        take_edge = float(self.params.get("ar_taker_edge", 15.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.30))
        taker_size = max(1, int(taker_size_pct * self.position_limit()))

        orders: List[Order] = []
        bought = sold = 0

        if buy_ok:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fair_value - take_edge or buy_cap <= 0:
                    break
                avail = -order_depth.sell_orders[ask_p]
                qty = min(avail, buy_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, ask_p, qty))
                    buy_cap -= qty
                    bought += qty

        if sell_ok:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fair_value + take_edge or sell_cap <= 0:
                    break
                avail = order_depth.buy_orders[bid_p]
                qty = min(avail, sell_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, bid_p, -qty))
                    sell_cap -= qty
                    sold += qty

        return orders, buy_cap, sell_cap, bought, sold

    # ── Inventory-skewed passive MM ───────────────────────────────────────

    def _mm_passive(
        self,
        book: BookSnapshot,
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Bestquote MM with asymmetric inventory skew.

        When short (position < 0): raise bid by floor(inv_skew_ticks × |pos/limit|)
        ticks above best_bid+1. This makes bids more competitive during uptrends,
        capturing pullbacks faster. The ask side stays unaffected so we don't
        accidentally add to a short position.
        Symmetric logic when long.
        """
        limit = self.position_limit()
        base_size    = int(self.params.get("mm_base_size", 20))
        inv_skew_max = float(self.params.get("inv_skew_ticks", 8))

        inv_ratio = position / max(1, limit)  # in [-1, 1]
        bid_size = max(0, int(base_size * (1.0 - inv_ratio)))
        ask_size = max(0, int(base_size * (1.0 + inv_ratio)))

        # Asymmetric skew: only improve the inventory-reducing side
        if position < 0:
            skew = int(inv_skew_max * abs(inv_ratio))
            bid_px = (book.best_bid + 1 + skew) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1)         if book.best_ask is not None else None
        elif position > 0:
            skew = int(inv_skew_max * abs(inv_ratio))
            bid_px = (book.best_bid + 1)         if book.best_bid is not None else None
            ask_px = (book.best_ask - 1 - skew)  if book.best_ask is not None else None
        else:
            bid_px = (book.best_bid + 1) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1) if book.best_ask is not None else None

        # Prevent self-crossing (can happen when skew pushes bid up to ask)
        if bid_px is not None and ask_px is not None and bid_px >= ask_px:
            bid_px = book.best_bid if book.best_bid is not None else (ask_px - 1 if ask_px else None)
            if bid_px is not None and ask_px is not None and bid_px >= ask_px:
                bid_px = ask_px - 1

        bid_qty = min(bid_size, buy_cap)
        ask_qty = min(ask_size, sell_cap)

        orders: List[Order] = []
        if bid_qty > 0 and bid_px is not None:
            orders.append(Order(self.product, bid_px,  bid_qty))
        if ask_qty > 0 and ask_px is not None:
            orders.append(Order(self.product, ask_px, -ask_qty))

        return orders, bid_qty, ask_qty

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

        limit = self.position_limit()
        fast_mid = self._compute_fast_mid(float(mid), memory)
        fair_value, anchor_val, ar_mom, dev = self._update_slow_ar(float(mid), position, memory)

        sell_ok, buy_ok = self._update_taker_gate(position, state.timestamp, memory)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        taker_orders, buy_cap, sell_cap, t_bought, t_sold = self._ar_takers(
            order_depth, fair_value, position, sell_ok, buy_ok, buy_cap, sell_cap,
        )

        # Record last fire timestamp for cooldown
        if t_sold > 0:
            memory["_sell_last_ts"] = state.timestamp
        if t_bought > 0:
            memory["_buy_last_ts"] = state.timestamp

        mm_orders, mm_bid_qty, mm_ask_qty = self._mm_passive(
            book, position, buy_cap, sell_cap,
        )

        all_orders = taker_orders + mm_orders

        stop  = int(float(self.params.get("ar_taker_stop_pct",  0.40)) * limit)
        start = int(float(self.params.get("ar_taker_start_pct", 0.15)) * limit)

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":       position,
                "mid":            round(float(mid), 2),
                "fast_mid":       round(fast_mid, 2),
                "FairValue":      round(fair_value, 2),
                "Anchor":         round(anchor_val, 2),
                "DevSmooth":      round(dev, 3),
                "ar_mom":         round(ar_mom, 4),
                "sell_taker_ok":  int(sell_ok),
                "buy_taker_ok":   int(buy_ok),
                "taker_buy":      t_bought,
                "taker_sell":     t_sold,
                "mm_bid_qty":     mm_bid_qty,
                "mm_ask_qty":     mm_ask_qty,
                "hyst_stop":      stop,
                "hyst_start":     start,
            },
        )

        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))          is not None: out["FairValue"]      = float(v)
        if (v := memory.get("_dev_smooth"))          is not None: out["DevSmooth"]      = float(v)
        if (v := memory.get("_anchor_ema"))          is not None: out["Anchor"]         = float(v)
        if (v := memory.get("_ar_momentum"))         is not None: out["ar_mom"]         = float(v)
        if (v := memory.get("_fast_mid"))            is not None: out["fast_mid"]       = float(v)
        if (v := memory.get("_sell_taker_active"))   is not None: out["sell_taker_ok"]  = float(v)
        if (v := memory.get("_buy_taker_active"))    is not None: out["buy_taker_ok"]   = float(v)
        if (v := memory.get("_hysteresis_stop"))     is not None: out["hyst_stop"]      = float(v)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'anchor_alpha': 0.005,
                   'anchor_pos_threshold': 0.2,
                   'anchor_price': 10000,
                   'ar_gain': 8.0,
                   'ar_smooth_half_life': 5,
                   'ar_taker_edge': 15.0,
                   'ar_taker_size_pct': 0.3,
                   'ar_taker_start_pct': 0.38,
                   'ar_taker_stop_pct': 0.4,
                   'dev_smooth_half_life': 5,
                   'fast_mid_half_life': 5,
                   'inv_skew_ticks': 4,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'mid_smooth_half_life': 20,
                   'mm_base_size': 20,
                   'position_limit': 200,
                   'quote_trace_enabled': True,
                   'strategy': 'hydro_mv_v8',
                   'taker_cooldown_ticks': 20}}

STRATEGY_CLASSES = {"hydro_mv_v8": HydroMVV8}

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
