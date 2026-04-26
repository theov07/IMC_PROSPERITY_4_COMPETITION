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


# ── prosperity/strategies/round_3/hydrogel_passive_regime_mm.py ───────────────────

HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"

REGIME_CODES = {
    "WARMUP": 0,
    "NODE": 1,
    "NEG_COUPLED": 2,
    "POS_COUPLED": 3,
    "DECOUPLED": 4,
    "MIXED": 5,
}


def _mid_from_state(state: TradingState, symbol: str) -> float | None:
    depth = state.order_depths.get(symbol)
    if depth is None:
        return None
    return snapshot_from_order_depth(symbol, depth).mid_price


def _rolling_corr(xs: List[float], ys: List[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    x = xs[-n:]
    y = ys[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    vx = 0.0
    vy = 0.0
    cov = 0.0
    for xv, yv in zip(x, y):
        dx = xv - mx
        dy = yv - my
        vx += dx * dx
        vy += dy * dy
        cov += dx * dy
    denom = math.sqrt(vx * vy)
    return cov / denom if denom > 1e-12 else 0.0


class HydrogelPassiveRegimeMMStrategy(BaseStrategy):
    """Passive-only HYDROGEL MM with dynamic caps and wrong-side inventory guard."""

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

        spread = book.best_ask - book.best_bid
        if spread < int(self.params.get("min_spread", 3)):
            return [], 0

        mid = float(book.mid_price)
        regime = self._regime(state, memory, mid)
        fast, slow, momentum = self._trend_state(memory, mid)

        cap = self._dynamic_cap(regime["name"])
        buy_cap = max(0, cap - position)
        sell_cap = max(0, cap + position)

        bid_price, ask_price = self._base_quotes(book)
        bid_mult, ask_mult = self._base_multipliers(regime["name"])
        bid_mult, ask_mult = self._apply_inventory_aversion(
            bid_mult=bid_mult,
            ask_mult=ask_mult,
            position=position,
            cap=max(1, cap),
        )

        kill = self._wrong_side_kill(position=position, mid=mid, slow=slow, momentum=momentum)
        if kill == "LONG":
            bid_mult = 0.0
            ask_mult = max(ask_mult, float(self.params.get("kill_exit_mult", 2.0)))
            ask_price = self._exit_ask(book)
        elif kill == "SHORT":
            ask_mult = 0.0
            bid_mult = max(bid_mult, float(self.params.get("kill_exit_mult", 2.0)))
            bid_price = self._exit_bid(book)

        base_size = int(self.params.get("maker_size", 60))
        bid_size = min(buy_cap, self._scaled_size(base_size, bid_mult))
        ask_size = min(sell_cap, self._scaled_size(base_size, ask_mult))

        orders: List[Order] = []
        if bid_price is not None and bid_size > 0:
            orders.append(Order(self.product, bid_price, bid_size))
        if ask_price is not None and ask_size > 0:
            orders.append(Order(self.product, ask_price, -ask_size))

        memory["_hpr_mid"] = mid
        memory["_hpr_fast"] = fast
        memory["_hpr_slow"] = slow
        memory["_hpr_momentum"] = momentum
        memory["_hpr_cap"] = float(cap)
        memory["_hpr_bid_mult"] = bid_mult
        memory["_hpr_ask_mult"] = ask_mult
        memory["_hpr_kill"] = 1.0 if kill else 0.0
        memory["_hpr_regime_code"] = float(REGIME_CODES[regime["name"]])
        memory["_hpr_corr"] = float(regime["corr"])
        memory["_hpr_spread_norm"] = float(regime["spread"])

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "regime": REGIME_CODES[regime["name"]],
                "corr": round(float(regime["corr"]), 4),
                "spread_norm": round(float(regime["spread"]), 4),
                "cap": cap,
                "bid_mult": round(bid_mult, 3),
                "ask_mult": round(ask_mult, 3),
                "kill": kill or "",
            },
        )
        return orders, 0

    def _base_quotes(self, book: BookSnapshot) -> Tuple[int | None, int | None]:
        improve = int(self.params.get("improve_ticks", 1))
        bid = int(min(book.best_bid + improve, book.best_ask - 1))
        ask = int(max(book.best_ask - improve, book.best_bid + 1))
        if bid >= ask:
            return None, None
        return bid, ask

    def _exit_bid(self, book: BookSnapshot) -> int:
        improve = int(self.params.get("kill_exit_improve_ticks", 3))
        return int(min(book.best_bid + improve, book.best_ask - 1))

    def _exit_ask(self, book: BookSnapshot) -> int:
        improve = int(self.params.get("kill_exit_improve_ticks", 3))
        return int(max(book.best_ask - improve, book.best_bid + 1))

    def _regime(self, state: TradingState, memory: Dict[str, Any], h_mid: float) -> Dict[str, Any]:
        v_mid = _mid_from_state(state, VELVET)
        ts = int(state.timestamp)
        if v_mid is None or v_mid <= 0 or h_mid <= 0:
            return {"timestamp": ts, "name": "WARMUP", "corr": 0.0, "spread": 0.0}

        h0 = float(memory.setdefault("_hpr_h0", h_mid))
        v0 = float(memory.setdefault("_hpr_v0", v_mid))
        h_norm = 100.0 * h_mid / h0
        v_norm = 100.0 * v_mid / v0
        spread = h_norm - v_norm

        window = int(self.params.get("regime_window", 120))
        min_samples = int(self.params.get("regime_min_samples", 60))
        keep = max(window, min_samples) + 5
        h_hist = memory.setdefault("_hpr_h_norm_hist", [])
        v_hist = memory.setdefault("_hpr_v_norm_hist", [])
        h_hist.append(round(h_norm, 4))
        v_hist.append(round(v_norm, 4))
        if len(h_hist) > keep:
            del h_hist[:-keep]
        if len(v_hist) > keep:
            del v_hist[:-keep]

        samples = min(len(h_hist), len(v_hist))
        corr_window = min(window, samples)
        corr = _rolling_corr(h_hist[-corr_window:], v_hist[-corr_window:])
        if samples < min_samples:
            name = "WARMUP"
        elif abs(spread) <= float(self.params.get("node_threshold", 0.10)):
            name = "NODE"
        elif corr <= float(self.params.get("neg_corr_threshold", -0.55)):
            name = "NEG_COUPLED"
        elif corr >= float(self.params.get("pos_corr_threshold", 0.55)):
            name = "POS_COUPLED"
        elif abs(corr) <= float(self.params.get("decorr_threshold", 0.15)):
            name = "DECOUPLED"
        else:
            name = "MIXED"

        return {"timestamp": ts, "name": name, "corr": round(corr, 4), "spread": round(spread, 4)}

    def _dynamic_cap(self, regime_name: str) -> int:
        limit = min(int(self.params.get("max_position", self.position_limit())), self.position_limit())
        ratios = {
            "WARMUP": float(self.params.get("cap_warmup", 0.55)),
            "NODE": float(self.params.get("cap_node", 0.45)),
            "NEG_COUPLED": float(self.params.get("cap_neg", 0.35)),
            "POS_COUPLED": float(self.params.get("cap_pos", 0.60)),
            "DECOUPLED": float(self.params.get("cap_decoupled", 0.85)),
            "MIXED": float(self.params.get("cap_mixed", 0.65)),
        }
        ratio = max(0.05, min(1.0, ratios.get(regime_name, 0.55)))
        return max(1, int(round(limit * ratio)))

    def _base_multipliers(self, regime_name: str) -> Tuple[float, float]:
        mult = {
            "WARMUP": float(self.params.get("size_warmup", 0.75)),
            "NODE": float(self.params.get("size_node", 0.55)),
            "NEG_COUPLED": float(self.params.get("size_neg", 0.35)),
            "POS_COUPLED": float(self.params.get("size_pos", 0.70)),
            "DECOUPLED": float(self.params.get("size_decoupled", 1.15)),
            "MIXED": float(self.params.get("size_mixed", 0.85)),
        }.get(regime_name, 0.75)
        return mult, mult

    def _apply_inventory_aversion(
        self,
        *,
        bid_mult: float,
        ask_mult: float,
        position: int,
        cap: int,
    ) -> Tuple[float, float]:
        pressure = min(1.0, abs(position) / float(max(1, cap)))
        power = float(self.params.get("inventory_power", 2.0))
        cut = max(0.0, 1.0 - pressure) ** power
        min_worsen = float(self.params.get("min_worsen_mult", 0.0))
        exit_boost = float(self.params.get("inventory_exit_boost", 1.4))
        soft = float(self.params.get("soft_inventory_ratio", 0.55))

        if position > 0:
            bid_mult *= max(min_worsen, cut)
            ask_mult *= 1.0 + exit_boost * pressure
            if pressure >= soft:
                bid_mult *= float(self.params.get("soft_worsen_mult", 0.15))
        elif position < 0:
            ask_mult *= max(min_worsen, cut)
            bid_mult *= 1.0 + exit_boost * pressure
            if pressure >= soft:
                ask_mult *= float(self.params.get("soft_worsen_mult", 0.15))
        return bid_mult, ask_mult

    def _trend_state(self, memory: Dict[str, Any], mid: float) -> Tuple[float, float, float]:
        fast_alpha = float(self.params.get("fast_alpha", 0.25))
        slow_alpha = float(self.params.get("slow_alpha", 0.03))
        fast_prev = float(memory.get("_hpr_fast", mid))
        slow_prev = float(memory.get("_hpr_slow", mid))
        fast = fast_alpha * mid + (1.0 - fast_alpha) * fast_prev
        slow = slow_alpha * mid + (1.0 - slow_alpha) * slow_prev

        lookback = int(self.params.get("momentum_lookback", 40))
        hist = memory.setdefault("_hpr_mid_hist", [])
        hist.append(round(mid, 2))
        if len(hist) > lookback + 1:
            del hist[: -(lookback + 1)]
        ref = hist[0] if len(hist) <= lookback else hist[-lookback - 1]
        momentum = mid - float(ref)
        return fast, slow, momentum

    def _wrong_side_kill(self, *, position: int, mid: float, slow: float, momentum: float) -> str | None:
        threshold = int(self.params.get("kill_position", 120))
        if abs(position) < threshold:
            return None
        dist = mid - slow
        dist_trigger = float(self.params.get("kill_dist_ticks", 8.0))
        mom_trigger = float(self.params.get("kill_momentum_ticks", 12.0))
        if position > 0 and (dist <= -dist_trigger or momentum <= -mom_trigger):
            return "LONG"
        if position < 0 and (dist >= dist_trigger or momentum >= mom_trigger):
            return "SHORT"
        return None

    def _scaled_size(self, base_size: int, mult: float) -> int:
        if base_size <= 0 or mult <= 0.0:
            return 0
        return max(1, int(round(base_size * mult)))

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key, label in [
            ("_hpr_fast", "HPR_fast"),
            ("_hpr_slow", "HPR_slow"),
            ("_hpr_cap", "HPR_cap"),
            ("_hpr_regime_code", "HPR_regime"),
            ("_hpr_corr", "HPR_corr"),
            ("_hpr_spread_norm", "HPR_spread"),
            ("_hpr_bid_mult", "HPR_bid_mult"),
            ("_hpr_ask_mult", "HPR_ask_mult"),
            ("_hpr_kill", "HPR_kill"),
        ]:
            if (value := memory.get(key)) is not None:
                out[label] = float(value)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'cap_decoupled': 0.55,
                   'cap_mixed': 0.45,
                   'cap_neg': 0.25,
                   'cap_node': 0.3,
                   'cap_pos': 0.4,
                   'cap_warmup': 0.35,
                   'decorr_threshold': 0.15,
                   'fast_alpha': 0.25,
                   'improve_ticks': 1,
                   'inventory_exit_boost': 1.4,
                   'inventory_power': 2.0,
                   'kill_dist_ticks': 8.0,
                   'kill_exit_improve_ticks': 3,
                   'kill_exit_mult': 2.0,
                   'kill_momentum_ticks': 12.0,
                   'kill_position': 120,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 60,
                   'max_position': 200,
                   'min_spread': 3,
                   'min_worsen_mult': 0.0,
                   'momentum_lookback': 40,
                   'neg_corr_threshold': -0.55,
                   'node_threshold': 0.1,
                   'pos_corr_threshold': 0.55,
                   'position_limit': 200,
                   'regime_min_samples': 60,
                   'regime_window': 120,
                   'size_decoupled': 1.15,
                   'size_mixed': 0.85,
                   'size_neg': 0.35,
                   'size_node': 0.55,
                   'size_pos': 0.7,
                   'size_warmup': 0.75,
                   'slow_alpha': 0.03,
                   'soft_inventory_ratio': 0.55,
                   'soft_worsen_mult': 0.15,
                   'strategy': 'hydrogel_passive_regime_mm',
                   'tighten_ticks': 1,
                   'ts_increment': 100}}

STRATEGY_CLASSES = {"hydrogel_passive_regime_mm": HydrogelPassiveRegimeMMStrategy}

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
