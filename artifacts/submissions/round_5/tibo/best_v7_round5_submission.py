from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order
from datamodel import Order, OrderDepth, TradingState
from datamodel import Order, TradingState
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

        orders, conversions = self.compute_orders(
            state=state,
            book=book,
            order_depth=order_depth,
            position=position,
            memory=memory,
        )

        orders = self._apply_obi_size_tilt(state, position, orders, book, memory)
        orders = self._apply_vol_size_cut(state, position, orders, book, memory)
        orders = self._apply_cp_bias(state, position, orders, book, memory)
        orders = self._apply_xa(state, position, orders, book, memory)
        orders = self._apply_inventory_unwind(state, position, orders, book, memory)
        return orders, conversions

    def _apply_xa(self, state, position, orders, book, memory):
        """Cross-asset shift from source trader flow on source symbol."""
        p = self.params
        if not bool(p.get("cross_asset_enabled", False)) or not orders:
            return orders
        ss = p.get("cross_asset_source_symbol", "")
        st = p.get("cross_asset_source_trader", "")
        if not ss or not st:
            return orders
        ts = int(getattr(state, "timestamp", 0))
        buf = memory.setdefault("_xa_buf", [])
        for t in ((state.market_trades or {}).get(ss) or []):
            q = float(getattr(t, "quantity", 0))
            if q <= 0:
                continue
            if getattr(t, "buyer", "") == st:
                buf.append([ts, q])
            elif getattr(t, "seller", "") == st:
                buf.append([ts, -q])
        cut = ts - int(p.get("cross_asset_window_ts", 10000))
        while buf and buf[0][0] < cut:
            buf.pop(0)
        sig = float(p.get("cross_asset_weight", 0.0)) * sum(q for _, q in buf)
        if abs(sig) <= float(p.get("cross_asset_threshold", 5.0)):
            return orders
        mx = float(p.get("cross_asset_max_offset", 2.0))
        off = int(round(max(-mx, min(mx, sig * float(p.get("cross_asset_scale", 0.05))))))
        if off == 0:
            return orders
        bb, ba = book.best_bid, book.best_ask
        out = []
        for o in orders:
            np_ = int(o.price) + off
            if o.quantity > 0 and ba is not None and np_ >= ba:
                np_ = int(ba) - 1
            elif o.quantity < 0 and bb is not None and np_ <= bb:
                np_ = int(bb) + 1
            out.append(Order(o.symbol, np_, o.quantity))
        return out

    def _apply_vol_size_cut(self, state, position, orders, book, memory):
        """Defensive: cut sizes by `factor` when realized vol > threshold."""
        p = self.params
        if not bool(p.get("vol_size_cut_enabled", False)) or not orders or book.mid_price is None:
            return orders
        buf = memory.setdefault("_vol_buf", [])
        buf.append(float(book.mid_price))
        max_n = int(p.get("vol_size_cut_window", 50))
        if len(buf) > max_n:
            del buf[: len(buf) - max_n]
        if len(buf) < 10:
            return orders
        rets = [(buf[i] - buf[i-1]) / max(buf[i-1], 1e-9) for i in range(1, len(buf))]
        mean = sum(rets) / len(rets)
        std = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
        if std <= float(p.get("vol_size_cut_threshold", 0.005)):
            return orders
        cut = float(p.get("vol_size_cut_factor", 0.5))
        return [Order(o.symbol, o.price, int(o.quantity * cut))
                for o in orders if int(o.quantity * cut) != 0]

    def _apply_inventory_unwind(self, state, position, orders, book, memory):
        """Inventory-based unwind. Triggers when |pos|>threshold*limit, reduces toward target."""
        p = self.params
        if not bool(p.get("inv_unwind_enabled", False)):
            return orders
        limit = self.position_limit()
        if limit <= 0:
            return orders
        if abs(position) < float(p.get("inv_unwind_threshold_pct", 0.8)) * limit:
            return orders
        excess = abs(position) - int(float(p.get("inv_unwind_target_pct", 0.5)) * limit)
        if excess <= 0:
            return orders
        mode = str(p.get("inv_unwind_mode", "taker")).lower()
        new_orders = list(orders)
        if mode in ("taker", "both"):
            delta = min(excess, int(p.get("inv_unwind_max_per_tick", 10)))
            if position > 0 and book.best_bid is not None:
                qty = -min(delta, int(book.best_bid_volume or 0))
                if qty < 0:
                    new_orders.append(Order(self.product, int(book.best_bid), qty))
            elif position < 0 and book.best_ask is not None:
                qty = min(delta, int(book.best_ask_volume or 0))
                if qty > 0:
                    new_orders.append(Order(self.product, int(book.best_ask), qty))
        if mode in ("passive", "both"):
            psize = min(int(p.get("inv_unwind_passive_size", 20)), excess)
            offset = int(p.get("inv_unwind_passive_offset", 0))
            if position > 0 and book.best_ask is not None:
                price = int(book.best_ask) + offset
                if book.best_bid is not None and price <= int(book.best_bid):
                    price = int(book.best_bid) + 1
                new_orders.append(Order(self.product, price, -psize))
            elif position < 0 and book.best_bid is not None:
                price = int(book.best_bid) - offset
                if book.best_ask is not None and price >= int(book.best_ask):
                    price = int(book.best_ask) - 1
                new_orders.append(Order(self.product, price, psize))
        return new_orders

    def _apply_cp_bias(self, state, position, orders, book, memory):
        """Per-product cp_bias overlay (with optional regime gate via vol buffer)."""
        p = self.params
        if not bool(p.get("counterparty_bias_enabled", False)):
            return orders
        if bool(p.get("_cp_bias_handled_internally", False)):
            return orders
        if not orders:
            return orders
        cp_signal = self._counterparty_signal(state, memory)
        cp_threshold = float(p.get("cp_signal_threshold", 5.0))
        if abs(cp_signal) <= cp_threshold:
            return orders
        cp_max = float(p.get("cp_max_anchor_offset", 3.0))
        cp_scale = float(p.get("cp_anchor_scale_per_unit", 0.10))
        cp_offset = int(round(max(-cp_max, min(cp_max, cp_signal * cp_scale))))
        if cp_offset == 0:
            return orders
        shifted = []
        bb, ba = book.best_bid, book.best_ask
        for o in orders:
            np_ = int(o.price) + cp_offset
            if o.quantity > 0 and ba is not None and np_ >= ba:
                np_ = int(ba) - 1
            elif o.quantity < 0 and bb is not None and np_ <= bb:
                np_ = int(bb) + 1
            shifted.append(Order(o.symbol, np_, o.quantity))
        return shifted

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

    def _microprice(self, book: "BookSnapshot") -> float:
        """Volume-weighted microprice across all book levels."""
        bid_total = sum(v for _, v in book.bid_levels)
        ask_total = sum(v for _, v in book.ask_levels)
        prev = self._memory.get("_microprice_last", 0.0)
        if bid_total == 0 or ask_total == 0:
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

    # ------------------------------------------------------------------
    # Trend gate (skip mean-rev BUY in downtrend, mean-rev SELL in uptrend)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Order Book Imbalance (OBI) SIZE tilt — adjust own quote SIZES (not prices).
    # Avoids spread cost from price tilt. Captures alpha through inventory shift.
    # ------------------------------------------------------------------
    def _apply_obi_size_tilt(self, state, position, orders, book, memory):
        """L3 OBI size tilt: boost favored side, reduce opposite side."""
        p = self.params
        if not bool(p.get("obi_size_enabled", False)):
            return orders
        levels = int(p.get("obi_size_levels", 3))
        bid_total = sum(v for _, v in (book.bid_levels or [])[:levels])
        ask_total = sum(v for _, v in (book.ask_levels or [])[:levels])
        total = bid_total + ask_total
        if total == 0:
            return orders
        obi = (bid_total - ask_total) / total
        if abs(obi) < float(p.get("obi_size_threshold", 0.005)):
            return orders
        boost = float(p.get("obi_size_boost_factor", 1.5))
        reduce = float(p.get("obi_size_reduce_factor", 0.7))
        bullish = obi > 0
        adjusted = []
        for o in orders:
            if o.quantity > 0:
                factor = boost if bullish else reduce
            elif o.quantity < 0:
                factor = reduce if bullish else boost
            else:
                adjusted.append(o); continue
            new_qty = int(o.quantity * factor)
            if new_qty > 0:
                new_qty = min(new_qty, max(0, self.position_limit() - position))
            elif new_qty < 0:
                new_qty = max(new_qty, -max(0, self.position_limit() + position))
            if new_qty != 0:
                adjusted.append(Order(o.symbol, o.price, new_qty))
        return adjusted

    def _counterparty_signal(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> float:
        """Counterparty-flow weighted signal with optional volume-conditional gating.

        Maintains a rolling buffer of (timestamp, trader_id, signed_qty) for the last
        `cp_window_ts` timestamp units. Signed qty = +qty when trader is buyer, -qty
        when trader is seller. Aggregates per trader, applies a per-trader weight,
        returns weighted sum.

        Conditional gating (opt-in): for traders listed in `cp_conditional_traders`,
        only apply their full weight when their current rolling-window |net_volume|
        exceeds historical mean by `cp_conditional_zthresh` standard deviations.
        Otherwise apply `cp_conditional_baseline_weight` (default 0).

        Params:
          cp_window_ts                    : rolling window in timestamp units (default 10000)
          cp_trader_weights               : dict trader_id -> weight
          cp_conditional_traders          : list of traders to gate (default [])
          cp_conditional_zthresh          : z-score threshold (default 2.0)
          cp_conditional_stats_window_ts  : history window for stats (default 50000 = 500 ticks)
          cp_conditional_min_samples      : min samples before gating activates (default 50)
          cp_conditional_baseline_weight  : weight applied when below threshold (default 0.0)

        Returns: weighted signed signal (units = contracts).
        """
        window_ts = int(self.params.get("cp_window_ts", 10000))
        weights = self.params.get("cp_trader_weights", {
            "Mark 55": +1.0, "Mark 67": +1.0,
            "Mark 01": -1.0, "Mark 14": -1.0,
        })
        cond_traders = set(self.params.get("cp_conditional_traders", []) or [])
        cond_zthresh = float(self.params.get("cp_conditional_zthresh", 2.0))
        cond_stats_ts = int(self.params.get("cp_conditional_stats_window_ts", 50000))
        cond_min_samples = int(self.params.get("cp_conditional_min_samples", 50))
        cond_baseline = float(self.params.get("cp_conditional_baseline_weight", 0.0))

        ts_now = int(getattr(state, "timestamp", 0))

        # Append this tick's trades to rolling buffer
        buf = memory.setdefault("_cp_buf", [])  # list of [ts, trader, signed_qty]
        try:
            mt = state.market_trades
            trades = (mt or {}).get(self.product, []) or []
        except Exception:
            trades = []
        for t in trades:
            buyer = getattr(t, "buyer", None) or ""
            seller = getattr(t, "seller", None) or ""
            qty = float(getattr(t, "quantity", 0))
            if qty <= 0:
                continue
            if buyer:
                buf.append([ts_now, buyer, qty])
            if seller:
                buf.append([ts_now, seller, -qty])

        # Drop old entries
        cutoff = ts_now - window_ts
        if buf and buf[0][0] < cutoff:
            i = 0
            while i < len(buf) and buf[i][0] < cutoff:
                i += 1
            del buf[:i]

        # Aggregate per trader
        per_trader = {}
        for _, trader, signed in buf:
            per_trader[trader] = per_trader.get(trader, 0.0) + signed

        # Conditional gating: maintain stats history for designated traders
        gates = {}  # trader -> effective weight multiplier (1.0 = full, baseline/w otherwise)
        if cond_traders:
            stats_buf = memory.setdefault("_cp_stats_buf", {})
            cond_cut = ts_now - cond_stats_ts
            for trader in cond_traders:
                cur_abs = abs(per_trader.get(trader, 0.0))
                hist = stats_buf.setdefault(trader, [])
                hist.append([ts_now, cur_abs])
                while hist and hist[0][0] < cond_cut:
                    hist.pop(0)
                if len(hist) < cond_min_samples:
                    gates[trader] = 1.0  # not enough data → behave as v5 (always-on)
                    continue
                vols = [s[1] for s in hist]
                n = len(vols)
                mean = sum(vols) / n
                var = sum((v - mean) ** 2 for v in vols) / n
                std = math.sqrt(var) if var > 0 else 0.0
                z = (cur_abs - mean) / std if std > 0 else (cond_zthresh + 1 if cur_abs > 0 else 0.0)
                gates[trader] = 1.0 if z >= cond_zthresh else 0.0

        # Apply weights (with conditional gating where applicable)
        signal = 0.0
        for trader, net in per_trader.items():
            w = weights.get(trader, 0.0)
            if trader in cond_traders:
                # Linearly blend full-weight and baseline based on gate
                g = gates.get(trader, 1.0)
                w = g * w + (1.0 - g) * cond_baseline
            signal += w * net

        memory["_cp_signal"] = signal
        memory["_cp_per_trader"] = per_trader
        if cond_traders:
            memory["_cp_gates"] = gates
        return signal


# ── prosperity/strategies/round_5/tibo/ar1_mean_rev_v1.py ─────────────────────────

class AR1MeanRevV1(BaseStrategy):
    """Tick-to-tick mean-reversion strategy using the AR1 signal."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        limit = int(p.get("position_limit", 10))
        entry_thresh = float(p.get("entry_threshold", 20.0))
        taker_size = int(p.get("taker_size", 10))
        exit_ticks = int(p.get("exit_ticks", 0))    # 0 = hold until reverse signal
        passive_size = int(p.get("passive_size", 0))  # optional passive MM alongside

        mid = book.mid_price
        if mid is None:
            return [], 0

        prev_mid = memory.get("prev_mid")
        memory["prev_mid"] = mid

        if prev_mid is None:
            return [], 0

        ret = mid - prev_mid  # this tick's return
        orders: List[Order] = []
        bb = book.best_bid
        ba = book.best_ask

        buy_room = limit - position
        sell_room = limit + position

        # ── taker SELL: large up-move → expect reversion ─────────────────
        if ret >= entry_thresh and sell_room > 0 and bb is not None:
            qty = min(taker_size, sell_room)
            orders.append(Order(self.product, bb, -qty))
            sell_room -= qty

        # ── taker BUY: large down-move → expect reversion ────────────────
        elif ret <= -entry_thresh and buy_room > 0 and ba is not None:
            qty = min(taker_size, buy_room)
            orders.append(Order(self.product, ba, qty))
            buy_room -= qty

        # ── exit stale positions after exit_ticks ────────────────────────
        if exit_ticks > 0:
            ticks_held = memory.get("ticks_held", 0)
            if position != 0:
                ticks_held += 1
                if ticks_held >= exit_ticks:
                    if position > 0 and bb is not None and sell_room > 0:
                        orders.append(Order(self.product, bb, -min(position, sell_room)))
                    elif position < 0 and ba is not None and buy_room > 0:
                        orders.append(Order(self.product, ba, min(-position, buy_room)))
                    ticks_held = 0
            else:
                ticks_held = 0
            memory["ticks_held"] = ticks_held

        # ── optional passive MM alongside (narrow spread) ─────────────────
        if passive_size > 0:
            passive_half = float(p.get("passive_half_spread", 4.0))
            if buy_room > 0 and bb is not None:
                orders.append(Order(self.product, bb + 1, min(passive_size, buy_room)))
            if sell_room > 0 and ba is not None:
                orders.append(Order(self.product, ba - 1, -min(passive_size, sell_room)))

        return orders, 0


# ── prosperity/strategies/round_1/naive_tight_mm.py ───────────────────────────────

class NaiveTightMarketMakerStrategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        maker_size = int(self.params.get("maker_size", 10))
        tighten_ticks = int(self.params.get("tighten_ticks", 1))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_price = None
        ask_price = None

        if book.best_bid is not None:
            bid_price = book.best_bid
        if book.best_ask is not None:
            ask_price = book.best_ask

        if book.best_bid is not None and book.best_ask is not None:
            spread = book.best_ask - book.best_bid
            if spread >= 2:
                bid_price = min(book.best_bid + tighten_ticks, book.best_ask - 0.1)
                ask_price = max(book.best_ask - tighten_ticks, book.best_bid + 0.1)

        if bid_price is not None and buy_cap > 0:
            orders.append(Order(self.product, bid_price, min(maker_size, buy_cap)))

        if ask_price is not None and sell_cap > 0:
            orders.append(Order(self.product, ask_price, -min(maker_size, sell_cap)))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread

        # ── Per-tick log accumulation ──
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
        )

        return orders, 0


# ── prosperity/strategies/round_5/tibo/pebbles_arb_v1.py ──────────────────────────

class PebblesArbV1(BaseStrategy):
    """Basket-conservation market maker for any of the 5 PEBBLES products."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        limit = int(p.get("position_limit", 10))
        partners: List[str] = list(p["partner_products"])
        sum_target = float(p.get("sum_target", 50000.0))
        edge = float(p.get("edge_ticks", 6.0))
        passive_half = float(p.get("passive_half_spread", 7.0))
        taker_size = int(p.get("taker_size", 10))
        passive_size = int(p.get("passive_size", 5))

        # ── compute partners mid sum ───────────────────────────────────
        partners_sum = 0.0
        available = 0
        for sym in partners:
            od = state.order_depths.get(sym)
            if od is None:
                continue
            pb = list(od.buy_orders.keys())
            pa = list(od.sell_orders.keys())
            if not pb or not pa:
                continue
            partners_sum += (max(pb) + min(pa)) / 2.0
            available += 1

        if available < len(partners):
            # fall back: use last known fair value from EWMA
            mid = book.mid_price
            if mid is None:
                return [], 0
            ewma = memory.get("fair_ewma", mid)
            alpha = float(p.get("ewma_alpha", 0.01))
            ewma = alpha * mid + (1 - alpha) * ewma
            memory["fair_ewma"] = ewma
            fair_value = ewma
        else:
            fair_value = sum_target - partners_sum
            # update EWMA with current fair value for fallback continuity
            alpha = float(p.get("ewma_alpha", 0.01))
            memory["fair_ewma"] = alpha * fair_value + (1 - alpha) * memory.get("fair_ewma", fair_value)

        orders: List[Order] = []
        bb = book.best_bid
        ba = book.best_ask

        buy_room = limit - position
        sell_room = limit + position

        # ── taker BUY ─────────────────────────────────────────────────
        if ba is not None and ba <= fair_value - edge and buy_room > 0:
            qty = min(taker_size, buy_room)
            orders.append(Order(self.product, ba, qty))
            buy_room -= qty

        # ── taker SELL ────────────────────────────────────────────────
        if bb is not None and bb >= fair_value + edge and sell_room > 0:
            qty = min(taker_size, sell_room)
            orders.append(Order(self.product, bb, -qty))
            sell_room -= qty

        # ── passive BID ───────────────────────────────────────────────
        if buy_room > 0:
            bid_px = int(fair_value - passive_half)
            if bb is not None:
                bid_px = max(bid_px, bb)
            orders.append(Order(self.product, bid_px, min(passive_size, buy_room)))

        # ── passive ASK ───────────────────────────────────────────────
        if sell_room > 0:
            ask_px = int(fair_value + passive_half) + 1
            if ba is not None:
                ask_px = min(ask_px, ba)
            orders.append(Order(self.product, ask_px, -min(passive_size, sell_room)))

        return orders, 0


# ── prosperity/strategies/round_5/tibo/trend_follow_v2.py ─────────────────────────

class TrendFollowV2(BaseStrategy):
    """
    Level-based trend following for Round 5 products.

    Signal = EMA(mid, hl) - start_session_price
    - Enters max long  when signal > +entry_threshold
    - Enters max short when signal < -entry_threshold
    - Holds position until signal clearly reverses past exit_threshold
    - Optional warmup_ticks: won't enter before this many ticks have elapsed

    Using a fixed start_price (first price of each session) rather than
    a rolling reference avoids the dual-EMA noise amplification problem.

    Params:
        ema_half_life   : EMA half-life in ticks (default 100)
        threshold       : deviation from start to enter (default 80)
        exit_threshold  : deviation to close a wrong-way position (default 30)
        warmup_ticks    : ticks before first entry allowed (default 0)
        position_limit  : 10 for all R5 products
    """

    def compute_orders(
        self,
        state,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0

        mid = book.mid_price
        limit = int(self.params.get("position_limit", 10))
        hl = float(self.params.get("ema_half_life", 100))
        entry_thr = float(self.params.get("threshold", 80))
        exit_thr = float(self.params.get("exit_threshold", 30))
        min_tick = int(self.params.get("warmup_ticks", 0))

        alpha = 1.0 - 0.5 ** (1.0 / hl)

        if "start_price" not in memory:
            memory["start_price"] = mid
        if "ema" not in memory:
            memory["ema"] = mid
        tick = memory.get("tick", 0)
        memory["tick"] = tick + 1

        ema = alpha * mid + (1.0 - alpha) * memory["ema"]
        memory["ema"] = ema

        if tick < min_tick:
            return [], 0

        signal = ema - memory["start_price"]

        if signal > entry_thr:
            target = limit
        elif signal < -entry_thr:
            target = -limit
        elif position > 0 and signal < -exit_thr:
            target = 0
        elif position < 0 and signal > exit_thr:
            target = 0
        else:
            target = position  # hold

        return self._reach_target(order_depth, position, target, limit), 0

    def _reach_target(self, order_depth, position: int, target: int, limit: int) -> List[Order]:
        delta = target - position
        if delta == 0:
            return []
        orders = []
        if delta > 0 and order_depth.sell_orders:
            ask = min(order_depth.sell_orders.keys())
            avail = -order_depth.sell_orders[ask]
            qty = min(delta, avail, limit - position)
            if qty > 0:
                orders.append(Order(self.product, ask, qty))
        elif delta < 0 and order_depth.buy_orders:
            bid = max(order_depth.buy_orders.keys())
            avail = order_depth.buy_orders[bid]
            qty = min(-delta, avail, limit + position)
            if qty > 0:
                orders.append(Order(self.product, bid, -qty))
        return orders

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'GALAXY_SOUNDS_BLACK_HOLES': {'last_ts_value': 999900,
                               'log_flush_ts': 1000,
                               'maker_size': 3,
                               'position_limit': 10,
                               'strategy': 'naive_tight_mm',
                               'tighten_ticks': 1,
                               'ts_increment': 100},
 'GALAXY_SOUNDS_DARK_MATTER': {'last_ts_value': 999900,
                               'log_flush_ts': 1000,
                               'maker_size': 5,
                               'position_limit': 10,
                               'strategy': 'naive_tight_mm',
                               'tighten_ticks': 1,
                               'ts_increment': 100},
 'GALAXY_SOUNDS_PLANETARY_RINGS': {'last_ts_value': 999900,
                                   'log_flush_ts': 1000,
                                   'maker_size': 3,
                                   'position_limit': 10,
                                   'strategy': 'naive_tight_mm',
                                   'tighten_ticks': 1,
                                   'ts_increment': 100},
 'GALAXY_SOUNDS_SOLAR_FLAMES': {'last_ts_value': 999900,
                                'log_flush_ts': 1000,
                                'maker_size': 3,
                                'position_limit': 10,
                                'strategy': 'naive_tight_mm',
                                'tighten_ticks': 1,
                                'ts_increment': 100},
 'GALAXY_SOUNDS_SOLAR_WINDS': {'last_ts_value': 999900,
                               'log_flush_ts': 1000,
                               'maker_size': 3,
                               'position_limit': 10,
                               'strategy': 'naive_tight_mm',
                               'tighten_ticks': 1,
                               'ts_increment': 100},
 'MICROCHIP_CIRCLE': {'last_ts_value': 999900,
                      'log_flush_ts': 1000,
                      'maker_size': 3,
                      'position_limit': 10,
                      'strategy': 'naive_tight_mm',
                      'tighten_ticks': 1,
                      'ts_increment': 100},
 'MICROCHIP_OVAL': {'last_ts_value': 999900,
                    'log_flush_ts': 1000,
                    'maker_size': 5,
                    'position_limit': 10,
                    'strategy': 'naive_tight_mm',
                    'tighten_ticks': 1,
                    'ts_increment': 100},
 'MICROCHIP_RECTANGLE': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 3,
                         'position_limit': 10,
                         'strategy': 'naive_tight_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'MICROCHIP_SQUARE': {'ema_half_life': 100,
                      'exit_threshold': 80,
                      'last_ts_value': 999900,
                      'log_flush_ts': 1000,
                      'position_limit': 10,
                      'strategy': 'trend_follow_v2',
                      'threshold': 250,
                      'ts_increment': 100,
                      'warmup_ticks': 0},
 'MICROCHIP_TRIANGLE': {'last_ts_value': 999900,
                        'log_flush_ts': 1000,
                        'maker_size': 3,
                        'position_limit': 10,
                        'strategy': 'naive_tight_mm',
                        'tighten_ticks': 1,
                        'ts_increment': 100},
 'OXYGEN_SHAKE_CHOCOLATE': {'last_ts_value': 999900,
                            'log_flush_ts': 1000,
                            'maker_size': 5,
                            'position_limit': 10,
                            'strategy': 'naive_tight_mm',
                            'tighten_ticks': 1,
                            'ts_increment': 100},
 'OXYGEN_SHAKE_EVENING_BREATH': {'last_ts_value': 999900,
                                 'log_flush_ts': 1000,
                                 'maker_size': 5,
                                 'position_limit': 10,
                                 'strategy': 'naive_tight_mm',
                                 'tighten_ticks': 1,
                                 'ts_increment': 100},
 'OXYGEN_SHAKE_GARLIC': {'ema_half_life': 150,
                         'exit_threshold': 150,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'position_limit': 10,
                         'strategy': 'trend_follow_v2',
                         'threshold': 700,
                         'ts_increment': 100,
                         'warmup_ticks': 0},
 'OXYGEN_SHAKE_MINT': {'last_ts_value': 999900,
                       'log_flush_ts': 1000,
                       'maker_size': 3,
                       'position_limit': 10,
                       'strategy': 'naive_tight_mm',
                       'tighten_ticks': 1,
                       'ts_increment': 100},
 'OXYGEN_SHAKE_MORNING_BREATH': {'last_ts_value': 999900,
                                 'log_flush_ts': 1000,
                                 'maker_size': 5,
                                 'position_limit': 10,
                                 'strategy': 'naive_tight_mm',
                                 'tighten_ticks': 1,
                                 'ts_increment': 100},
 'PANEL_1X2': {'ema_half_life': 100,
               'exit_threshold': 30,
               'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'position_limit': 10,
               'strategy': 'trend_follow_v2',
               'threshold': 80,
               'ts_increment': 100,
               'warmup_ticks': 0},
 'PANEL_1X4': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PANEL_2X2': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PANEL_2X4': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PANEL_4X4': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 3,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PEBBLES_L': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 3,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PEBBLES_M': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 3,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PEBBLES_S': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 3,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PEBBLES_XL': {'edge_ticks': 7.0,
                'ewma_alpha': 0.05,
                'last_ts_value': 999900,
                'partner_products': ['PEBBLES_L', 'PEBBLES_M', 'PEBBLES_S', 'PEBBLES_XS'],
                'passive_half_spread': 6.0,
                'passive_size': 5,
                'position_limit': 10,
                'strategy': 'pebbles_arb_v1',
                'sum_target': 50000.0,
                'taker_size': 10},
 'PEBBLES_XS': {'ema_half_life': 150,
                'exit_threshold': 80,
                'last_ts_value': 999900,
                'log_flush_ts': 1000,
                'position_limit': 10,
                'strategy': 'trend_follow_v2',
                'threshold': 250,
                'ts_increment': 100,
                'warmup_ticks': 0},
 'ROBOT_DISHES': {'entry_threshold': 20.0,
                  'exit_ticks': 0,
                  'last_ts_value': 999900,
                  'passive_size': 0,
                  'position_limit': 10,
                  'strategy': 'ar1_mean_rev_v1',
                  'taker_size': 10},
 'ROBOT_IRONING': {'ema_half_life': 150,
                   'exit_threshold': 40,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'position_limit': 10,
                   'strategy': 'trend_follow_v2',
                   'threshold': 100,
                   'ts_increment': 100,
                   'warmup_ticks': 0},
 'ROBOT_LAUNDRY': {'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 3,
                   'position_limit': 10,
                   'strategy': 'naive_tight_mm',
                   'tighten_ticks': 1,
                   'ts_increment': 100},
 'ROBOT_MOPPING': {'ema_half_life': 150,
                   'exit_threshold': 40,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'position_limit': 10,
                   'strategy': 'trend_follow_v2',
                   'threshold': 100,
                   'ts_increment': 100,
                   'warmup_ticks': 0},
 'ROBOT_VACUUMING': {'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'maker_size': 3,
                     'position_limit': 10,
                     'strategy': 'naive_tight_mm',
                     'tighten_ticks': 1,
                     'ts_increment': 100},
 'SLEEP_POD_COTTON': {'ema_half_life': 100,
                      'exit_threshold': 30,
                      'last_ts_value': 999900,
                      'log_flush_ts': 1000,
                      'position_limit': 10,
                      'strategy': 'trend_follow_v2',
                      'threshold': 80,
                      'ts_increment': 100,
                      'warmup_ticks': 0},
 'SLEEP_POD_NYLON': {'ema_half_life': 100,
                     'exit_threshold': 30,
                     'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'position_limit': 10,
                     'strategy': 'trend_follow_v2',
                     'threshold': 80,
                     'ts_increment': 100,
                     'warmup_ticks': 0},
 'SLEEP_POD_POLYESTER': {'ema_half_life': 150,
                         'exit_threshold': 150,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'position_limit': 10,
                         'strategy': 'trend_follow_v2',
                         'threshold': 600,
                         'ts_increment': 100,
                         'warmup_ticks': 0},
 'SLEEP_POD_SUEDE': {'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'maker_size': 3,
                     'position_limit': 10,
                     'strategy': 'naive_tight_mm',
                     'tighten_ticks': 1,
                     'ts_increment': 100},
 'SNACKPACK_CHOCOLATE': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 5,
                         'position_limit': 10,
                         'strategy': 'naive_tight_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'SNACKPACK_PISTACHIO': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 5,
                         'position_limit': 10,
                         'strategy': 'naive_tight_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'SNACKPACK_RASPBERRY': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 5,
                         'position_limit': 10,
                         'strategy': 'naive_tight_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'SNACKPACK_STRAWBERRY': {'last_ts_value': 999900,
                          'log_flush_ts': 1000,
                          'maker_size': 5,
                          'position_limit': 10,
                          'strategy': 'naive_tight_mm',
                          'tighten_ticks': 1,
                          'ts_increment': 100},
 'SNACKPACK_VANILLA': {'last_ts_value': 999900,
                       'log_flush_ts': 1000,
                       'maker_size': 5,
                       'position_limit': 10,
                       'strategy': 'naive_tight_mm',
                       'tighten_ticks': 1,
                       'ts_increment': 100},
 'TRANSLATOR_ASTRO_BLACK': {'last_ts_value': 999900,
                            'log_flush_ts': 1000,
                            'maker_size': 3,
                            'position_limit': 10,
                            'strategy': 'naive_tight_mm',
                            'tighten_ticks': 1,
                            'ts_increment': 100},
 'TRANSLATOR_ECLIPSE_CHARCOAL': {'last_ts_value': 999900,
                                 'log_flush_ts': 1000,
                                 'maker_size': 3,
                                 'position_limit': 10,
                                 'strategy': 'naive_tight_mm',
                                 'tighten_ticks': 1,
                                 'ts_increment': 100},
 'TRANSLATOR_GRAPHITE_MIST': {'last_ts_value': 999900,
                              'log_flush_ts': 1000,
                              'maker_size': 3,
                              'position_limit': 10,
                              'strategy': 'naive_tight_mm',
                              'tighten_ticks': 1,
                              'ts_increment': 100},
 'TRANSLATOR_SPACE_GRAY': {'last_ts_value': 999900,
                           'log_flush_ts': 1000,
                           'maker_size': 3,
                           'position_limit': 10,
                           'strategy': 'naive_tight_mm',
                           'tighten_ticks': 1,
                           'ts_increment': 100},
 'TRANSLATOR_VOID_BLUE': {'last_ts_value': 999900,
                          'log_flush_ts': 1000,
                          'maker_size': 5,
                          'position_limit': 10,
                          'strategy': 'naive_tight_mm',
                          'tighten_ticks': 1,
                          'ts_increment': 100},
 'UV_VISOR_AMBER': {'ema_half_life': 100,
                    'exit_threshold': 30,
                    'last_ts_value': 999900,
                    'log_flush_ts': 1000,
                    'position_limit': 10,
                    'strategy': 'trend_follow_v2',
                    'threshold': 80,
                    'ts_increment': 100,
                    'warmup_ticks': 0},
 'UV_VISOR_MAGENTA': {'last_ts_value': 999900,
                      'log_flush_ts': 1000,
                      'maker_size': 3,
                      'position_limit': 10,
                      'strategy': 'naive_tight_mm',
                      'tighten_ticks': 1,
                      'ts_increment': 100},
 'UV_VISOR_ORANGE': {'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'maker_size': 5,
                     'position_limit': 10,
                     'strategy': 'naive_tight_mm',
                     'tighten_ticks': 1,
                     'ts_increment': 100},
 'UV_VISOR_RED': {'last_ts_value': 999900,
                  'log_flush_ts': 1000,
                  'maker_size': 5,
                  'position_limit': 10,
                  'strategy': 'naive_tight_mm',
                  'tighten_ticks': 1,
                  'ts_increment': 100},
 'UV_VISOR_YELLOW': {'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'maker_size': 3,
                     'position_limit': 10,
                     'strategy': 'naive_tight_mm',
                     'tighten_ticks': 1,
                     'ts_increment': 100}}

STRATEGY_CLASSES = {"ar1_mean_rev_v1": AR1MeanRevV1, "naive_tight_mm": NaiveTightMarketMakerStrategy, "pebbles_arb_v1": PebblesArbV1, "trend_follow_v2": TrendFollowV2}

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
