from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Optional, Set, Tuple
from typing import Any, Dict, List, Optional, Tuple
from typing import Any, Dict, List, Tuple
from typing import Any, Mapping
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

        # Alpha overlay used by champion v5: OBI size tilt
        orders = self._apply_obi_size_tilt(state, position, orders, book, memory)

        return orders, conversions

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

    # ------------------------------------------------------------------
    # Trend gate (skip mean-rev BUY in downtrend, mean-rev SELL in uptrend)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Order Book Imbalance (OBI) SIZE tilt — adjust own quote SIZES (not prices).
    # Avoids spread cost from price tilt. Captures alpha through inventory shift.
    # ------------------------------------------------------------------
    def _apply_obi_size_tilt(
        self,
        state: TradingState,
        position: int,
        orders: List[Order],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> List[Order]:
        """When L3 OBI is extreme, increase the size of orders going in the predicted direction.

        Bullish OBI (>+threshold):
          - Multiply BUY orders by `obi_size_boost_factor` (e.g. 1.5x) — accumulate long
          - Reduce SELL order sizes by `obi_size_reduce_factor` (e.g. 0.5x) — keep long longer

        Bearish OBI (<-threshold): mirror.

        Params:
          obi_size_enabled         : turn on (default False)
          obi_size_levels          : aggregation levels (default 3)
          obi_size_threshold       : abs OBI to fire (default 0.005)
          obi_size_boost_factor    : multiplier on favored side (default 1.5)
          obi_size_reduce_factor   : multiplier on opposed side (default 0.7)
        """
        if not bool(self.params.get("obi_size_enabled", False)):
            return orders

        levels = int(self.params.get("obi_size_levels", 3))
        threshold = float(self.params.get("obi_size_threshold", 0.005))
        boost = float(self.params.get("obi_size_boost_factor", 1.5))
        reduce = float(self.params.get("obi_size_reduce_factor", 0.7))

        bid_total = sum(v for _, v in (book.bid_levels or [])[:levels])
        ask_total = sum(v for _, v in (book.ask_levels or [])[:levels])
        total = bid_total + ask_total
        if total == 0:
            return orders
        obi = (bid_total - ask_total) / total
        memory["_obi_size"] = obi

        if abs(obi) < threshold:
            return orders

        bullish = obi > 0
        adjusted: List[Order] = []
        for o in orders:
            if o.quantity > 0:  # BUY
                factor = boost if bullish else reduce
            elif o.quantity < 0:  # SELL
                factor = reduce if bullish else boost
            else:
                adjusted.append(o)
                continue
            new_qty = int(o.quantity * factor)
            # Respect position limits
            if new_qty > 0:
                cap = max(0, self.position_limit() - position)
                new_qty = min(new_qty, cap) if cap >= 0 else new_qty
            elif new_qty < 0:
                cap = max(0, self.position_limit() + position)
                new_qty = max(new_qty, -cap)
            if new_qty != 0:
                adjusted.append(Order(o.symbol, o.price, new_qty))

        memory["_obi_size_dir"] = "BULL" if bullish else "BEAR"
        return adjusted

    def _counterparty_signal(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> float:
        """Counterparty-flow weighted signal.

        Maintains a rolling buffer of (timestamp, trader_id, signed_qty) for the last
        `cp_window_ts` timestamp units. Signed qty = +qty when trader is buyer, -qty
        when trader is seller. Aggregates per trader, applies a per-trader weight,
        returns weighted sum.

        Default weights (from R4 D1+D2+D3 lead-lag analysis on VELVET):
          Mark 55 = +1.0  (high-vol MM, +0.14 rho with next-50-tick return, 60% hit rate)
          Mark 67 = +1.0  (directional buyer, +0.12 rho, 54% hit rate)
          Mark 01 = -1.0  (MM, -0.17 rho — FADE its flow)
          Mark 14 = -1.0  (MM, -0.15 rho — FADE)
        Other traders default to 0 weight.

        Params:
          cp_window_ts        : rolling window in timestamp units (default 10000 = 100 ticks)
          cp_trader_weights   : dict trader_id -> weight (default = R4 VELVET weights)

        Returns: weighted signed signal (units = contracts).
        """
        window_ts = int(self.params.get("cp_window_ts", 10000))
        weights = self.params.get("cp_trader_weights", {
            "Mark 55": +1.0, "Mark 67": +1.0,
            "Mark 01": -1.0, "Mark 14": -1.0,
        })

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

        # Aggregate per trader, apply weights
        signal = 0.0
        per_trader = {}
        for _, trader, signed in buf:
            per_trader[trader] = per_trader.get(trader, 0.0) + signed
        for trader, net in per_trader.items():
            w = weights.get(trader, 0.0)
            signal += w * net

        memory["_cp_signal"] = signal
        memory["_cp_per_trader"] = per_trader
        return signal


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


# ── prosperity/strategies/round_3/tibo/gamma_scalp_zgated.py ──────────────────────

class GammaScalpZGatedStrategy(BaseStrategy):
    """Z-score-gated long-call accumulation with BS fair value and unwind logic."""

    def _get_spot(self, state: TradingState) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if not od or not od.buy_orders or not od.sell_orders:
            return None
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        return 0.5 * (bb + ba)

    def _update_zscore(self, S: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Optional[float]:
        window = p["zscore_window"]
        buf: List[float] = memory.setdefault("_velvet_buf", [])
        buf.append(S)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (S - mean) / std

    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        params = self.params
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(params.get("tte_days_initial", 5.0)),
            params.get("historical_tte_by_day"),
        )
        ts_per_day = timestamp_units_per_day_from_params(params)
        T = time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_per_day)
        return {
            "K":                    float(params["strike"]),
            "T":                    max(0.01, T),
            "implied_vol_prior":    float(params.get("implied_vol_prior", 0.0125)),
            "edge_ticks":           float(params.get("edge_ticks", 0.0)),
            "target_qty":           int(params.get("target_qty", 100)),
            "entry_size":           int(params.get("entry_size", 10)),
            "passive_bid_size":     int(params.get("passive_bid_size", 10)),
            "unwind_tte_threshold": float(params.get("unwind_tte_threshold", 1.5)),
            "min_quote_price":      float(params.get("min_quote_price", 2.0)),
            "underlying_symbol":    params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
            "zscore_window":        int(params.get("zscore_window", 500)),
            "zscore_skip_threshold":  float(params.get("zscore_skip_threshold", 1.0)),
            "zscore_boost_threshold": float(params.get("zscore_boost_threshold", 1.0)),
            "skip_when_expensive":  bool(params.get("skip_when_expensive", True)),
            "boost_when_cheap":     bool(params.get("boost_when_cheap", False)),
            "entry_size_boost":     float(params.get("entry_size_boost", 1.5)),
            "sell_when_very_expensive": bool(params.get("sell_when_very_expensive", False)),
            "zscore_sell_threshold":    float(params.get("zscore_sell_threshold", 1.5)),
            "sell_size_pct":            float(params.get("sell_size_pct", 0.10)),
        }

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
        S = self._get_spot(state)
        if S is None:
            return [], 0

        z = self._update_zscore(S, memory, p)
        memory["_velvet_z"] = z

        fair  = call_price(S, p["K"], p["T"], p["implied_vol_prior"])
        gamma = call_gamma(S, p["K"], p["T"], p["implied_vol_prior"])
        delta = call_delta(S, p["K"], p["T"], p["implied_vol_prior"])
        memory["_gamma"]   = gamma
        memory["_delta"]   = delta
        memory["_fair_iv"] = fair
        memory["_spot"]    = S
        memory["_T"]       = p["T"]

        if fair < p["min_quote_price"]:
            return [], 0

        orders:   List[Order] = []
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── Unwind phase ──────────────────────────────────────────────────────
        if p["T"] < p["unwind_tte_threshold"] or position >= p["target_qty"]:
            if sell_cap > 0 and position > 0:
                ask_px = book.best_ask - 1
                if ask_px <= book.best_bid:
                    ask_px = book.best_bid + 1
                qty = min(p["passive_bid_size"], sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "unwind"
            return orders, 0

        # ── Profit-take on extreme z ──────────────────────────────────────────
        if (p["sell_when_very_expensive"] and z is not None
                and z > p["zscore_sell_threshold"] and position > 0 and sell_cap > 0):
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            sell_qty = max(1, int(round(position * p["sell_size_pct"])))
            qty = min(sell_qty, sell_cap, position, p["passive_bid_size"])
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "z_profit_take"
            return orders, 0

        # ── Skip when expensive ───────────────────────────────────────────────
        if p["skip_when_expensive"] and z is not None and z > p["zscore_skip_threshold"]:
            memory["_mode"] = "z_skipped_expensive"
            return orders, 0

        # ── Accumulate phase ──────────────────────────────────────────────────
        size_mult = 1.0
        if p["boost_when_cheap"] and z is not None and z < -p["zscore_boost_threshold"]:
            size_mult = p["entry_size_boost"]
            memory["_mode"] = "z_boost_cheap"
        else:
            memory["_mode"] = "accumulate"

        eff_entry_size  = max(1, int(round(p["entry_size"]      * size_mult)))
        eff_passive_size = max(1, int(round(p["passive_bid_size"] * size_mult)))

        # Active taker: buy if ask is at or below fair + edge_ticks
        if buy_cap > 0 and position < p["target_qty"]:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty  = -order_depth.sell_orders.get(ask, 0)
                headroom = p["target_qty"] - position
                take_qty = min(ask_qty, buy_cap, eff_entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty

        # Passive maker: penny-improve bid
        if buy_cap > 0 and position < p["target_qty"]:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(eff_passive_size, buy_cap, p["target_qty"] - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (g := memory.get("_gamma"))   is not None: out["gamma"]   = g
        if (d := memory.get("_delta"))   is not None: out["delta"]   = d
        if (f := memory.get("_fair_iv")) is not None: out["fair_iv"] = f
        if (z := memory.get("_velvet_z")) is not None: out["velvet_z"] = z
        if (m := memory.get("_mode")) is not None:
            out["mode"] = {"accumulate": 1.0, "unwind": 0.0,
                           "z_skipped_expensive": -1.0, "z_boost_cheap": 2.0}.get(m, 0.5)
        return out


# ── prosperity/strategies/round_3/tibo/mm_first_v4_combo.py ───────────────────────

class MMFirstV4ComboStrategy(BaseStrategy):

    def _compute_quote_prices(
        self,
        book: BookSnapshot,
        inventory_ratio: float,
        mid_smooth: float,
    ) -> Tuple[Optional[int], Optional[int], str]:
        bid_price = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price = (book.best_ask - 1) if book.best_ask is not None else None
        return bid_price, ask_price, "L1"

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        window = int(self.params.get("zscore_window", 50))
        buf: List[float] = memory.setdefault("_zscore_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            memory["zscore"] = None
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            memory["zscore"] = None
            return None
        z = (mid - mean) / std
        memory["zscore"] = z
        memory["_zs_mean"] = mean
        memory["_zs_std"] = std
        return z

    def _zscore_size_factors(self, memory: Dict[str, Any]) -> Tuple[float, float]:
        z = memory.get("zscore")
        if z is None:
            return 1.0, 1.0
        threshold = float(self.params.get("zscore_threshold", 1.0))
        size_scale = float(self.params.get("zscore_size_scale", 0.5))
        max_scale  = float(self.params.get("zscore_max_scale", 3.0))
        excess = max(0.0, abs(z) - threshold)
        scale  = min(max_scale, 1.0 + size_scale * excess)
        if z > threshold:
            return 1.0 / scale, scale
        if z < -threshold:
            return scale, 1.0 / scale
        return 1.0, 1.0

    def _compute_sizes(self, position: int, limit: int) -> Tuple[float, float]:
        base = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base * (1.0 - position / limit)
        ask_size = base * (1.0 + position / limit)
        return bid_size, ask_size

    def _dynamic_take_edge(self, memory: Dict[str, Any]) -> float:
        lo = self.params.get("take_edge_lo")
        hi = self.params.get("take_edge_hi")
        if lo is None or hi is None:
            return float(self.params.get("take_edge", 1.0))
        sigma = memory.get("sigma_smoothed")
        if sigma is None:
            return float(lo)
        vol_lo = float(self.params.get("take_edge_vol_lo", 2.0))
        vol_hi = float(self.params.get("take_edge_vol_hi", 5.0))
        if sigma <= vol_lo:
            return float(lo)
        if sigma >= vol_hi:
            return float(hi)
        t = (sigma - vol_lo) / (vol_hi - vol_lo)
        return float(lo) + t * (float(hi) - float(lo))

    def _compute_anchor_signal(
        self,
        mid: float,
        book: BookSnapshot,
        mid_smooth: float,
        memory: Dict[str, Any],
    ) -> float:
        anchor_price = self.params.get("anchor_price")
        if anchor_price is None:
            return mid_smooth
        anchor_fixed = float(anchor_price)
        anchor_alpha = float(self.params.get("anchor_alpha", 0.0))
        if anchor_alpha > 0.0:
            ema = memory.get("_anchor_ema", anchor_fixed)
            ema = anchor_alpha * mid + (1.0 - anchor_alpha) * ema
            drift_bound = float(self.params.get("anchor_drift_bound", 0.0))
            if drift_bound > 0:
                ema = max(anchor_fixed - drift_bound,
                          min(anchor_fixed + drift_bound, ema))
            memory["_anchor_ema"] = ema
            anchor_value = ema
        else:
            anchor_value = anchor_fixed
        ar_gain = float(self.params.get("ar_gain", 0.0))
        ar_shift = 0.0
        if ar_gain > 0.0:
            source = str(self.params.get("ar_shift_source", "mid"))
            if source == "microprice":
                current = self._microprice(book)
            elif source == "mid_smooth":
                current = mid_smooth
            else:
                current = mid
            prev = memory.get("_ar_prev_signal")
            if prev is not None:
                ar_shift = -ar_gain * (current - prev)
            memory["_ar_prev_signal"] = current
        return anchor_value + ar_shift

    def _compute_asym_take_edges(
        self,
        base_edge: float,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[float, float]:
        unwind = float(self.params.get("unwind_take_edge", 0.0))
        if unwind <= 0:
            return base_edge, base_edge
        limit = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if position > 0:
            sell_edge = max(0.0, base_edge - unwind * pressure)
            buy_edge  = base_edge + unwind * pressure
        elif position < 0:
            buy_edge  = max(0.0, base_edge - unwind * pressure)
            sell_edge = base_edge + unwind * pressure
        else:
            return base_edge, base_edge
        return buy_edge, sell_edge

    def _fire_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        buy_edge: float,
        sell_edge: float,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        taker_buy_threshold  = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")
        orders: List[Order] = []
        taker_buy_px:  Set[int] = set()
        taker_sell_px: Set[int] = set()
        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= fair_value - buy_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, int(bid_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                taker_buy_px.add(ask_p)
                buy_cap -= qty
        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume     = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= fair_value + sell_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, int(ask_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                taker_sell_px.add(bid_p)
                sell_cap -= qty
        return orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        limit: int,
        bid_size: float,
        ask_size: float,
        bid_price: Optional[int],
        ask_price: Optional[int],
        buy_cap: int,
        sell_cap: int,
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        gap_min     = float(self.params.get("gap_trigger_min", 10))
        shift       = float(self.params.get("OB_cleared_shift", 10))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))
        z           = memory.get("zscore")
        gap_gate    = float(self.params.get("zscore_gap_gate",
                            self.params.get("zscore_threshold", 1.0)))
        bid_z_ok = z is None or z >= -gap_gate
        ask_z_ok = z is None or z <= gap_gate
        orders: List[Order] = []
        memory["_gap_buy_px"]  = []
        memory["_gap_sell_px"] = []
        all_bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        all_asks = sorted(order_depth.sell_orders.keys())
        if all_bids:
            memory["_last_best_bid"] = all_bids[0]
        if all_asks:
            memory["_last_best_ask"] = all_asks[0]
        last_best_bid = memory.get("_last_best_bid")
        last_best_ask = memory.get("_last_best_ask")
        remaining_bids = [p for p in all_bids if p not in taker_sell_px]
        remaining_asks = [p for p in all_asks if p not in taker_buy_px]
        gap_swept_bids: Set[int] = set()
        gap_swept_asks: Set[int] = set()
        if gap_min > 0 and gap_max_vol > 0:
            bid_gap_ok = False
            bid1 = bid2 = bid1_vol = None
            if len(remaining_bids) >= 2:
                bid1, bid2 = remaining_bids[0], remaining_bids[1]
                bid1_vol   = order_depth.buy_orders[bid1]
                bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol
            bid_streak = memory.get("_gap_bid_streak", 0)
            bid_streak = bid_streak + 1 if bid_gap_ok else 0
            memory["_gap_bid_streak"] = bid_streak
            if bid_streak >= gap_confirm and bid_gap_ok and sell_cap > 0 and bid_z_ok:
                qty = min(bid1_vol, sell_cap, int(ask_size))
                if qty > 0:
                    orders.append(Order(self.product, bid1, -qty))
                    sell_cap -= qty
                    memory["_gap_sell_px"].append(bid1)
                    if qty >= bid1_vol:
                        gap_swept_bids.add(bid1)
            ask_gap_ok = False
            ask1 = ask2 = ask1_vol = None
            if len(remaining_asks) >= 2:
                ask1, ask2 = remaining_asks[0], remaining_asks[1]
                ask1_vol   = -order_depth.sell_orders[ask1]
                ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol
            ask_streak = memory.get("_gap_ask_streak", 0)
            ask_streak = ask_streak + 1 if ask_gap_ok else 0
            memory["_gap_ask_streak"] = ask_streak
            if ask_streak >= gap_confirm and ask_gap_ok and buy_cap > 0 and ask_z_ok:
                qty = min(ask1_vol, buy_cap, int(bid_size))
                if qty > 0:
                    orders.append(Order(self.product, ask1, qty))
                    buy_cap -= qty
                    memory["_gap_buy_px"].append(ask1)
                    if qty >= ask1_vol:
                        gap_swept_asks.add(ask1)
        final_remaining_bids = [p for p in remaining_bids if p not in gap_swept_bids]
        final_remaining_asks = [p for p in remaining_asks if p not in gap_swept_asks]
        if final_remaining_asks:
            ask_price = final_remaining_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + int(shift)
        if final_remaining_bids:
            bid_price = final_remaining_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - int(shift)
        return orders, buy_cap, sell_cap, bid_price, ask_price

    def _apply_toxic_flow(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        toxic_threshold = float(self.params.get("toxic_threshold", 0.0))
        if toxic_threshold <= 0:
            return buy_size, sell_size
        toxic_window    = int(self.params.get("toxic_window", 6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.75))
        flow_history = memory.setdefault("_flow_history", [])
        prev_best_bid = memory.get("_prev_best_bid")
        prev_best_ask = memory.get("_prev_best_ask")
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None:
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
            total  = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total
        memory["_flow_score"] = flow_score
        if flow_score > toxic_threshold and sell_size > 0:
            sell_size = max(1.0, sell_size * toxic_size_frac)
        elif flow_score < -toxic_threshold and buy_size > 0:
            buy_size = max(1.0, buy_size * toxic_size_frac)
        return buy_size, sell_size

    def _apply_jump_filter(
        self,
        book: BookSnapshot,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        threshold = float(self.params.get("trend_jump_threshold", 0.0))
        if threshold <= 0:
            return buy_size, sell_size
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))
        prev_best_bid  = memory.get("_prev_best_bid")
        prev_best_ask  = memory.get("_prev_best_ask")
        bid_jumped = prev_best_bid is not None and book.best_bid == prev_best_bid + 1
        ask_jumped = prev_best_ask is not None and book.best_ask == prev_best_ask - 1
        if bid_jumped and sell_size > 0:
            sell_size = max(1.0, sell_size * jump_size_frac)
        if ask_jumped and buy_size > 0:
            buy_size = max(1.0, buy_size * jump_size_frac)
        return buy_size, sell_size

    def _compute_base_mid(self, raw_mid: float, book: BookSnapshot) -> float:
        vol_filter = int(self.params.get("mid_vol_filter", 0))
        if vol_filter <= 0:
            return raw_mid
        wall_bid = wall_ask = None
        for (p, v) in book.bid_levels:
            if v >= vol_filter:
                wall_bid = p
                break
        for (p, v) in book.ask_levels:
            if v >= vol_filter:
                wall_ask = p
                break
        if wall_bid is None or wall_ask is None:
            return raw_mid
        return (wall_bid + wall_ask) / 2.0

    def _taker_cooldown_active(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[bool, bool]:
        cooldown = int(self.params.get("taker_cooldown_ticks", 0))
        if cooldown <= 0:
            return False, False
        now          = int(state.timestamp)
        ts_increment = int(self.params.get("ts_increment", 100))
        last_buy     = memory.get("_last_taker_buy_ts")
        last_sell    = memory.get("_last_taker_sell_ts")
        buy_blocked  = last_buy  is not None and (now - last_buy)  < cooldown * ts_increment
        sell_blocked = last_sell is not None and (now - last_sell) < cooldown * ts_increment
        return buy_blocked, sell_blocked

    def _update_taker_cooldown(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> None:
        now = int(state.timestamp)
        if taker_buy_px:
            memory["_last_taker_buy_ts"]  = now
        if taker_sell_px:
            memory["_last_taker_sell_ts"] = now

    def _apply_inventory_bias(
        self,
        fair_value: float,
        position: int,
        memory: Dict[str, Any],
    ) -> float:
        gamma = float(self.params.get("inventory_aversion_gamma", 0.0))
        if gamma <= 0 or position == 0:
            return fair_value
        sigma = memory.get("sigma_smoothed", 1.0)
        return fair_value - gamma * position * (sigma ** 2)

    def _microprice_size_tilt(
        self,
        book: BookSnapshot,
        raw_mid: float,
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        gain = float(self.params.get("microprice_size_gain", 0.0))
        if gain <= 0:
            return bid_size, ask_size
        threshold = float(self.params.get("microprice_size_threshold", 0.2))
        micro = self._microprice(book)
        delta = micro - raw_mid
        if abs(delta) < threshold:
            return bid_size, ask_size
        scale = 1.0 + gain * (abs(delta) - threshold)
        if delta > 0:
            return bid_size / scale, ask_size * scale
        else:
            return bid_size * scale, ask_size / scale

    def _apply_spread_widening(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        threshold = float(self.params.get("spread_widen_vol_threshold", 0.0))
        if threshold <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        sigma = memory.get("sigma_smoothed", 0.0)
        if sigma < threshold:
            return bid_price, ask_price
        extra   = int(self.params.get("spread_widen_extra_ticks", 1))
        new_bid = max(1, bid_price - extra)
        new_ask = ask_price + extra
        if book.best_ask is not None:
            new_bid = min(new_bid, book.best_ask - 1)
        if book.best_bid is not None:
            new_ask = max(new_ask, book.best_bid + 1)
        return new_bid, new_ask

    def _effective_position(self, position: int) -> int:
        target = int(self.params.get("inventory_target", 0))
        return position - target

    def _apply_fill_rate_toxicity(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        window = int(self.params.get("fill_toxicity_window", 0))
        if window <= 0:
            return bid_size, ask_size
        history = memory.setdefault("_fill_history", [])
        for trade in state.own_trades.get(self.product, []):
            qty = float(trade.quantity)
            if trade.buyer == "SUBMISSION":
                history.append(qty)
            elif trade.seller == "SUBMISSION":
                history.append(-qty)
        if len(history) > window:
            del history[:-window]
        if not history:
            return bid_size, ask_size
        signed  = sum(history)
        total   = sum(abs(x) for x in history)
        if total <= 0:
            return bid_size, ask_size
        imbalance = signed / total
        threshold = float(self.params.get("fill_toxicity_threshold", 0.7))
        frac      = float(self.params.get("fill_toxicity_frac", 0.5))
        if imbalance > threshold and bid_size > 0:
            bid_size = max(1.0, bid_size * frac)
        elif imbalance < -threshold and ask_size > 0:
            ask_size = max(1.0, ask_size * frac)
        return bid_size, ask_size

    def _apply_spread_zscore_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        window = int(self.params.get("spread_zscore_window", 0))
        if window <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        spread = book.best_ask - book.best_bid
        buf: List[float] = memory.setdefault("_spread_buf", [])
        buf.append(spread)
        if len(buf) > window:
            del buf[:-window]
        if len(buf) < max(10, window // 4):
            return bid_price, ask_price
        mean = sum(buf) / len(buf)
        var  = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        std  = var ** 0.5
        if std < 1e-9:
            return bid_price, ask_price
        z         = (spread - mean) / std
        threshold = float(self.params.get("spread_zscore_threshold", 1.5))
        if z < threshold:
            return bid_price, ask_price
        shift   = int(self.params.get("spread_zscore_shift", 1))
        new_bid = min(book.best_ask - 1, bid_price + shift)
        new_ask = max(book.best_bid + 1, ask_price - shift)
        if new_bid >= new_ask:
            new_ask = new_bid + 1
        return new_bid, new_ask

    def _probe_tick0(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        distances = self.params.get("probe_t0_distances")
        if not distances or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap
        max_ts = int(self.params.get("probe_t0_max_ts", 500))
        now    = int(state.timestamp)
        if now > max_ts:
            return [], buy_cap, sell_cap
        if memory.get("_probe_t0_fired", False):
            return [], buy_cap, sell_cap
        qty    = int(self.params.get("probe_t0_qty", 1))
        orders: List[Order] = []
        for dist in distances:
            d = int(dist)
            if d <= 0:
                continue
            b_qty = min(qty, buy_cap)
            a_qty = min(qty, sell_cap)
            if b_qty > 0:
                orders.append(Order(self.product, book.best_bid - d, b_qty))
                buy_cap -= b_qty
            if a_qty > 0:
                orders.append(Order(self.product, book.best_ask + d, -a_qty))
                sell_cap -= a_qty
        if orders:
            memory["_probe_t0_fired"] = True
        return orders, buy_cap, sell_cap

    def _apply_momentum_follower(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        window = int(self.params.get("momentum_window", 0))
        if window <= 0:
            return [], buy_cap, sell_cap
        history   = memory.setdefault("_momentum_history", [])
        prev_bid  = memory.get("_prev_best_bid")
        prev_ask  = memory.get("_prev_best_ask")
        for trade in state.market_trades.get(self.product, []):
            qty = float(trade.quantity)
            if prev_ask is not None and trade.price >= prev_ask:
                history.append(qty)
            elif prev_bid is not None and trade.price <= prev_bid:
                history.append(-qty)
        if len(history) > window:
            del history[:-window]
        if not history:
            return [], buy_cap, sell_cap
        signed = sum(history)
        total  = sum(abs(x) for x in history)
        if total <= 0:
            return [], buy_cap, sell_cap
        flow      = signed / total
        threshold = float(self.params.get("momentum_threshold", 0.8))
        qty       = int(self.params.get("momentum_qty", 3))
        orders: List[Order] = []
        if flow > threshold and buy_cap > 0:
            asks = sorted(order_depth.sell_orders.keys())
            if asks:
                ask_p     = asks[0]
                available = -order_depth.sell_orders[ask_p]
                q = min(qty, buy_cap, available)
                if q > 0:
                    orders.append(Order(self.product, ask_p, q))
                    buy_cap -= q
        elif flow < -threshold and sell_cap > 0:
            bids = sorted(order_depth.buy_orders.keys(), reverse=True)
            if bids:
                bid_p  = bids[0]
                volume = order_depth.buy_orders[bid_p]
                q = min(qty, sell_cap, volume)
                if q > 0:
                    orders.append(Order(self.product, bid_p, -q))
                    sell_cap -= q
        return orders, buy_cap, sell_cap

    def _probe_quotes(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        probe_dist = int(self.params.get("probe_distance", 0))
        if probe_dist <= 0 or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap
        probe_qty      = int(self.params.get("probe_qty", 1))
        probe_interval = int(self.params.get("probe_interval_ticks", 100))
        ts_increment   = int(self.params.get("ts_increment", 100))
        now            = int(state.timestamp)
        last_probe     = memory.get("_last_probe_ts", -(10 ** 9))
        if (now - last_probe) < probe_interval * ts_increment:
            return [], buy_cap, sell_cap
        orders: List[Order] = []
        actual_bid_qty = min(probe_qty, buy_cap)
        actual_ask_qty = min(probe_qty, sell_cap)
        if actual_bid_qty > 0:
            probe_bid = book.best_bid - probe_dist
            orders.append(Order(self.product, probe_bid, actual_bid_qty))
            buy_cap -= actual_bid_qty
        if actual_ask_qty > 0:
            probe_ask = book.best_ask + probe_dist
            orders.append(Order(self.product, probe_ask, -actual_ask_qty))
            sell_cap -= actual_ask_qty
        if orders:
            memory["_last_probe_ts"] = now
        return orders, buy_cap, sell_cap

    def _asym_passive_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        position: int,
        book: BookSnapshot,
    ) -> Tuple[Optional[int], Optional[int]]:
        skew_max = int(self.params.get("passive_unwind_skew_ticks", 0))
        if skew_max <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        trigger  = float(self.params.get("passive_unwind_trigger", 0.3))
        limit    = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if pressure < trigger:
            return bid_price, ask_price
        scaled = (pressure - trigger) / max(1e-9, 1.0 - trigger)
        skew   = int(round(skew_max * scaled))
        if skew <= 0:
            return bid_price, ask_price
        if position > 0:
            ask_price = max(book.best_bid + 1, ask_price - skew)
        elif position < 0:
            bid_price = min(book.best_ask - 1, bid_price + skew)
        return bid_price, ask_price

    def _apply_eod_flatten(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        position: int,
    ) -> Optional[List[Order]]:
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

    def _passive_quotes(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        limit: int,
    ) -> Tuple[List[Order], int, int]:
        quote_buy  = min(buy_cap,  int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))
        inv_abs    = abs(position) / float(limit) if limit else 0.0
        hard_stop  = 1.0 - float(self.params.get("pct_kept_for_takers", 0.2))
        if inv_abs >= hard_stop:
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0
        orders: List[Order] = []
        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))
        return orders, buy_cap - quote_buy, sell_cap - quote_sell

    def _log_taker_fills(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        this_taker_buy_px: Set[int],
        this_taker_sell_px: Set[int],
    ) -> None:
        prev_taker_buy_px  = set(memory.get("_taker_buy_px", []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        prev_gap_buy_px    = set(memory.get("_gap_buy_px_prev", []))
        prev_gap_sell_px   = set(memory.get("_gap_sell_px_prev", []))
        memory["_taker_buy_px"]      = list(this_taker_buy_px)
        memory["_taker_sell_px"]     = list(this_taker_sell_px)
        memory["_gap_buy_px_prev"]   = list(memory.get("_gap_buy_px", []))
        memory["_gap_sell_px_prev"]  = list(memory.get("_gap_sell_px", []))
        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY", trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                is_gap = (
                    (side == "BUY"  and trade.price in prev_gap_buy_px)
                    or (side == "SELL" and trade.price in prev_gap_sell_px)
                )
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                    gap_exploit=is_gap,
                )

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if order_depth.buy_orders and order_depth.sell_orders:
            eod_orders = self._apply_eod_flatten(state, order_depth, position)
            if eod_orders is not None:
                return eod_orders, 0
        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0
        raw_mid = book.mid_price
        if raw_mid is None and book.best_bid is not None:
            raw_mid = float(book.best_bid)
        if raw_mid is None and book.best_ask is not None:
            raw_mid = float(book.best_ask)
        mid = raw_mid if raw_mid is not None else memory["_last_mid"]
        if raw_mid is not None:
            memory["_last_mid"] = raw_mid
        if self.params.get("use_microprice_as_fair", False):
            micro    = self._microprice(book)
            base_mid = micro if micro else mid
        else:
            base_mid = self._compute_base_mid(mid, book)
        mid_smooth = self._smooth_mid(base_mid, memory)
        self._compute_zscore(base_mid, memory)
        sigma      = self._update_volatility(base_mid, memory)
        fair_value = self._compute_anchor_signal(base_mid, book, mid_smooth, memory)
        eff_position = self._effective_position(position)
        fair_value   = self._apply_inventory_bias(fair_value, eff_position, memory)
        limit         = self.position_limit()
        inventory_ratio = position / float(limit) if limit else 0.0
        bid_price, ask_price, _ = self._compute_quote_prices(book, inventory_ratio, fair_value)
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        bid_size, ask_size = self._compute_sizes(position, limit)
        bid_factor, ask_factor = self._zscore_size_factors(memory)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)
        bid_size, ask_size = self._microprice_size_tilt(book, mid, bid_size, ask_size)
        base_edge       = self._dynamic_take_edge(memory)
        buy_edge, sell_edge = self._compute_asym_take_edges(base_edge, eff_position, memory)
        buy_blocked, sell_blocked = self._taker_cooldown_active(state, memory)
        if buy_blocked:
            buy_edge = 1_000_000.0
        if sell_blocked:
            sell_edge = 1_000_000.0
        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._fire_takers(
            order_depth, fair_value, bid_size, ask_size, buy_cap, sell_cap,
            buy_edge=buy_edge, sell_edge=sell_edge,
        )
        self._update_taker_cooldown(state, memory, taker_buy_px, taker_sell_px)
        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap,
            taker_buy_px, taker_sell_px,
        )
        bid_price, ask_price = self._asym_passive_skew(bid_price, ask_price, eff_position, book)
        bid_price, ask_price = self._apply_spread_widening(bid_price, ask_price, book, memory)
        bid_price, ask_price = self._apply_spread_zscore_skew(bid_price, ask_price, book, memory)
        bid_size, ask_size   = self._apply_toxic_flow(state, memory, bid_size, ask_size)
        bid_size, ask_size   = self._apply_jump_filter(book, memory, bid_size, ask_size)
        bid_size, ask_size   = self._apply_fill_rate_toxicity(state, memory, bid_size, ask_size)
        passive_orders, buy_cap, sell_cap = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit
        )
        probe_orders, buy_cap, sell_cap = self._probe_quotes(
            book, state, memory, position, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_orders)
        probe_t0_orders, buy_cap, sell_cap = self._probe_tick0(
            book, state, memory, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_t0_orders)
        momentum_orders, buy_cap, sell_cap = self._apply_momentum_follower(
            state, order_depth, memory, buy_cap, sell_cap,
        )
        taker_orders.extend(momentum_orders)
        if book.best_bid is not None:
            memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_prev_best_ask"] = book.best_ask
        self._log_taker_fills(state, memory, taker_buy_px, taker_sell_px)
        z = memory.get("zscore")
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position": position,
                "fair":     round(fair_value, 2),
                "buy_edge": round(buy_edge, 2),
                "sell_edge":round(sell_edge, 2),
                "bid_size": int(bid_size),
                "ask_size": int(ask_size),
                "zscore":   round(z, 4) if z is not None else None,
                "sigma":    round(sigma, 4),
                "flow_score": round(memory.get("_flow_score", 0.0), 3),
            },
        )
        return taker_orders + gap_orders + passive_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed"))  is not None: out["MidSmooth"]  = float(m)
        if (a := memory.get("_anchor_ema"))   is not None: out["AnchorEMA"]  = float(a)
        z = memory.get("zscore")
        if z is not None:
            out["Z"] = float(z)
        return out


class R3GuardedAnchorMMStrategy(MMFirstV4ComboStrategy):
    """Guarded Anchor MM: disables AR + takers when price trends away from anchor.

    Guard logic (_use_anchor):
      - near_anchor: |mid - anchor| <= near_band (default 0)
      - reverting:   price is between [min_dist, max_dist] from anchor AND
                     trending back toward it (dist × trend_ema <= -threshold)
      - wrong_way_inventory: inventory pushes in the wrong direction
      - Guard ON (use anchor) = (near_anchor OR reverting) AND NOT wrong_way
      - Guard OFF: set ar_gain=0, take_edges=∞  → pure passive MM only
    """

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        # Counterparty bias layer (opt-in via params): compute trader-flow signal
        # Mark 55+67 follow / Mark 01+14 fade → returns weighted net flow signal
        # Mark this strategy as handling cp_bias internally — avoid double-application from on_tick
        self.params["_cp_bias_handled_internally"] = True

        cp_offset = 0
        if bool(self.params.get("counterparty_bias_enabled", False)):
            cp_signal = self._counterparty_signal(state, memory)
            cp_threshold = float(self.params.get("cp_signal_threshold", 5.0))
            cp_max_offset = float(self.params.get("cp_max_anchor_offset", 3.0))
            cp_scale = float(self.params.get("cp_anchor_scale_per_unit", 0.10))
            if abs(cp_signal) > cp_threshold:
                cp_offset = int(round(max(-cp_max_offset, min(cp_max_offset, cp_signal * cp_scale))))

        # Original guard logic
        orders, conv = self._compute_guarded(state, book, order_depth, position, memory)

        # Apply cp_bias as uniform price shift on all orders (post-strategy)
        if cp_offset != 0 and orders:
            shifted = []
            best_bid = book.best_bid
            best_ask = book.best_ask
            for o in orders:
                new_price = int(o.price) + cp_offset
                # Cap to avoid crossing the book
                if o.quantity > 0 and best_ask is not None and new_price >= best_ask:
                    new_price = int(best_ask) - 1
                elif o.quantity < 0 and best_bid is not None and new_price <= best_bid:
                    new_price = int(best_bid) + 1
                shifted.append(Order(o.symbol, new_price, o.quantity))
            return shifted, conv
        return orders, conv

    def _compute_guarded(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        mid    = book.mid_price
        anchor = self.params.get("anchor_price")
        if mid is None or anchor is None:
            return super().compute_orders(state, book, order_depth, position, memory)
        use_anchor = self._use_anchor(float(mid), float(anchor), position, memory)
        memory["_guard_use_anchor"] = int(use_anchor)
        if use_anchor:
            return super().compute_orders(state, book, order_depth, position, memory)
        old_anchor   = self.params.get("anchor_price")
        old_ar       = self.params.get("ar_gain")
        old_take_lo  = self.params.get("take_edge_lo")
        old_take_hi  = self.params.get("take_edge_hi")
        try:
            self.params["anchor_price"] = None
            self.params["ar_gain"]      = 0.0
            self.params["take_edge_lo"] = 1_000_000.0
            self.params["take_edge_hi"] = 1_000_000.0
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = old_anchor
            self.params["ar_gain"]      = old_ar
            self.params["take_edge_lo"] = old_take_lo
            self.params["take_edge_hi"] = old_take_hi

    def _use_anchor(
        self,
        mid: float,
        anchor: float,
        position: int,
        memory: Dict[str, Any],
    ) -> bool:
        prev_mid = memory.get("_guard_prev_mid")
        memory["_guard_prev_mid"] = mid
        raw_trend = 0.0 if prev_mid is None else mid - float(prev_mid)
        alpha = float(self.params.get("guard_trend_alpha", 0.3))
        trend = float(memory.get("_guard_trend_ema", raw_trend))
        trend = alpha * raw_trend + (1.0 - alpha) * trend
        memory["_guard_trend_ema"] = trend
        dist = mid - anchor
        memory["_guard_dist"]  = dist
        memory["_guard_trend"] = trend
        near_band       = float(self.params.get("guard_near_band", 0.0))
        min_dist        = float(self.params.get("guard_min_dist", 0.0))
        max_dist        = float(self.params.get("guard_max_dist", 80.0))
        threshold       = float(self.params.get("guard_reversion_threshold", 0.0))
        inventory_dist  = float(self.params.get("guard_inventory_dist", 40.0))
        near_anchor = abs(dist) <= near_band
        reverting   = min_dist <= abs(dist) <= max_dist and (dist * trend) <= -threshold
        wrong_way   = (position > 0 and dist < -inventory_dist) or (
                       position < 0 and dist > inventory_dist)
        return (near_anchor or reverting) and not wrong_way

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (d := memory.get("_guard_dist"))       is not None: out["GuardDist"]  = float(d)
        if (t := memory.get("_guard_trend"))      is not None: out["GuardTrend"] = float(t)
        if (u := memory.get("_guard_use_anchor")) is not None: out["GuardOn"]    = float(u)
        return out


class DynamicAnchorMMStrategy(R3GuardedAnchorMMStrategy):
    """R3GuardedAnchorMMStrategy with anchor replaced by a slow EWMA of mid price.

    Instead of a fixed anchor_price=5250, the anchor tracks a very slow
    exponential moving average of the mid price. This lets the strategy
    adapt when VELVETFRUIT drifts over multi-day periods.

    Key param:
      anchor_slow_alpha  EWMA alpha for the slow anchor (default 0.0002,
                         half-life ≈ 3500 ticks ≈ 0.35 days).
                         Smaller = slower / more stable anchor.

    Set anchor_alpha=0.0 and anchor_drift_bound=0.0 in config so the parent's
    fast-drift logic is bypassed (the slow EMA is already smooth enough).
    """

    def _get_dynamic_anchor(self, mid: float, memory: Dict[str, Any]) -> float:
        alpha = float(self.params.get("anchor_slow_alpha", 0.0002))
        prev = memory.get("_dynamic_anchor")
        if prev is None:
            memory["_dynamic_anchor"] = float(mid)
            return float(mid)
        ema = (1.0 - alpha) * float(prev) + alpha * mid
        memory["_dynamic_anchor"] = ema
        return ema

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
            return super().compute_orders(state, book, order_depth, position, memory)
        anchor = self._get_dynamic_anchor(float(mid), memory)
        old_anchor = self.params.get("anchor_price")
        try:
            self.params["anchor_price"] = anchor
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = old_anchor

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (a := memory.get("_dynamic_anchor")) is not None:
            out["DynAnchor"] = float(a)
        return out


# ── prosperity/strategies/round_3/vev_option_mm_v3.py ─────────────────────────────

class VEVOptionMMV3Strategy(BaseStrategy):
    """Tibo's 2-sided passive MM with z-score gating (default mode='none')."""

    # ── Z-score (self-contained from VELVET spot) ──────────────────────────
    def _compute_zscore(self, state: TradingState, memory: Dict[str, Any]) -> Optional[float]:
        S = self._get_spot(state)
        if S is None:
            return None
        window = int(self.params.get("zscore_window", 500))
        buf: List[float] = memory.setdefault("_velvet_buf", [])
        buf.append(S)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (S - mean) / std

    def _signal_state(self, z: Optional[float]) -> str:
        if z is None:
            return "neutral"
        threshold = float(self.params.get("zscore_threshold", 1.0))
        if z < -threshold:
            return "cheap"
        if z > threshold:
            return "expensive"
        return "neutral"

    def _quote_bid(self, book: BookSnapshot, signal: str, mode: str) -> Optional[int]:
        if book.best_bid is None:
            return None
        if mode in ("bid_only", "both"):
            if signal == "cheap" and bool(self.params.get("allow_taker", True)):
                return book.best_ask if book.best_ask is not None else book.best_bid + 1
            if signal == "expensive":
                return None  # skip bid when expensive
        bid = book.best_bid + 1
        if bool(self.params.get("prevent_crossing", False)):
            if book.best_ask is not None and bid >= book.best_ask:
                bid = book.best_ask - 1
        return bid

    def _quote_ask(self, book: BookSnapshot, signal: str, mode: str) -> Optional[int]:
        if book.best_ask is None:
            return None
        neutral_offset = int(self.params.get("ask_offset_neutral", 10))
        if mode in ("ask_adapt", "both"):
            if signal == "expensive":
                return book.best_ask - 1
            if signal == "cheap":
                return book.best_ask + neutral_offset + 5
        return book.best_ask - 1 + neutral_offset

    def _resolve_tte(self, state: TradingState) -> float:
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(self.params.get("tte_days_initial", 5.0)),
            self.params.get("historical_tte_by_day"),
        )
        ts_per_day = timestamp_units_per_day_from_params(self.params)
        return max(0.01, time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_per_day))

    def _get_spot(self, state: TradingState) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if od is None:
            return None
        bb = max(od.buy_orders.keys()) if od.buy_orders else None
        ba = min(od.sell_orders.keys()) if od.sell_orders else None
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return float(bb or ba or 0) or None

    def _post_orders(
        self,
        bid_px: Optional[int],
        ask_px: Optional[int],
        buy_cap: int,
        sell_cap: int,
    ) -> List[Order]:
        size_bid = int(self.params.get("maker_size_bid", 20))
        size_ask = int(self.params.get("maker_size_ask", 5))
        orders: List[Order] = []
        if bid_px is not None and bid_px > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(size_bid, buy_cap)))
        if ask_px is not None and ask_px > 0 and sell_cap > 0 and size_ask > 0:
            orders.append(Order(self.product, ask_px, -min(size_ask, sell_cap)))
        return orders

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
        mid = 0.5 * (book.best_bid + book.best_ask)
        if mid < float(self.params.get("min_quote_price", 2.0)):
            return [], 0

        z = self._compute_zscore(state, memory)
        memory["_zscore"] = z
        mode = str(self.params.get("zscore_exec_mode", "none"))
        signal = self._signal_state(z)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_px = self._quote_bid(book, signal, mode)
        ask_px = self._quote_ask(book, signal, mode)

        # Safety: prevent crossing
        if bid_px is not None and ask_px is not None and ask_px <= bid_px:
            ask_px = bid_px + 1

        orders = self._post_orders(bid_px, ask_px, buy_cap, sell_cap)
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_zscore")
        return {"z_velvet": round(z, 3)} if z is not None else {}

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'VELVETFRUIT_EXTRACT': {'anchor_alpha': 0.02,
                         'anchor_drift_bound': 2.0,
                         'anchor_price': 5250.0,
                         'ar_gain': 0.3,
                         'ar_shift_source': 'mid_smooth',
                         'full_capacity_on_empty': True,
                         'guard_inventory_dist': 40.0,
                         'guard_max_dist': 80.0,
                         'guard_min_dist': 0.0,
                         'guard_near_band': 0.0,
                         'guard_reversion_threshold': 7.5,
                         'guard_trend_alpha': 0.45,
                         'inventory_aversion_gamma': 0.001,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 30,
                         'maker_size_base_pct': 0.4,
                         'passive_unwind_skew_ticks': 1,
                         'passive_unwind_trigger': 0.38,
                         'pct_kept_for_takers': 0.005,
                         'position_limit': 200,
                         'strategy': 'r3_guarded_anchor_mm',
                         'take_edge_hi': 1.2,
                         'take_edge_lo': 0.6,
                         'tighten_ticks': 1,
                         'toxic_size_frac': 0.68,
                         'toxic_threshold': 0.6,
                         'toxic_window': 8,
                         'ts_increment': 100,
                         'unwind_take_edge': 3.0},
 'VEV_4000': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 4000,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_4500': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_boost_threshold': 0.001,
              'iv_delta_threshold': 0.0003,
              'iv_ewma_alpha': 0.3,
              'iv_ewma_fast_alpha': 0.1,
              'iv_ewma_slow_alpha': 0.02,
              'iv_passive_boost': 1.5,
              'iv_residual_gate': True,
              'iv_skip_threshold': 0.001,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 4500,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5000': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_boost_threshold': 0.001,
              'iv_delta_threshold': 0.0003,
              'iv_ewma_alpha': 0.3,
              'iv_ewma_fast_alpha': 0.1,
              'iv_ewma_slow_alpha': 0.02,
              'iv_passive_boost': 1.5,
              'iv_residual_gate': True,
              'iv_skip_threshold': 0.001,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 5000,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5100': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_boost_threshold': 0.001,
              'iv_delta_threshold': 0.0003,
              'iv_ewma_alpha': 0.3,
              'iv_ewma_fast_alpha': 0.1,
              'iv_ewma_slow_alpha': 0.02,
              'iv_passive_boost': 1.5,
              'iv_residual_gate': True,
              'iv_skip_threshold': 0.001,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 5100,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5200': {'ask_offset_neutral': 10,
              'ask_offset_sell': 1,
              'delta_sigma': 0.022,
              'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'maker_size_ask': 5,
              'maker_size_bid': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prevent_crossing': False,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'vev_option_mm_v3',
              'strike': 5200.0,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True,
              'zscore_bid_max': 4.0,
              'zscore_bid_scale': 2.0,
              'zscore_exec_mode': 'none',
              'zscore_threshold': 1.0,
              'zscore_window': 500},
 'VEV_5300': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_boost_threshold': 0.001,
              'iv_delta_threshold': 0.0003,
              'iv_ewma_alpha': 0.3,
              'iv_ewma_fast_alpha': 0.1,
              'iv_ewma_slow_alpha': 0.02,
              'iv_passive_boost': 1.5,
              'iv_residual_gate': True,
              'iv_skip_threshold': 0.001,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 5300,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_skip_threshold': 0.8,
              'zscore_window': 500},
 'VEV_5400': {'ask_offset_neutral': 10,
              'ask_offset_sell': 1,
              'delta_sigma': 0.022,
              'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'maker_size_ask': 5,
              'maker_size_bid': 20,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prevent_crossing': True,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'vev_option_mm_v3',
              'strike': 5400.0,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True,
              'zscore_bid_max': 4.0,
              'zscore_bid_scale': 2.0,
              'zscore_exec_mode': 'none',
              'zscore_threshold': 1.0,
              'zscore_window': 500}}

STRATEGY_CLASSES = {"gamma_scalp_zgated": GammaScalpZGatedStrategy, "r3_guarded_anchor_mm": R3GuardedAnchorMMStrategy, "vev_option_mm_v3": VEVOptionMMV3Strategy}

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
