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


# ── prosperity/strategies/round_3/diagnostic_probe_mm.py ──────────────────────────

class DiagnosticProbeMMStrategy(BaseStrategy):
    """Live-only alpha discovery: participant tracking + adverse selection."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.mid_price is None:
            return [], 0

        ts = int(state.timestamp)
        mid = float(book.mid_price)

        # G1: Track named participants in market_trades
        self._track_participants(state, memory)

        # G2: Track adverse selection on our fills
        self._track_adverse_selection(state, memory, mid, ts)

        # Issue minimal far-quote probes to generate data
        orders, buy_cap, sell_cap = self._far_probes(
            state, book, memory,
            self.buy_capacity(position),
            self.sell_capacity(position),
        )

        memory["_prev_best_bid"] = int(book.best_bid)
        memory["_prev_best_ask"] = int(book.best_ask)
        memory["_last_mid"] = mid

        # Emit detailed trace for log analysis
        adverse_stats = memory.get("_adverse_stats", {})
        avg_adv = adverse_stats.get("avg_signed_mtm", 0.0)
        adverse_count = adverse_stats.get("adverse_count", 0)
        total_count = adverse_stats.get("total_count", 0)

        named_count = memory.get("_named_participant_count", 0)
        last_buyer = memory.get("_last_named_buyer", "")
        last_seller = memory.get("_last_named_seller", "")

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=book.best_bid,
            ask_price=book.best_ask,
            extras={
                "position": int(position),
                "fills_tracked": int(total_count),
                "adverse_count": int(adverse_count),
                "adverse_rate": round(adverse_count / total_count, 3) if total_count else 0.0,
                "avg_signed_mtm": round(avg_adv, 3),
                "named_market_trades": int(named_count),
                "last_buyer_hash": _str_hash(last_buyer),
                "last_seller_hash": _str_hash(last_seller),
                "n_far_probes": int(memory.get("_far_probe_count", 0)),
                "session_phase": _session_phase(ts),
            },
        )

        return orders, 0

    # ─── G1: Named participant tracking ───────────────────────────────────────
    def _track_participants(self, state: TradingState, memory: Dict[str, Any]) -> None:
        """Log every market_trade with non-empty buyer/seller string."""
        trades = state.market_trades.get(self.product, [])
        if not trades:
            return

        named_log: List[str] = memory.setdefault("_named_participants", [])
        max_log = int(self.params.get("participant_log_max", 30))

        for t in trades:
            buyer = str(getattr(t, "buyer", "") or "")
            seller = str(getattr(t, "seller", "") or "")
            if buyer:
                named_log.append(f"B:{buyer}@{t.timestamp}:{t.quantity}@{t.price}")
                memory["_last_named_buyer"] = buyer
                memory["_named_participant_count"] = int(memory.get("_named_participant_count", 0)) + 1
            if seller:
                named_log.append(f"S:{seller}@{t.timestamp}:{t.quantity}@{t.price}")
                memory["_last_named_seller"] = seller
                memory["_named_participant_count"] = int(memory.get("_named_participant_count", 0)) + 1

        # Bound memory
        if len(named_log) > max_log:
            del named_log[:-max_log]

    # ─── G2: Adverse selection tracking ───────────────────────────────────────
    def _track_adverse_selection(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        current_mid: float,
        ts: int,
    ) -> None:
        """For each of our fills, record (fill_price, side, ts). After
        adverse_horizon_ticks, compute signed_mtm = side * (current_mid - fill_price).
        Negative = adverse to us.
        """
        horizon_ticks = int(self.params.get("adverse_horizon_ticks", 5))
        ts_increment = int(self.params.get("ts_increment", 100))
        horizon_us = horizon_ticks * ts_increment
        max_window = int(self.params.get("adverse_max_window", 50))

        # 1) Add new own_trades to pending
        pending: List[Tuple[int, int, float, int]] = memory.setdefault("_pending_fills", [])
        for trade in state.own_trades.get(self.product, []):
            if trade.timestamp != state.timestamp - ts_increment:
                # Only fills from the IMMEDIATELY previous tick (avoid double-counting)
                continue
            side = 1 if trade.buyer == "SUBMISSION" else -1
            pending.append((int(trade.timestamp), side, float(trade.price), int(trade.quantity)))

        # 2) Resolve pending fills whose horizon has elapsed
        adverse_stats = memory.setdefault("_adverse_stats", {
            "total_signed_mtm": 0.0,
            "total_count": 0,
            "adverse_count": 0,
            "avg_signed_mtm": 0.0,
            "by_horizon_signed": [],  # list of (horizon_passed_ts, signed_mtm)
        })

        still_pending: List[Tuple[int, int, float, int]] = []
        for fill_ts, side, price, qty in pending:
            if ts >= fill_ts + horizon_us:
                signed_mtm = side * (current_mid - price) * qty
                adverse_stats["total_signed_mtm"] += signed_mtm
                adverse_stats["total_count"] += 1
                if signed_mtm < 0:
                    adverse_stats["adverse_count"] += 1
                # Bounded history
                hist = adverse_stats["by_horizon_signed"]
                hist.append([ts, round(signed_mtm, 2)])
                if len(hist) > max_window:
                    del hist[: len(hist) - max_window]
            else:
                still_pending.append((fill_ts, side, price, qty))
        memory["_pending_fills"] = still_pending

        if adverse_stats["total_count"] > 0:
            adverse_stats["avg_signed_mtm"] = (
                adverse_stats["total_signed_mtm"] / adverse_stats["total_count"]
            )

    # ─── Minimal far-quote probes (data generation only) ──────────────────────
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
            if sell_cap > 0:
                ask_px = int(book.best_ask) + d
                q = min(qty, sell_cap)
                orders.append(Order(self.product, ask_px, -q))
                sell_cap -= q

        if orders:
            memory["_last_far_probe_ts"] = now
            memory["_far_probe_count"] = int(memory.get("_far_probe_count", 0)) + 1
        return orders, buy_cap, sell_cap

    # ─── Feature snapshot for downstream tools ────────────────────────────────
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        adv = memory.get("_adverse_stats", {})
        out["fills_tracked"] = float(adv.get("total_count", 0))
        out["adverse_count"] = float(adv.get("adverse_count", 0))
        out["avg_signed_mtm"] = float(adv.get("avg_signed_mtm", 0.0))
        if adv.get("total_count", 0):
            out["adverse_rate"] = float(adv["adverse_count"]) / float(adv["total_count"])
        out["named_market_trades"] = float(memory.get("_named_participant_count", 0))
        return out


def _session_phase(ts: int) -> int:
    """Return 0/1/2 for early/mid/late phase of a 100k-ts session."""
    if ts < 33_000:
        return 0
    elif ts < 66_000:
        return 1
    return 2


def _str_hash(s: str) -> int:
    """Stable short hash for log compression. Returns 0 for empty strings."""
    if not s:
        return 0
    h = 0
    for c in s:
        h = (h * 31 + ord(c)) & 0xFFFF
    return h

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'adverse_horizon_ticks': 5,
                   'adverse_max_window': 50,
                   'far_probe_distances': [25, 50, 100],
                   'far_probe_interval_ticks': 200,
                   'far_probe_qty': 1,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'participant_log_max': 30,
                   'position_limit': 30,
                   'quote_trace_enabled': True,
                   'strategy': 'diagnostic_probe_mm',
                   'tighten_ticks': 1,
                   'ts_increment': 100},
 'VELVETFRUIT_EXTRACT': {'adverse_horizon_ticks': 5,
                         'adverse_max_window': 50,
                         'far_probe_distances': [25, 50, 100],
                         'far_probe_interval_ticks': 200,
                         'far_probe_qty': 1,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 30,
                         'participant_log_max': 30,
                         'position_limit': 30,
                         'quote_trace_enabled': True,
                         'strategy': 'diagnostic_probe_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'VEV_4000': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 4000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_4500': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 4500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5000': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 5000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5100': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 5100,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5200': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 5200,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5300': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 5300,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5400': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 5400,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_5500': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 5500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_6000': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 6000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_6500': {'adverse_horizon_ticks': 5,
              'adverse_max_window': 50,
              'enable_takers': False,
              'far_probe_distances': [25, 50, 100],
              'far_probe_interval_ticks': 200,
              'far_probe_qty': 1,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'participant_log_max': 30,
              'penny_improve_around_mkt': True,
              'position_limit': 30,
              'prior_vol': 0.0125,
              'quote_trace_enabled': True,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'diagnostic_probe_mm',
              'strike': 6500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True}}

STRATEGY_CLASSES = {"diagnostic_probe_mm": DiagnosticProbeMMStrategy}

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
