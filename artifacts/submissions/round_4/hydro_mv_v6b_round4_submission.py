from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from datamodel import TradingState
from typing import Any, Dict
from typing import Any, Dict, List, Optional
from typing import Any, Dict, List, Optional, Set, Tuple
from typing import Any, Dict, List, Optional, Tuple
from typing import Any, Dict, List, Tuple
from typing import Any, Mapping
from typing import List, Sequence, Tuple, Optional
from typing import List, Tuple
import json
import math
import statistics

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


# ── prosperity/strategies/round_4/tibo/hydro_mv_v6.py ─────────────────────────────

class HydroMVV6(BaseStrategy):

    # ── Dynamic anchor ────────────────────────────────────────────────────

    def _update_anchor(self, raw_mid: float, position: int, memory: Dict[str, Any]) -> float:
        mode         = str(self.params.get("anchor_mode", "fixed"))
        anchor_fixed = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.02))
        anchor_ema   = float(memory.get("_anchor_ema", anchor_fixed))

        if mode == "fixed":
            # Original v5: barely moves (drift_bound keeps it ≈ anchor_fixed)
            drift_bound = float(self.params.get("anchor_drift_bound", 1.5))
            if anchor_alpha > 0:
                anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
            if drift_bound > 0:
                anchor_ema = max(anchor_fixed - drift_bound,
                                 min(anchor_fixed + drift_bound, anchor_ema))

        elif mode == "slow_ewma":
            # Unclamped slow EWMA — drifts to new regime over time.
            # anchor_alpha controls adaptation speed; no drift_bound cap.
            if anchor_alpha > 0:
                anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema

        elif mode == "rolling_median":
            # Rolling window median. Adapts when price spends time at new level.
            window = int(self.params.get("anchor_window", 500))
            buf = list(memory.get("_anchor_buf", []))
            buf.append(raw_mid)
            if len(buf) > window:
                buf = buf[-window:]
            memory["_anchor_buf"] = buf
            anchor_ema = statistics.median(buf)

        elif mode == "regime_switch":
            # Two-speed anchor: slow normally, fast when price has trended
            # away from anchor for >= regime_ticks consecutive ticks.
            regime_threshold = float(self.params.get("anchor_regime_threshold", 10.0))
            regime_ticks     = int(self.params.get("anchor_regime_ticks", 20))
            fast_alpha       = float(self.params.get("anchor_fast_alpha", 0.1))

            dist     = raw_mid - anchor_ema
            prev_mid = float(memory.get("_anchor_prev_mid", raw_mid))
            delta    = raw_mid - prev_mid
            memory["_anchor_prev_mid"] = raw_mid

            # "Trending away": price outside threshold band AND delta pushes further out
            trending_away = abs(dist) > regime_threshold and (dist * delta) >= 0
            streak = int(memory.get("_anchor_trend_streak", 0))
            streak = streak + 1 if trending_away else max(0, streak - 1)
            memory["_anchor_trend_streak"] = streak

            effective_alpha = fast_alpha if streak >= regime_ticks else anchor_alpha
            anchor_ema = effective_alpha * raw_mid + (1.0 - effective_alpha) * anchor_ema
            memory["_anchor_regime_active"] = int(streak >= regime_ticks)

        elif mode == "inv_protected":
            # Only update anchor when |position| is small (we're near flat).
            # When positioned heavily, freeze: we need the old reference to exit.
            limit         = self.position_limit()
            pos_threshold = float(self.params.get("anchor_pos_threshold", 0.3))
            if limit > 0 and abs(position) < limit * pos_threshold:
                anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
            # else: freeze anchor_ema unchanged

        memory["_anchor_ema"] = anchor_ema
        return anchor_ema

    # ── AR model ──────────────────────────────────────────────────────────

    def _update_ar(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        ms_hl    = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms  = memory.get("_mid_smooth")
        mid_s    = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        anchor_ema = self._update_anchor(raw_mid, position, memory)

        ar_hl    = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta    = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom   = float(memory.get("_ar_momentum", 0.0))
        ar_mom   = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        ar_gain    = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev  = mid_s - fair_value
        dev_hl   = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s    = float(memory.get("_dev_smooth", raw_dev))
        dev_s    = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s
        memory["_dev_raw"]    = raw_dev
        return mid_s, fair_value, dev_s

    # ── Mark 14 tracking ─────────────────────────────────────────────────

    def _update_m14(self, state: TradingState, memory: Dict[str, Any]) -> int:
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:    net += trade.quantity
            elif trade.seller == trader: net -= trade.quantity
        signal = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_signal"] = signal
        return signal

    # ── Sizing ────────────────────────────────────────────────────────────

    def _passive_sizes(self, position: int) -> Tuple[float, float]:
        limit    = self.position_limit()
        base     = float(self.params.get("maker_size_base_pct", 0.15)) * limit
        inv_bias = self.params.get("use_inventory_bias", True)
        if inv_bias and limit > 0:
            bid_size = base * (1.0 - position / limit)
            ask_size = base * (1.0 + position / limit)
        else:
            bid_size = ask_size = base
        return max(0.0, bid_size), max(0.0, ask_size)

    # ── Passive quoting ───────────────────────────────────────────────────

    def _passive_quotes(
        self,
        book: BookSnapshot,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        dev: float,
    ) -> List[Order]:
        if not self.params.get("passive_quoting", True):
            return []
        bid_price = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price = (book.best_ask - 1) if book.best_ask is not None else None

        if self.params.get("use_ar_quote_bias", False) and bid_price and ask_price:
            bias_ticks = int(self.params.get("ar_quote_bias_ticks", 2))
            if dev > 0:
                ask_price = max(book.best_bid + 1 if book.best_bid else ask_price,
                                ask_price - bias_ticks)
            elif dev < 0:
                bid_price = min(book.best_ask - 1 if book.best_ask else bid_price,
                                bid_price + bias_ticks)

        if bid_price is not None and ask_price is not None and bid_price >= ask_price:
            bid_price = ask_price - 1

        limit    = self.position_limit()
        hard_pct = float(self.params.get("pct_kept_for_takers", 0.2))
        if abs(position) >= limit * (1.0 - hard_pct):
            if position > 0: bid_size  = 0.0
            else:            ask_size  = 0.0

        orders: List[Order] = []
        qty_bid = min(buy_cap,  int(bid_size))
        qty_ask = min(sell_cap, int(ask_size))
        if qty_bid > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price,  qty_bid))
        if qty_ask > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -qty_ask))
        return orders

    # ── AR takers ─────────────────────────────────────────────────────────

    def _ar_takers(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        fair_value: float,
        dev: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        if not self.params.get("use_ar_taker", False):
            return [], buy_cap, sell_cap, set(), set()

        take_edge      = float(self.params.get("ar_taker_edge", 1.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.3))
        orders: List[Order] = []
        buy_px:  Set[int] = set()
        sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fair_value - take_edge or buy_cap <= 0:
                break
            avail = -order_depth.sell_orders[ask_p]
            qty   = min(avail, buy_cap, max(1, int(bid_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fair_value + take_edge or sell_cap <= 0:
                break
            avail = order_depth.buy_orders[bid_p]
            qty   = min(avail, sell_cap, max(1, int(ask_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, buy_px, sell_px

    # ── Anchor guard (v5 guard feature, optional) ─────────────────────────

    def _guard_allows_taker(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> bool:
        if not self.params.get("use_anchor_guard", False):
            return True
        anchor    = float(memory.get("_anchor_ema", self.params.get("anchor_price", 10000)))
        prev_mid  = memory.get("_guard_prev_mid", raw_mid)
        memory["_guard_prev_mid"] = raw_mid
        raw_delta = raw_mid - float(prev_mid)
        alpha     = float(self.params.get("guard_trend_alpha", 0.3))
        trend_ema = float(memory.get("_guard_trend_ema", raw_delta))
        trend_ema = alpha * raw_delta + (1.0 - alpha) * trend_ema
        memory["_guard_trend_ema"] = trend_ema
        dist      = raw_mid - anchor
        threshold = float(self.params.get("guard_reversion_threshold", 3.0))
        max_dist  = float(self.params.get("guard_max_dist", 80.0))
        reverting = abs(dist) <= max_dist and (dist * trend_ema <= -threshold)
        near      = abs(dist) <= float(self.params.get("guard_near_band", 0.5))
        inv_dist  = float(self.params.get("guard_inventory_dist", 40.0))
        wrong_way = (position > 0 and dist < -inv_dist) or (position < 0 and dist > inv_dist)
        guard_on  = (near or reverting) and not wrong_way
        memory["_guard_on"] = int(guard_on)
        return guard_on

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

        # Store position so _update_anchor (inv_protected) can read it
        memory["_last_position"] = position

        mid_s, fair_value, dev = self._update_ar(float(mid), position, memory)
        sigma  = self._update_volatility(float(mid), memory)
        signal = self._update_m14(state, memory)

        if book.best_bid is not None: memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None: memory["_prev_best_ask"] = book.best_ask

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        sell_cap_init = sell_cap
        buy_cap_init  = buy_cap

        bid_size, ask_size = self._passive_sizes(position)

        guard_ok = self._guard_allows_taker(float(mid), position, memory)

        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = (
            self._ar_takers(book, order_depth, fair_value, dev,
                            bid_size, ask_size, buy_cap, sell_cap)
            if guard_ok else ([], buy_cap, sell_cap, set(), set())
        )

        passive_orders = self._passive_quotes(
            book, bid_size, ask_size, buy_cap, sell_cap, position, dev,
        )
        all_orders = taker_orders + passive_orders

        taker_sold   = sum(-o.quantity for o in taker_orders if o.quantity < 0)
        taker_bought = sum( o.quantity for o in taker_orders if o.quantity > 0)
        anchor_val   = float(memory.get("_anchor_ema", self.params.get("anchor_price", 10000)))

        # Per-tick quote trace — accumulated in memory and flushed every log_flush_ts.
        # Captures all signals needed to diagnose position build-up in live.
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":     position,
                "mid":          round(float(mid), 2),
                "FairValue":    round(fair_value, 2),
                "Anchor":       round(anchor_val, 2),
                "DevSmooth":    round(dev, 3),
                "ar_mom":       round(float(memory.get("_ar_momentum", 0.0)), 4),
                "guard":        int(guard_ok),
                "M14Signal":    signal,
                "taker_sell":   taker_sold,
                "taker_buy":    taker_bought,
                "bid_size":     int(bid_size),
                "ask_size":     int(ask_size),
                "sigma":        round(sigma, 4),
            },
        )

        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))   is not None: out["FairValue"] = float(v)
        if (v := memory.get("_dev_smooth"))   is not None: out["DevSmooth"] = float(v)
        if (v := memory.get("_m14_signal"))   is not None: out["M14Signal"] = float(v)
        if (v := memory.get("_anchor_ema"))   is not None: out["Anchor"]    = float(v)
        if (v := memory.get("_ar_momentum"))  is not None: out["ar_mom"]    = float(v)
        if (v := memory.get("_guard_on"))     is not None: out["guard"]     = float(v)
        return out


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


# ── prosperity/options/time.py ────────────────────────────────────────────────────

DEFAULT_TIMESTAMP_UNITS_PER_DAY = 1_000_000.0
DEFAULT_TS_INCREMENT = 100.0
MIN_TTE_DAYS = 0.01


def timestamp_units_per_day_from_params(params: Mapping[str, Any]) -> float:
    """Resolve how many raw timestamp units make one Prosperity day."""

    explicit = params.get("timestamp_units_per_day")
    if explicit is not None:
        return max(float(explicit), 1.0)

    ticks_per_day = float(params.get("ticks_per_day", DEFAULT_TIMESTAMP_UNITS_PER_DAY / DEFAULT_TS_INCREMENT))
    ts_increment = float(params.get("ts_increment", DEFAULT_TS_INCREMENT))
    return max(ticks_per_day * ts_increment, 1.0)


def time_to_expiry_days(
    timestamp: int | float,
    initial_tte_days: int | float,
    *,
    timestamp_units_per_day: int | float = DEFAULT_TIMESTAMP_UNITS_PER_DAY,
    min_tte_days: int | float = MIN_TTE_DAYS,
) -> float:
    """Return remaining option TTE in days at a raw IMC timestamp."""

    elapsed_days = max(float(timestamp), 0.0) / max(float(timestamp_units_per_day), 1.0)
    return max(float(min_tte_days), float(initial_tte_days) - elapsed_days)


def resolve_initial_tte_days(
    trader_data: str,
    default_tte_days: int | float,
    historical_tte_by_day: Mapping[Any, Any] | None = None,
) -> float:
    """Use backtest day metadata when present, otherwise return live default."""

    if not historical_tte_by_day or not trader_data:
        return float(default_tte_days)

    try:
        loaded = json.loads(trader_data)
    except Exception:
        return float(default_tte_days)
    if not isinstance(loaded, dict):
        return float(default_tte_days)

    meta = loaded.get("_backtest")
    if not isinstance(meta, dict) or "day" not in meta:
        return float(default_tte_days)

    day = meta.get("day")
    candidate_keys = [day, str(day)]
    try:
        candidate_keys.append(int(day))
    except (TypeError, ValueError):
        pass

    for key in candidate_keys:
        if key in historical_tte_by_day:
            try:
                return float(historical_tte_by_day[key])
            except (TypeError, ValueError):
                return float(default_tte_days)

    return float(default_tte_days)


# ── prosperity/options/black_scholes.py ───────────────────────────────────────────

# ── Normal CDF and PDF (pure Python, Abramowitz & Stegun approx) ──────────────

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _norm_cdf(x: float) -> float:
    # math.erf gives enough precision for option pricing
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ── d1 / d2 helpers ───────────────────────────────────────────────────────────

def _d1_d2(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0):
    """Return (d1, d2). Returns (None, None) if inputs invalid (T<=0 or sigma<=0)."""
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return None, None
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return d1, d2


# ── Call pricing and greeks ───────────────────────────────────────────────────

def call_price(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """European call price. Returns intrinsic value if T<=0 or sigma<=0."""
    if T <= 0.0 or sigma <= 0.0:
        return max(0.0, S - K)
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return max(0.0, S - K)
    return S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def call_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """dC/dS. Approaches 1 deep ITM, 0 deep OTM, 0.5 ATM-ish."""
    if T <= 0.0 or sigma <= 0.0:
        return 1.0 if S > K else (0.0 if S < K else 0.5)
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.5
    return math.exp(-q * T) * _norm_cdf(d1)


def call_gamma(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """d2C/dS2. Peaks near ATM with short T."""
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    return math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def call_vega(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """dC/dsigma. Per 1.0 change in sigma (i.e. not %). Peaks near ATM."""
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    return S * math.exp(-q * T) * _norm_pdf(d1) * math.sqrt(T)


def call_theta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """dC/dt. Per 1 day of time decay. Usually negative for long calls."""
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    term1 = -S * _norm_pdf(d1) * sigma * math.exp(-q * T) / (2.0 * math.sqrt(T))
    term2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
    term3 = q * S * math.exp(-q * T) * _norm_cdf(d1)
    return term1 + term2 + term3


# ── Put pricing (via put-call parity) ─────────────────────────────────────────

def put_price(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """European put price."""
    c = call_price(S, K, T, sigma, r, q)
    return c - S * math.exp(-q * T) + K * math.exp(-r * T)


def put_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    """dP/dS = call_delta - e^(-q*T)."""
    return call_delta(S, K, T, sigma, r, q) - math.exp(-q * T)


# ── prosperity/options/implied_vol.py ─────────────────────────────────────────────

# ── Newton-Raphson implied vol (call) ─────────────────────────────────────────

def call_implied_vol(
    target_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    *,
    sigma_init: float = 0.02,
    tol: float = 1e-5,
    max_iter: int = 30,
    sigma_min: float = 1e-5,
    sigma_max: float = 5.0,
) -> float | None:
    """Invert Black-Scholes to get sigma from a call price.

    Returns None if convergence fails or target price is outside no-arbitrage bounds.
    """
    import math

    if T <= 0.0 or S <= 0.0 or K <= 0.0:
        return None
    # No-arbitrage bounds: max(S e^-qT - K e^-rT, 0) <= C <= S e^-qT
    lower_bound = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
    upper_bound = S * math.exp(-q * T)
    if target_price < lower_bound - 1e-6 or target_price > upper_bound + 1e-6:
        return None

    # Newton-Raphson first
    sigma = sigma_init
    for _ in range(max_iter):
        price = call_price(S, K, T, sigma, r, q)
        diff = price - target_price
        if abs(diff) < tol:
            return sigma
        vega = call_vega(S, K, T, sigma, r, q)
        if vega < 1e-10:
            break  # switch to bisection
        sigma -= diff / vega
        if sigma < sigma_min or sigma > sigma_max:
            break  # switch to bisection

    # Bisection fallback
    lo, hi = sigma_min, sigma_max
    p_lo = call_price(S, K, T, lo, r, q)
    p_hi = call_price(S, K, T, hi, r, q)
    if p_lo > target_price or p_hi < target_price:
        return None
    for _ in range(max_iter * 2):
        mid = 0.5 * (lo + hi)
        p_mid = call_price(S, K, T, mid, r, q)
        if abs(p_mid - target_price) < tol:
            return mid
        if p_mid < target_price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ── Put implied vol (reuse put-call parity + call IV) ─────────────────────────

def put_implied_vol(
    target_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    **kwargs,
) -> float | None:
    """Invert BS to get sigma from a put price via put-call parity."""
    import math

    # Put = Call - S e^-qT + K e^-rT  ->  equivalent call price
    call_target = target_price + S * math.exp(-q * T) - K * math.exp(-r * T)
    return call_implied_vol(call_target, S, K, T, r, q, **kwargs)


# ── prosperity/options/smile.py ───────────────────────────────────────────────────

def _solve_normal_eqs(X_cols: List[List[float]], y: List[float]) -> Optional[List[float]]:
    """Ordinary least squares: solve (X^T X) beta = X^T y for small matrices.

    X_cols is a list of columns (each column is a list of same length n).
    Returns beta as list[float] or None if singular.
    """
    n = len(y)
    d = len(X_cols)
    if n < d:
        return None
    # Build X^T X (d x d) and X^T y (d)
    XtX = [[0.0] * d for _ in range(d)]
    Xty = [0.0] * d
    for i in range(d):
        for j in range(d):
            s = 0.0
            for k in range(n):
                s += X_cols[i][k] * X_cols[j][k]
            XtX[i][j] = s
        s = 0.0
        for k in range(n):
            s += X_cols[i][k] * y[k]
        Xty[i] = s
    # Solve d x d via Gauss-Jordan
    M = [row[:] + [Xty[i]] for i, row in enumerate(XtX)]  # augmented
    for i in range(d):
        # Partial pivot
        max_row = i
        for r in range(i + 1, d):
            if abs(M[r][i]) > abs(M[max_row][i]):
                max_row = r
        M[i], M[max_row] = M[max_row], M[i]
        if abs(M[i][i]) < 1e-12:
            return None
        pivot = M[i][i]
        for c in range(d + 1):
            M[i][c] /= pivot
        for r in range(d):
            if r != i:
                factor = M[r][i]
                for c in range(d + 1):
                    M[r][c] -= factor * M[i][c]
    return [M[i][d] for i in range(d)]


# ── Smile fit ─────────────────────────────────────────────────────────────────

def fit_smile_poly(
    strikes: Sequence[float],
    vols: Sequence[float],
    S: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    *,
    degree: int = 2,
    min_points: int = 3,
) -> Optional[List[float]]:
    """Fit polynomial smile sigma(m) = sum(a_i * m^i) where m = ln(K/F).

    Args:
        strikes: iterable of strike prices
        vols:    iterable of matching implied vols (skip None values)
        S, T, r, q: BS inputs to compute forward F = S * e^((r-q)*T)
        degree: polynomial degree (2 = quadratic smile, default)
        min_points: require at least this many valid (K, vol) pairs

    Returns:
        list of coefficients [a0, a1, ..., a_degree], or None if fit failed.
    """
    F = S * math.exp((r - q) * T)
    ms: List[float] = []
    sigs: List[float] = []
    for K, v in zip(strikes, vols):
        if v is None or v <= 0.0 or K <= 0.0:
            continue
        ms.append(math.log(K / F))
        sigs.append(float(v))
    if len(ms) < max(min_points, degree + 1):
        return None
    # Build design matrix columns [1, m, m^2, ...]
    cols: List[List[float]] = []
    for d in range(degree + 1):
        cols.append([m ** d for m in ms])
    return _solve_normal_eqs(cols, sigs)


def smile_predict(
    K: float,
    coeffs: Sequence[float],
    S: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
) -> float:
    """Evaluate smile sigma at strike K using fitted polynomial."""
    F = S * math.exp((r - q) * T)
    m = math.log(K / F)
    sig = 0.0
    for i, a in enumerate(coeffs):
        sig += a * (m ** i)
    return max(1e-5, sig)


def average_vol(vols: Sequence[Optional[float]]) -> Optional[float]:
    """Robust average of a list of implied vols (ignore None/invalid)."""
    valid = [v for v in vols if v is not None and v > 0.0]
    if not valid:
        return None
    return sum(valid) / len(valid)


# ── prosperity/options/coordinator.py ─────────────────────────────────────────────

# ── Module-level state (safe in Prosperity single-threaded sandbox) ───────────

_STATE: Dict[str, Any] = {
    "ts": None,          # int — timestamp of current tick
    "smile": None,       # List[float] or None — last computed smile coeffs
    "spot": {},          # dict: underlying_symbol -> float mid
    "positions": {},     # dict: product -> int position (published by strategies)
}


def _ensure_current_tick(ts: int) -> None:
    """Clear per-tick caches if the timestamp has advanced."""
    if _STATE["ts"] != ts:
        _STATE["ts"] = ts
        _STATE["smile"] = None
        _STATE["spot"] = {}
        _STATE["positions"] = {}


# ── Spot ──────────────────────────────────────────────────────────────────────

def get_spot(state: TradingState, *, underlying: str) -> Optional[float]:
    """Return mid-price of the underlying, caching the result for this tick."""
    ts = int(state.timestamp)
    _ensure_current_tick(ts)
    cached = _STATE["spot"].get(underlying)
    if cached is not None:
        return cached
    od = state.order_depths.get(underlying)
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    bb = max(od.buy_orders.keys())
    ba = min(od.sell_orders.keys())
    spot = 0.5 * (bb + ba)
    _STATE["spot"][underlying] = spot
    return spot


# ── Smile ─────────────────────────────────────────────────────────────────────

def get_smile(
    state: TradingState,
    *,
    strikes: List[int],
    strike_prefix: str,
    S: float,
    T: float,
    sigma_floor: float,
    sigma_cap: float,
    prior_vol: float,
    degree: int = 2,
) -> Optional[List[float]]:
    """Return smile coefficients fitted across all strikes at this tick.

    Fits once per tick. Subsequent calls in the same tick return the cached
    result regardless of which strike asked.

    Args:
        state: current TradingState (for order_depths)
        strikes: iterable of strike prices to consider
        strike_prefix: e.g. "VEV_" so "VEV_5000" resolves from strike 5000
        S, T: spot + time to expiry for BS
        sigma_floor/sigma_cap: IV bounds for validity
        prior_vol: initial guess for IV solver
        degree: polynomial degree in log-moneyness (default 2)
    """
    ts = int(state.timestamp)
    _ensure_current_tick(ts)
    if _STATE["smile"] is not None:
        return _STATE["smile"]

    valid_strikes: List[float] = []
    valid_vols: List[float] = []
    for K in strikes:
        sym = f"{strike_prefix}{K}"
        od = state.order_depths.get(sym)
        if not od or not od.buy_orders or not od.sell_orders:
            continue
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        mid = 0.5 * (bb + ba)
        iv = call_implied_vol(mid, S, float(K), T, sigma_init=prior_vol)
        if iv is not None and sigma_floor <= iv <= sigma_cap:
            valid_strikes.append(float(K))
            valid_vols.append(iv)

    coeffs: Optional[List[float]] = None
    if len(valid_strikes) >= 3:
        coeffs = fit_smile_poly(valid_strikes, valid_vols, S, T, degree=degree)

    _STATE["smile"] = coeffs
    return coeffs


# ── Position registry (used by delta hedger) ──────────────────────────────────

def publish_position(ts: int, product: str, position: int) -> None:
    """Record current position for `product`. Called by each strategy per tick."""
    _ensure_current_tick(ts)
    _STATE["positions"][product] = int(position)


def get_positions(ts: int) -> Dict[str, int]:
    """Return snapshot of published positions for the given tick (dict copy)."""
    _ensure_current_tick(ts)
    return dict(_STATE["positions"])


# ── Debug / introspection ─────────────────────────────────────────────────────

def snapshot() -> Dict[str, Any]:
    """Return a shallow copy of current state (debug / testing)."""
    return {
        "ts": _STATE["ts"],
        "smile_present": _STATE["smile"] is not None,
        "spot_keys": list(_STATE["spot"].keys()),
        "positions": dict(_STATE["positions"]),
    }


def reset() -> None:
    """Clear all state. Intended for tests / between backtest runs."""
    _STATE["ts"] = None
    _STATE["smile"] = None
    _STATE["spot"] = {}
    _STATE["positions"] = {}


# ── prosperity/strategies/round_3/option_mm_bs.py ─────────────────────────────────

# Default strike set for the VEV voucher series (can be overridden via params).
_DEFAULT_VEV_STRIKES: List[int] = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


class OptionMMBSStrategy(BaseStrategy):
    """European call market-maker using Black-Scholes + volatility smile."""

    # ── Entry point ──────────────────────────────────────────────────────────

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

        p = self._read_params(state)
        ts = int(state.timestamp)

        # Publish our current position to the coordinator so the hedger can read it.
        publish_position(ts, self.product, position)

        # 1. Resolve underlying spot (shared across all VEV_xxxx this tick).
        S = self._resolve_spot(state, memory, ts)
        if S is None:
            return [], 0

        # 2. Choose sigma to price this option: smile-fit / own IV / EWMA'd.
        own_mid = 0.5 * (book.best_bid + book.best_ask)
        sigma = self._resolve_sigma(
            state=state, memory=memory, own_mid=own_mid,
            S=S, K=p["K"], T=p["T"], ts=ts, params=p,
        )

        # 3. Compute BS fair value + inventory skew.
        fair = call_price(S, p["K"], p["T"], sigma)
        self._record_diagnostics(memory, fair=fair, sigma=sigma, T=p["T"], S=S, tte0=p["tte0"])
        if fair < p["min_quote_price"]:
            memory["_skipped"] = 1
            return [], 0
        fair_skewed = fair - p["inv_bias_per_unit"] * position

        # 4. Determine quote prices (two modes: penny-improve vs BS-edged).
        bid_px, ask_px = self._compute_quotes(book, fair_skewed, p)

        # 5. Taker + passive orders.
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        if p["enable_takers"]:
            taker_orders, buy_cap, sell_cap = self._fire_takers(
                fair_skewed, book, order_depth, buy_cap, sell_cap, p,
            )
            orders.extend(taker_orders)

        orders.extend(self._post_passive(bid_px, ask_px, buy_cap, sell_cap, p["maker_size"]))
        return orders, 0

    # ── Param loading ────────────────────────────────────────────────────────

    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        """Read + normalize all params once per tick."""
        params = self.params
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(params.get("tte_days_initial", 5.0)),
            params.get("historical_tte_by_day"),
        )
        ts = int(state.timestamp)
        ts_per_day = timestamp_units_per_day_from_params(params)
        T = time_to_expiry_days(ts, tte0, timestamp_units_per_day=ts_per_day)
        return {
            "K": float(params["strike"]),
            "tte0": tte0,
            "T": max(0.01, T),
            "prior_vol": float(params.get("prior_vol", 0.02)),
            "maker_edge": int(params.get("maker_edge", 2)),
            "maker_size": int(params.get("maker_size", 20)),
            "take_edge": float(params.get("take_edge", 3.0)),
            "take_size": int(params.get("take_size", 40)),
            "use_smile": bool(params.get("use_smile", True)),
            "iv_ewma_alpha": float(params.get("iv_ewma_alpha", 0.3)),
            "sigma_floor": float(params.get("sigma_floor", 0.005)),
            "sigma_cap": float(params.get("sigma_cap", 0.10)),
            "enable_takers": bool(params.get("enable_takers", True)),
            "penny_improve_around_mkt": bool(params.get("penny_improve_around_mkt", False)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "inv_bias_per_unit": float(params.get("inv_bias_per_unit", 0.02)),
            "underlying_symbol": params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
        }

    # ── Spot resolution (delegates to coordinator) ───────────────────────────

    def _resolve_spot(
        self, state: TradingState, memory: Dict[str, Any], ts: int,
    ) -> Optional[float]:
        """Return mid-price of the underlying via the cross-product coordinator."""
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        return get_spot(state, underlying=underlying)

    # ── Sigma resolution ─────────────────────────────────────────────────────

    def _resolve_sigma(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        own_mid: float,
        S: float,
        K: float,
        T: float,
        ts: int,
        params: Dict[str, Any],
    ) -> float:
        """Return sigma to use for BS pricing of this option at this tick."""
        # 1. EWMA-smooth our own implied vol (always compute, for diagnostics / fallback).
        iv_smooth = self._update_iv_ewma(own_mid, S, K, T, memory, params)
        # Share our IV for smile coordinator / observability.
        shared = self._shared(memory)
        shared.setdefault("vev_iv", {})[K] = iv_smooth

        # 2. Prefer smile-predicted sigma when enabled.
        if not params["use_smile"]:
            return iv_smooth
        smile = self._get_or_fit_smile(state, shared, S, T, ts, params)
        if smile is None:
            return iv_smooth
        sigma = smile_predict(K, smile, S, T)
        return max(params["sigma_floor"], min(params["sigma_cap"], sigma))

    def _update_iv_ewma(
        self,
        own_mid: float,
        S: float,
        K: float,
        T: float,
        memory: Dict[str, Any],
        params: Dict[str, Any],
    ) -> float:
        """Invert BS for our own option mid and EWMA-smooth it."""
        iv = call_implied_vol(own_mid, S, K, T, sigma_init=params["prior_vol"])
        prev = memory.get("_iv_ewma")
        valid = iv is not None and params["sigma_floor"] <= iv <= params["sigma_cap"]
        if not valid:
            return prev if prev is not None else params["prior_vol"]
        if prev is None:
            memory["_iv_ewma"] = iv
            return iv
        alpha = params["iv_ewma_alpha"]
        iv_new = alpha * iv + (1.0 - alpha) * prev
        memory["_iv_ewma"] = iv_new
        return iv_new

    def _get_or_fit_smile(
        self,
        state: TradingState,
        shared: Dict[str, Any],
        S: float,
        T: float,
        ts: int,
        params: Dict[str, Any],
    ) -> Optional[List[float]]:
        """Return smile coefficients via the cross-product coordinator.

        The coordinator caches the fit for the current tick so only one fit
        is performed regardless of which voucher triggers it first.
        """
        strikes = params.get("smile_strikes") or _DEFAULT_VEV_STRIKES
        strike_prefix = str(params.get("strike_prefix", "VEV_"))
        return get_smile(
            state,
            strikes=list(strikes),
            strike_prefix=strike_prefix,
            S=S,
            T=T,
            sigma_floor=params["sigma_floor"],
            sigma_cap=params["sigma_cap"],
            prior_vol=params["prior_vol"],
        )

    # (smile fitting delegated to prosperity.options.coordinator.get_smile)

    # ── Quote pricing ────────────────────────────────────────────────────────

    def _compute_quotes(
        self,
        book: BookSnapshot,
        fair_skewed: float,
        params: Dict[str, Any],
    ) -> Tuple[int, int]:
        """Return (bid_px, ask_px). Return -1 for a side to signal 'skip'."""
        if params["penny_improve_around_mkt"]:
            bid_px = book.best_bid + 1
            ask_px = book.best_ask - 1
        else:
            bid_px = int(round(fair_skewed - params["maker_edge"]))
            ask_px = int(round(fair_skewed + params["maker_edge"]))

        # Never post inside own book or cross the market
        if bid_px >= book.best_ask:
            bid_px = book.best_ask - 1
        if ask_px <= book.best_bid:
            ask_px = book.best_bid + 1
        bid_px = max(1, bid_px)       # floor (call options can't price below 1)
        ask_px = max(bid_px + 1, ask_px)

        # Skip markers if our theoretical quote would cross the market
        if bid_px > book.best_ask:
            bid_px = -1
        if ask_px < book.best_bid:
            ask_px = -1
        return bid_px, ask_px

    # ── Taker orders ─────────────────────────────────────────────────────────

    def _fire_takers(
        self,
        fair_skewed: float,
        book: BookSnapshot,
        order_depth: OrderDepth,
        buy_cap: int,
        sell_cap: int,
        params: Dict[str, Any],
    ) -> Tuple[List[Order], int, int]:
        """Aggressive buy/sell when market ask/bid is mispriced vs fair."""
        orders: List[Order] = []
        take_edge = params["take_edge"]
        take_size = params["take_size"]
        # Buy under fair: market ask < fair - take_edge
        if book.best_ask is not None and buy_cap > 0:
            if (fair_skewed - book.best_ask) >= take_edge:
                qty = -order_depth.sell_orders[book.best_ask]
                take_qty = min(qty, buy_cap, take_size)
                if take_qty > 0:
                    orders.append(Order(self.product, book.best_ask, take_qty))
                    buy_cap -= take_qty
        # Sell over fair: market bid > fair + take_edge
        if book.best_bid is not None and sell_cap > 0:
            if (book.best_bid - fair_skewed) >= take_edge:
                qty = order_depth.buy_orders[book.best_bid]
                take_qty = min(qty, sell_cap, take_size)
                if take_qty > 0:
                    orders.append(Order(self.product, book.best_bid, -take_qty))
                    sell_cap -= take_qty
        return orders, buy_cap, sell_cap

    # ── Passive orders ───────────────────────────────────────────────────────

    def _post_passive(
        self,
        bid_px: int,
        ask_px: int,
        buy_cap: int,
        sell_cap: int,
        maker_size: int,
    ) -> List[Order]:
        """Post one passive bid + one passive ask within remaining capacity."""
        orders: List[Order] = []
        if bid_px > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(maker_size, buy_cap)))
        if ask_px > 0 and sell_cap > 0:
            orders.append(Order(self.product, ask_px, -min(maker_size, sell_cap)))
        return orders

    # ── Utilities ────────────────────────────────────────────────────────────

    def _shared(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        """Return (creating if needed) the cross-product shared dict."""
        shared = memory.get("_shared")
        if not isinstance(shared, dict):
            shared = {}
            memory["_shared"] = shared
        return shared

    def _record_diagnostics(
        self,
        memory: Dict[str, Any],
        *,
        fair: float,
        sigma: float,
        T: float,
        S: float,
        tte0: float,
    ) -> None:
        """Write per-tick diagnostics to memory (consumed by feature_prices)."""
        memory["_bs_fair"] = fair
        memory["_sigma_use"] = sigma
        memory["_tte_days"] = T
        memory["_tte_initial_days"] = tte0
        memory["_spot"] = S

    # ── Dashboard feature hooks ──────────────────────────────────────────────

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (f := memory.get("_bs_fair")) is not None:
            out["BS_fair"] = f
        if (s := memory.get("_sigma_use")) is not None:
            out["sigma_pct"] = s * 100
        if (T := memory.get("_tte_days")) is not None:
            out["TTE_days"] = T
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'anchor_alpha': 0.005,
                   'anchor_drift_bound': 1.5,
                   'anchor_mode': 'inv_protected',
                   'anchor_pos_threshold': 0.2,
                   'anchor_price': 10000,
                   'ar_gain': 8.0,
                   'ar_smooth_half_life': 5,
                   'ar_taker_edge': 12.0,
                   'ar_taker_size_pct': 0.3,
                   'dev_smooth_half_life': 5,
                   'informed_trader_name': 'Mark 14',
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size_base_pct': 0.25,
                   'mid_smooth_half_life': 20,
                   'passive_quoting': True,
                   'pct_kept_for_takers': 0.2,
                   'position_limit': 200,
                   'quote_trace_enabled': True,
                   'strategy': 'hydro_mv_v6',
                   'use_anchor_guard': False,
                   'use_ar_quote_bias': False,
                   'use_ar_taker': True,
                   'use_gap_exploit': False,
                   'use_inventory_bias': True,
                   'use_m14_gate': False},
 'VELVETFRUIT_EXTRACT': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 30,
                         'position_limit': 200,
                         'strategy': 'naive_tight_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'VEV_4000': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 4000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_4500': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 4500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5000': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5100': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5100,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5200': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5200,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5300': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5300,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5400': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5400,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5500': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_6000': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 6000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_6500': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 6500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True}}

STRATEGY_CLASSES = {"hydro_mv_v6": HydroMVV6, "naive_tight_mm": NaiveTightMarketMakerStrategy, "option_mm_bs": OptionMMBSStrategy}

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
