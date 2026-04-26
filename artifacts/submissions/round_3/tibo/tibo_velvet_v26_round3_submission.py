from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
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


# ── prosperity/strategies/round_3/tibo/velvet_strat_v3.py ─────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
#  CLASS 1 — VELVETFRUIT MM v3 (same as v2 + z-score write to shared)
# ══════════════════════════════════════════════════════════════════════════════

class VelvetMMV3(BaseStrategy):
    """VELVETFRUIT MM: penny-improve + delta hedge + writes z-score to shared."""

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        """Rolling 500-tick z-score of VELVETFRUIT mid. Stored in memory + shared."""
        window = int(self.params.get("zscore_window", 500))
        buf: List[float] = memory.setdefault("_zs_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n    = len(buf)
        mean = sum(buf) / n
        var  = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std  = var ** 0.5
        if std < 1e-9:
            return None
        return (mid - mean) / std

    def _compute_quote_prices(self, book: BookSnapshot) -> Tuple[Optional[int], Optional[int]]:
        bid = (book.best_bid + 1) if book.best_bid is not None else None
        ask = (book.best_ask - 1) if book.best_ask is not None else None
        if bid is not None and ask is not None and bid >= ask:
            ask = bid + 1
        return bid, ask

    def _compute_sizes(self, effective_pos: int, limit: int) -> Tuple[float, float]:
        base     = float(self.params.get("maker_size_base_pct", 0.30)) * limit
        bid_size = max(0.0, base * (1.0 - effective_pos / limit))
        ask_size = max(0.0, base * (1.0 + effective_pos / limit))
        return bid_size, ask_size

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
    ) -> List[Order]:
        quote_buy  = min(buy_cap,  max(0, int(bid_size)))
        quote_sell = min(sell_cap, max(0, int(ask_size)))
        hard_stop  = 1.0 - float(self.params.get("pct_kept_for_takers", 0.15))
        inv_abs    = abs(position) / float(limit) if limit else 0.0
        if inv_abs >= hard_stop:
            if position > 0:
                quote_buy  = 0
            elif position < 0:
                quote_sell = 0
        orders: List[Order] = []
        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))
        return orders

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0

        raw_mid = book.mid_price or float(book.best_bid or book.best_ask or 0)
        mid = raw_mid if raw_mid else memory.get("_last_mid", 0.0)
        if raw_mid:
            memory["_last_mid"] = raw_mid

        self._smooth_mid(mid, memory)

        # ── Z-score: compute and share for VEV option strategies ──────────────
        z = self._compute_zscore(mid, memory)
        shared = memory.get("_shared", {})
        shared["velvet_zscore"] = z   # VEV strategies read this on NEXT tick

        # ── Delta hedge from VEV options ──────────────────────────────────────
        vev_delta     = float(shared.get("vev_total_delta", 0.0)) if bool(self.params.get("use_delta_hedge", True)) else 0.0
        effective_pos = position + int(round(vev_delta))

        limit    = self.position_limit()
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_price, ask_price = self._compute_quote_prices(book)
        bid_size, ask_size   = self._compute_sizes(effective_pos, limit)
        orders = self._passive_quotes(bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit)

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position":   position,
                "zscore":     round(z, 3) if z is not None else None,
                "vev_delta":  round(vev_delta, 1),
                "mid_smooth": round(memory.get("mid_smoothed", mid), 2),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        z = memory.get("_zs_buf")
        # surface current z if already computed
        buf = memory.get("_zs_buf", [])
        if len(buf) > 4:
            n = len(buf); mean = sum(buf)/n
            var = sum((x-mean)**2 for x in buf)/max(n-1,1); std = var**0.5
            if std > 1e-9:
                out["Z_velvet"] = (buf[-1] - mean) / std
        return out


# ══════════════════════════════════════════════════════════════════════════════
#  CLASS 2 — VEV option MM v3 (signal-gated sizing)
# ══════════════════════════════════════════════════════════════════════════════

class VEVOptionMMV3(BaseStrategy):
    """VEV option MM with VELVETFRUIT z-score-gated sizing and ask adaptation."""

    # ── Z-score (self-contained, from VELVETFRUIT spot) ──────────────────────

    def _compute_zscore(self, state: TradingState, memory: Dict[str, Any]) -> Optional[float]:
        """Rolling z-score of VELVETFRUIT spot, computed independently per VEV strategy.

        Each VEV strategy maintains its own 500-price buffer in its own memory.
        No dependency on VelvetMMV3 or shared dict — robust against tick ordering.
        """
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
        n    = len(buf)
        mean = sum(buf) / n
        var  = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std  = var ** 0.5
        if std < 1e-9:
            return None
        return (S - mean) / std

    def _get_zscore(self, state: TradingState, memory: Dict[str, Any]) -> Optional[float]:
        """Alias: compute z-score and store in memory for logging."""
        z = self._compute_zscore(state, memory)
        memory["_zscore"] = z
        return z

    def _signal_state(self, z: Optional[float]) -> str:
        """Map z-score to 'cheap' | 'neutral' | 'expensive'."""
        if z is None:
            return "neutral"
        threshold = float(self.params.get("zscore_threshold", 1.0))
        if z < -threshold:
            return "cheap"
        if z > threshold:
            return "expensive"
        return "neutral"

    def _quote_bid(self, book: BookSnapshot, signal: str, mode: str) -> Optional[int]:
        """Bid price based on signal + execution mode.

        Execution approaches:
          "none" / "ask_adapt": always penny-improve with crossing prevention.
          "bid_only" / "both":
            cheap     → intentional cross: bid at best_ask (taker, fills immediately)
            neutral   → penny-improve (with crossing prevention)
            expensive → skip: return None (no bid → zero passive fills this tick)

        Crossing prevention applies to ALL non-intentional cases:
          On 1-tick spreads (bid=X, ask=X+1), bid+1 would = ask and become an
          unintentional taker. We fall back to bid=best_bid (join queue, passive).
          Only the explicit "cheap" signal is allowed to cross the spread.
        """
        if book.best_bid is None:
            return None

        if mode in ("bid_only", "both"):
            if signal == "cheap" and bool(self.params.get("allow_taker", True)):
                # Intentional taker: cross the spread (active buy, fills immediately)
                return book.best_ask if book.best_ask is not None else book.best_bid + 1
            if signal == "expensive":
                return None   # skip bid: don't accumulate when expensive

        # Default: penny-improve. Optional crossing prevention (per-strike param).
        # For strikes with persistently 1-tick spreads (VEV_5400), set
        # prevent_crossing=True to avoid unintentional taker fills that hurt PnL.
        # For wider-spread strikes (VEV_5200/5300), leave False to allow the
        # occasional crossing when the spread narrows — on average profitable.
        bid = book.best_bid + 1
        if bool(self.params.get("prevent_crossing", False)):
            if book.best_ask is not None and bid >= book.best_ask:
                bid = book.best_ask - 1   # join bid (passive)
        return bid

    def _quote_ask(self, book: BookSnapshot, signal: str, mode: str) -> Optional[int]:
        """Ask price based on signal + execution mode.

        "ask_adapt" / "both":
          expensive → penny-improve ask (best_ask-1): willing to sell at elevated price
          neutral   → wide ask (best_ask + ask_offset_neutral): rarely fills
          cheap     → very wide ask (hold longs, don't sell into dip)
        "none" / "bid_only": always wide ask
        """
        if book.best_ask is None:
            return None

        neutral_offset = int(self.params.get("ask_offset_neutral", 10))

        if mode in ("ask_adapt", "both"):
            if signal == "expensive":
                return book.best_ask - 1   # penny-improve: sell some at peak
            if signal == "cheap":
                return book.best_ask + neutral_offset + 5   # extra wide: don't sell dip
        return book.best_ask - 1 + neutral_offset   # default: wide, rarely fills

    # ── Time to expiry ────────────────────────────────────────────────────────

    def _resolve_tte(self, state: TradingState) -> float:
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(self.params.get("tte_days_initial", 5.0)),
            self.params.get("historical_tte_by_day"),
        )
        ts_per_day = timestamp_units_per_day_from_params(self.params)
        return max(0.01, time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_per_day))

    # ── Spot from order depths ────────────────────────────────────────────────

    def _get_spot(self, state: TradingState) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if od is None:
            return None
        bids = od.buy_orders
        asks = od.sell_orders
        bb = max(bids.keys()) if bids else None
        ba = min(asks.keys()) if asks else None
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return float(bb or ba or 0) or None

    # ── Quoting ───────────────────────────────────────────────────────────────

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

    def _publish_delta(self, memory: Dict[str, Any], position: int, S: float, K: float, T: float) -> None:
        sigma = float(self.params.get("delta_sigma", 0.022))
        delta = call_delta(S, K, T, sigma)
        shared = memory.get("_shared", {})
        shared["vev_total_delta"] = shared.get("vev_total_delta", 0.0) + position * delta

    # ── Main tick ─────────────────────────────────────────────────────────────

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

        T = self._resolve_tte(state)
        K = float(self.params["strike"])
        S = self._get_spot(state)
        if S is not None:
            self._publish_delta(memory, position, S, K, T)

        # ── Z-score signal → bid/ask prices ──────────────────────────────────
        z      = self._get_zscore(state, memory)
        mode   = str(self.params.get("zscore_exec_mode", "bid_only"))
        signal = self._signal_state(z)

        buy_cap  = self.buy_capacity(position)
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


# ── prosperity/strategies/round_3/tibo/velvet_strat_v25.py ────────────────────────

class VelvetMMV25(VelvetMMV3):
    """VELVETFRUIT MM for v25.

    Passive penny-improve + inventory-adaptive sizing + implicit delta hedge
    from accumulated VEV option positions. Writes z-score to shared dict for
    VEVOptionMMV25 (1-tick lag, negligible at 500-tick window).

    Identical to VelvetMMV3. Kept as a named class so v25 has its own
    identity and can diverge independently in future versions.
    """


class VEVOptionMMV25(VEVOptionMMV3):
    """VEV option MM for v25 (strikes 4000 / 5200 / 5300 / 5400).

    Penny-improve bid + wide ask (rarely sells) → passively accumulates long
    calls. Z-score adapts the ask side only (ask_adapt mode):
      expensive → tighten ask (sell some at peak)
      cheap     → widen ask extra (hold through dip)
    Never skips bids — always accumulates regardless of z-score.

    Identical to VEVOptionMMV3. Kept as a named class so v25 has its own
    identity and can diverge independently in future versions.
    """


class GammaScalpV25(GammaScalpZGatedStrategy):
    """VEV option accumulation for v25 (strikes 4500 / 5000 / 5100).

    Active taker when ask ≤ BS_fair + edge_ticks, passive penny-improve bid
    otherwise. Z-score gates entry (skip_when_expensive). Unwinds near expiry
    (TTE < unwind_tte_threshold).

    These strikes were excluded from v3 (illiquid in passive fill model) but
    earn significant MTM gains in v24/v25 via active taker entries.

    Identical to GammaScalpZGatedStrategy. Kept as a named class so v25 has
    its own identity and can diverge independently in future versions.
    """


# ── prosperity/strategies/round_3/tibo/velvet_strat_v26.py ────────────────────────

class VelvetMMV26(VelvetMMV25):
    """VELVETFRUIT MM for v26.

    Identical to VelvetMMV25. Delta hedge disabled via config
    (use_delta_hedge=False) — ablation confirmed zero PnL impact.
    """


class VEVOptionMMV26(VEVOptionMMV25):
    """VEV option MM for v26 (strikes 4000 / 5200 / 5300 / 5400).

    Identical to VEVOptionMMV25. Z-score ask adaptation disabled via config
    (zscore_exec_mode="none") — ablation confirmed zero PnL impact.
    """


class GammaScalpV26(GammaScalpV25):
    """VEV option accumulation for v26 (strikes 4500 / 5000 / 5100).

    Identical to GammaScalpV25. skip_when_expensive is product-specific:
      VEV_4500 / 5000: skip_when_expensive=False  (+2,326 / +2,265)
      VEV_5100:        skip_when_expensive=True   (removing costs -2,410)
    Controlled via config, not code.
    """

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'VELVETFRUIT_EXTRACT': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size_base_pct': 0.3,
                         'mid_smooth_half_life': 20,
                         'mid_smooth_window': 50,
                         'pct_kept_for_takers': 0.15,
                         'position_limit': 200,
                         'strategy': 'velvet_strat_v26_mm',
                         'ts_increment': 100,
                         'use_delta_hedge': False,
                         'zscore_window': 500},
 'VEV_4000': {'ask_offset_neutral': 1,
              'ask_offset_sell': 1,
              'delta_sigma': 0.022,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_size_ask': 20,
              'maker_size_bid': 20,
              'min_quote_price': 2.0,
              'position_limit': 300,
              'strategy': 'velvet_strat_v26_opt',
              'strike': 4000.0,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'zscore_bid_max': 4.0,
              'zscore_bid_scale': 2.0,
              'zscore_exec_mode': 'none',
              'zscore_threshold': 1.0,
              'zscore_window': 500},
 'VEV_4500': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'position_limit': 300,
              'sell_when_very_expensive': False,
              'skip_when_expensive': False,
              'strategy': 'gamma_scalp_v26',
              'strike': 4500,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5000': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'position_limit': 300,
              'sell_when_very_expensive': False,
              'skip_when_expensive': False,
              'strategy': 'gamma_scalp_v26',
              'strike': 5000,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5100': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'position_limit': 300,
              'sell_when_very_expensive': False,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_v26',
              'strike': 5100,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5200': {'ask_offset_neutral': 10,
              'ask_offset_sell': 1,
              'delta_sigma': 0.022,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_size_ask': 5,
              'maker_size_bid': 20,
              'min_quote_price': 2.0,
              'position_limit': 300,
              'strategy': 'velvet_strat_v26_opt',
              'strike': 5200.0,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'zscore_bid_max': 4.0,
              'zscore_bid_scale': 2.0,
              'zscore_exec_mode': 'none',
              'zscore_threshold': 1.0,
              'zscore_window': 500},
 'VEV_5300': {'ask_offset_neutral': 10,
              'ask_offset_sell': 1,
              'delta_sigma': 0.022,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_size_ask': 5,
              'maker_size_bid': 20,
              'min_quote_price': 2.0,
              'position_limit': 300,
              'strategy': 'velvet_strat_v26_opt',
              'strike': 5300.0,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'zscore_bid_max': 4.0,
              'zscore_bid_scale': 2.0,
              'zscore_exec_mode': 'none',
              'zscore_threshold': 1.0,
              'zscore_window': 500},
 'VEV_5400': {'ask_offset_neutral': 10,
              'ask_offset_sell': 1,
              'delta_sigma': 0.022,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_size_ask': 5,
              'maker_size_bid': 20,
              'min_quote_price': 2.0,
              'position_limit': 300,
              'prevent_crossing': True,
              'strategy': 'velvet_strat_v26_opt',
              'strike': 5400.0,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'zscore_bid_max': 4.0,
              'zscore_bid_scale': 2.0,
              'zscore_exec_mode': 'none',
              'zscore_threshold': 1.0,
              'zscore_window': 500}}

STRATEGY_CLASSES = {"gamma_scalp_v26": GammaScalpV26, "velvet_strat_v26_mm": VelvetMMV26, "velvet_strat_v26_opt": VEVOptionMMV26}

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
