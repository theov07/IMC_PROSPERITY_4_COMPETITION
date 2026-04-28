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


# ── prosperity/strategies/round_4/tibo/hydro_mv_v10.py ────────────────────────────

class HydroMVV10(BaseStrategy):

    # ── AR model (v6b inv_protected anchor, unchanged) ────────────────────

    def _update_ar(
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

    # ── Vol gate ──────────────────────────────────────────────────────────

    def _compute_vol(self, raw_mid: float, memory: Dict[str, Any]) -> float:
        prev_mid = float(memory.get("_vol_prev_mid", raw_mid))
        abs_chg = abs(raw_mid - prev_mid)
        memory["_vol_prev_mid"] = raw_mid
        hl = float(self.params.get("vol_half_life", 20))
        alpha = 1.0 - 0.5 ** (1.0 / max(hl, 1.0))
        sigma = float(memory.get("_sigma", abs_chg))
        sigma = alpha * abs_chg + (1.0 - alpha) * sigma
        memory["_sigma"] = sigma
        return sigma

    # ── M14 cumulative gate (from v9) ─────────────────────────────────────

    def _update_m14_gate(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> Tuple[int, bool]:
        """Returns (m14_cum, sell_gated_by_m14)."""
        m14_name = str(self.params.get("m14_trader", "Mark 14"))
        m38_name = str(self.params.get("m38_trader", "Mark 38"))
        m38_weight = float(self.params.get("m38_weight", 0.0))

        prev_ts = int(memory.get("_prev_timestamp", state.timestamp))
        if state.timestamp < prev_ts:
            memory["_m14_cum"] = 0
            memory["_m38_cum"] = 0
        memory["_prev_timestamp"] = state.timestamp

        m14_tick = m38_tick = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == m14_name:    m14_tick += trade.quantity
            elif trade.seller == m14_name: m14_tick -= trade.quantity
            if trade.buyer == m38_name:    m38_tick += trade.quantity
            elif trade.seller == m38_name: m38_tick -= trade.quantity

        m14_cum = int(memory.get("_m14_cum", 0)) + m14_tick
        m38_cum = int(memory.get("_m38_cum", 0)) + m38_tick
        memory["_m14_cum"] = m14_cum
        memory["_m38_cum"] = m38_cum

        informed_long = m14_cum + m38_weight * (-m38_cum)
        bullish_thr = float(self.params.get("m14_bullish_threshold", 9999))
        sell_gated = informed_long >= bullish_thr
        memory["_sell_gated_m14"] = int(sell_gated)
        return m14_cum, sell_gated

    # ── Unified hysteresis + vol/M14 gates ───────────────────────────────

    def _compute_gates(
        self, position: int, sigma: float, sell_gated_m14: bool, memory: Dict[str, Any],
    ) -> Tuple[bool, bool, bool, bool]:
        """Returns (sell_mm_ok, sell_ar_ok, buy_mm_ok, buy_ar_ok).

        Root cause of v10 live failures:
          1. MM ask + AR taker fire simultaneously → "fight": buy at 10027,
             sell at 10025. Negative spread per unit.
          2. Separate mm_deep and ar_cap created a zone where AR still fires
             after MM stopped, continuing the position build.

        Fix: UNIFIED HYSTERESIS — single state machine for ALL sells (MM + AR):
          sell_active deactivates at -sell_stop (default 80u = 40%).
          sell_active only restarts when position > -sell_restart (default 40u).
          40-unit gap between stop and restart prevents the fight:
          MM bid fills 5u → position -80→-75, sell_active stays False (75 < 40).
          AR taker can NOT re-sell. Position slowly recovers uncontested.

        Symmetric hysteresis for buys (prevents runaway long).
        Vol gate overrides with close-only mode.
        M14 gate suppresses sells before the hysteresis fires.
        """
        limit = self.position_limit()
        sell_stop    = int(float(self.params.get("sell_stop_pct",    0.40)) * limit)  # 80u
        sell_restart = int(float(self.params.get("sell_restart_pct", 0.20)) * limit)  # 40u
        buy_stop     = int(float(self.params.get("buy_stop_pct",     0.40)) * limit)
        buy_restart  = int(float(self.params.get("buy_restart_pct",  0.20)) * limit)
        vol_thr      = float(self.params.get("vol_threshold", 3.5))

        # Vol gate: close-only mode when trending fast
        if sigma >= vol_thr:
            memory["_gate_reason"] = 3
            return position > 0, position > 0, position < 0, position < 0

        # M14 gate: suppress sells when M14 is bullish
        if sell_gated_m14:
            memory["_gate_reason"] = 2
            # Buys still follow normal hysteresis
            buy_active = bool(memory.get("_buy_active", True))
            return False, False, buy_active, buy_active

        # Sell hysteresis
        sell_active = bool(memory.get("_sell_active", True))
        if sell_active and position <= -sell_stop:
            sell_active = False
        elif not sell_active and position > -sell_restart:
            sell_active = True
        memory["_sell_active"] = sell_active

        # Buy hysteresis (symmetric)
        buy_active = bool(memory.get("_buy_active", True))
        if buy_active and position >= buy_stop:
            buy_active = False
        elif not buy_active and position < buy_restart:
            buy_active = True
        memory["_buy_active"] = buy_active

        memory["_gate_reason"]   = 0
        memory["_sell_stop"]     = sell_stop
        memory["_sell_restart"]  = sell_restart
        # Both MM and AR share the same hysteresis state
        return sell_active, sell_active, buy_active, buy_active

    # ── AR takers (with stop-overshoot prevention) ────────────────────────

    def _ar_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        sell_ar_ok: bool,
        buy_ar_ok: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int, int]:
        take_edge = float(self.params.get("ar_taker_edge", 12.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.30))
        taker_size = max(1, int(taker_size_pct * self.position_limit()))

        orders: List[Order] = []
        bought = sold = 0

        if buy_ar_ok:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fair_value - take_edge or buy_cap <= 0:
                    break
                avail = -order_depth.sell_orders[ask_p]
                qty = min(avail, buy_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, ask_p, qty))
                    buy_cap -= qty
                    bought += qty

        if sell_ar_ok:
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

    # ── Passive MM (bestquote + directional cap + inventory sizing) ───────

    def _mm_passive(
        self,
        book: BookSnapshot,
        position: int,
        sell_mm_ok: bool,
        buy_mm_ok: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        limit = self.position_limit()
        base_size = float(self.params.get("maker_size_base_pct", 0.15)) * limit

        inv_ratio = position / max(1, limit)
        bid_size = max(0.0, base_size * (1.0 - inv_ratio))
        ask_size = max(0.0, base_size * (1.0 + inv_ratio))

        if not sell_mm_ok:
            ask_size = 0.0
        if not buy_mm_ok:
            bid_size = 0.0

        # Inventory skew: when deeply short, raise bid closer to mid.
        # When deeply long, lower ask. Only applied to the recovery side.
        inv_ratio_abs = abs(position) / max(1, limit)
        inv_skew_max = float(self.params.get("inv_skew_ticks", 6))
        skew = int(inv_skew_max * inv_ratio_abs)  # 0 when flat, up to inv_skew_max when max short

        if position < 0:
            bid_px = (book.best_bid + 1 + skew) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1)         if book.best_ask is not None else None
        elif position > 0:
            bid_px = (book.best_bid + 1)         if book.best_bid is not None else None
            ask_px = (book.best_ask - 1 - skew)  if book.best_ask is not None else None
        else:
            bid_px = (book.best_bid + 1) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1) if book.best_ask is not None else None

        # Never cross the spread
        if bid_px is not None and ask_px is not None and bid_px >= ask_px:
            bid_px = ask_px - 1
        if bid_px is not None and book.best_ask is not None and bid_px >= book.best_ask:
            bid_px = book.best_ask - 1

        orders: List[Order] = []
        qty_bid = min(buy_cap,  int(bid_size))
        qty_ask = min(sell_cap, int(ask_size))
        if qty_bid > 0 and bid_px is not None:
            orders.append(Order(self.product, bid_px,  qty_bid))
        if qty_ask > 0 and ask_px is not None:
            orders.append(Order(self.product, ask_px, -qty_ask))

        return orders, qty_bid, qty_ask

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

        sigma = self._compute_vol(float(mid), memory)
        fair_value, anchor_val, ar_mom, dev = self._update_ar(float(mid), position, memory)
        m14_cum, sell_gated_m14 = self._update_m14_gate(state, memory)

        sell_mm_ok, sell_ar_ok, buy_mm_ok, buy_ar_ok = self._compute_gates(
            position, sigma, sell_gated_m14, memory,
        )

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        taker_orders, buy_cap, sell_cap, t_bought, t_sold = self._ar_takers(
            order_depth, fair_value, sell_ar_ok, buy_ar_ok, buy_cap, sell_cap,
        )

        mm_orders, mm_bid_qty, mm_ask_qty = self._mm_passive(
            book, position, sell_mm_ok, buy_mm_ok, buy_cap, sell_cap,
        )

        all_orders = taker_orders + mm_orders

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":     position,
                "mid":          round(float(mid), 2),
                "FairValue":    round(fair_value, 2),
                "Anchor":       round(anchor_val, 2),
                "DevSmooth":    round(dev, 3),
                "ar_mom":       round(ar_mom, 4),
                "sigma":        round(sigma, 3),
                "m14_cum":      m14_cum,
                "gate_reason":  int(memory.get("_gate_reason", 0)),
                "sell_mm_ok":   int(sell_mm_ok),
                "sell_ar_ok":   int(sell_ar_ok),
                "taker_buy":    t_bought,
                "taker_sell":   t_sold,
                "mm_bid_qty":   mm_bid_qty,
                "mm_ask_qty":   mm_ask_qty,
            },
        )

        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))     is not None: out["FairValue"]   = float(v)
        if (v := memory.get("_dev_smooth"))     is not None: out["DevSmooth"]   = float(v)
        if (v := memory.get("_anchor_ema"))     is not None: out["Anchor"]      = float(v)
        if (v := memory.get("_ar_momentum"))    is not None: out["ar_mom"]      = float(v)
        if (v := memory.get("_sigma"))          is not None: out["sigma"]       = float(v)
        if (v := memory.get("_m14_cum"))        is not None: out["M14Cum"]      = float(v)
        if (v := memory.get("_sell_gated_m14")) is not None: out["SellGated"]   = float(v)
        if (v := memory.get("_gate_reason"))    is not None: out["GateReason"]  = float(v)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'anchor_alpha': 0.005,
                   'anchor_pos_threshold': 0.2,
                   'anchor_price': 10000,
                   'ar_gain': 8.0,
                   'ar_smooth_half_life': 5,
                   'ar_taker_edge': 12.0,
                   'ar_taker_size_pct': 0.3,
                   'buy_restart_pct': 0.3,
                   'buy_stop_pct': 0.7,
                   'dev_smooth_half_life': 5,
                   'inv_skew_ticks': 4,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'm14_bullish_threshold': 75,
                   'm14_trader': 'Mark 14',
                   'm38_trader': 'Mark 38',
                   'm38_weight': 0.0,
                   'maker_size_base_pct': 0.15,
                   'mid_smooth_half_life': 20,
                   'position_limit': 200,
                   'quote_trace_enabled': True,
                   'sell_restart_pct': 0.3,
                   'sell_stop_pct': 0.7,
                   'strategy': 'hydro_mv_v10',
                   'vol_half_life': 20,
                   'vol_threshold': 3.5}}

STRATEGY_CLASSES = {"hydro_mv_v10": HydroMVV10}

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
