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


# ── prosperity/strategies/round_4/oracle_replay_d3.py ─────────────────────────────

ORACLE_TRADES_R4D3 = {
    400:{'HYDROGEL_PACK':('BUY',11,10011)},
    800:{'HYDROGEL_PACK':('BUY',14,10010)},
    900:{'HYDROGEL_PACK':('BUY',14,10008)},
    1000:{'HYDROGEL_PACK':('BUY',15,10011)},
    1200:{'HYDROGEL_PACK':('BUY',12,10010)},
    1700:{'HYDROGEL_PACK':('BUY',8,10008)},
    1800:{'VEV_5300':('SELL',22,59),'VEV_5400':('SELL',8,21)},
    1900:{'VEV_5200':('SELL',26,120),'VEV_5300':('SELL',21,59)},
    2200:{'VEV_5200':('SELL',7,120)},
    2400:{'HYDROGEL_PACK':('SELL',4,10014)},
    3500:{'VELVETFRUIT_EXTRACT':('BUY',19,5294),'VEV_5100':('BUY',9,200),'VEV_5200':('BUY',22,118),'VEV_5300':('BUY',16,57)},
    3600:{'VEV_5200':('BUY',12,118)},
    4400:{'HYDROGEL_PACK':('SELL',12,10012)},
    4600:{'HYDROGEL_PACK':('SELL',9,10015)},
    4700:{'VEV_4000':('SELL',4,1296),'VEV_4500':('SELL',4,796),'VEV_5000':('SELL',4,297),'VEV_5100':('SELL',4,202),'VEV_5200':('SELL',4,120)},
    4900:{'HYDROGEL_PACK':('SELL',13,10012)},
    5100:{'HYDROGEL_PACK':('SELL',13,10012)},
    5200:{'HYDROGEL_PACK':('SELL',14,10015)},
    5300:{'HYDROGEL_PACK':('SELL',14,10016)},
    5400:{'HYDROGEL_PACK':('SELL',14,10017)},
    5500:{'HYDROGEL_PACK':('SELL',11,10014)},
    5600:{'HYDROGEL_PACK':('SELL',15,10012)},
    5700:{'HYDROGEL_PACK':('SELL',11,10014)},
    5800:{'HYDROGEL_PACK':('SELL',15,10014),'VEV_4000':('SELL',5,1296),'VEV_4500':('SELL',5,796),'VEV_5000':('SELL',5,297),'VEV_5100':('SELL',5,202),'VEV_5200':('SELL',5,120),'VEV_5300':('SELL',5,58)},
    5900:{'HYDROGEL_PACK':('SELL',10,10013)},
    6000:{'HYDROGEL_PACK':('SELL',11,10011)},
    6200:{'VELVETFRUIT_EXTRACT':('SELL',16,5295),'VEV_5100':('SELL',11,201),'VEV_5200':('SELL',26,119),'VEV_5300':('SELL',18,58)},
    6300:{'VELVETFRUIT_EXTRACT':('SELL',24,5294)},
    6500:{'VELVETFRUIT_EXTRACT':('SELL',23,5294),'VEV_5100':('SELL',11,200)},
    6600:{'VELVETFRUIT_EXTRACT':('SELL',22,5295),'VEV_5000':('SELL',6,295),'VEV_5100':('SELL',6,201),'VEV_5200':('SELL',19,119),'VEV_5300':('SELL',24,58)},
    6700:{'VELVETFRUIT_EXTRACT':('SELL',24,5294),'VEV_5100':('SELL',12,200),'VEV_5200':('SELL',24,118)},
    6800:{'VELVETFRUIT_EXTRACT':('SELL',18,5295),'VEV_5000':('SELL',8,295),'VEV_5100':('SELL',8,201),'VEV_5200':('SELL',25,119),'VEV_5300':('SELL',18,58)},
    6900:{'VELVETFRUIT_EXTRACT':('SELL',54,5294),'VEV_5100':('SELL',34,200),'VEV_5200':('SELL',34,118)},
    7000:{'VELVETFRUIT_EXTRACT':('SELL',18,5294),'VEV_5100':('SELL',11,200),'VEV_5200':('SELL',34,118)},
    7100:{'VELVETFRUIT_EXTRACT':('SELL',20,5294),'VEV_5100':('SELL',32,200),'VEV_5200':('SELL',32,118)},
    7200:{'VEV_5100':('SELL',6,200),'VEV_5200':('SELL',25,118)},
    7300:{'VEV_5100':('SELL',7,200),'VEV_5200':('SELL',22,118)},
    7400:{'HYDROGEL_PACK':('SELL',13,10012),'VEV_5000':('SELL',11,295),'VEV_5100':('SELL',11,201),'VEV_5200':('SELL',32,119),'VEV_5300':('SELL',25,58)},
    7500:{'VEV_5000':('SELL',7,294),'VEV_5100':('SELL',23,199),'VEV_5200':('SELL',19,118),'VEV_5300':('SELL',21,57)},
    7600:{'VEV_4000':('SELL',5,1296),'VEV_4500':('SELL',5,796),'VEV_5000':('SELL',5,297),'VEV_5100':('SELL',5,202),'VEV_5300':('SELL',5,58)},
    7700:{'VEV_5000':('SELL',11,295),'VEV_5100':('SELL',28,200),'VEV_5300':('SELL',28,57)},
    7800:{'VEV_5000':('SELL',29,296),'VEV_5100':('SELL',29,202),'VEV_5300':('SELL',18,58),'VEV_5400':('SELL',6,21)},
    7900:{'VEV_5000':('SELL',7,296),'VEV_5100':('SELL',7,202),'VEV_5300':('SELL',29,58)},
    8000:{'VEV_5000':('SELL',7,297),'VEV_5100':('SELL',24,202),'VEV_5300':('SELL',6,59),'VEV_5400':('SELL',6,21)},
    8100:{'VEV_5000':('SELL',20,297),'VEV_5100':('SELL',7,203),'VEV_5300':('SELL',19,59),'VEV_5400':('SELL',19,21)},
    8200:{'VEV_5000':('SELL',12,297),'VEV_5100':('SELL',28,202),'VEV_5300':('SELL',10,59),'VEV_5400':('SELL',10,21)},
    8300:{'VEV_5000':('SELL',11,298),'VEV_5300':('SELL',26,59),'VEV_5400':('SELL',26,21)},
    8400:{'VEV_5000':('SELL',11,296),'VEV_5300':('SELL',21,58),'VEV_5400':('SELL',25,20),'VEV_5500':('SELL',25,7)},
    8500:{'VEV_5000':('SELL',29,296),'VEV_5400':('SELL',26,20),'VEV_5500':('SELL',26,7)},
    8600:{'VEV_5000':('SELL',9,296),'VEV_5400':('SELL',25,20),'VEV_5500':('SELL',25,7)},
    8700:{'VEV_5000':('SELL',29,296),'VEV_5400':('SELL',6,21),'VEV_5500':('SELL',25,7)},
    8800:{'VEV_5000':('SELL',11,297),'VEV_5400':('SELL',9,21),'VEV_5500':('SELL',19,7)},
    8900:{'VEV_4500':('SELL',12,791),'VEV_5000':('SELL',12,297),'VEV_5400':('SELL',20,21),'VEV_5500':('SELL',20,7)},
    9000:{'VEV_4500':('SELL',8,790),'VEV_5000':('SELL',25,296),'VEV_5400':('SELL',27,20),'VEV_5500':('SELL',27,7)},
    9100:{'VEV_4500':('SELL',11,792),'VEV_5000':('SELL',11,298),'VEV_5400':('SELL',23,21),'VEV_5500':('SELL',23,7)},
    9200:{'VEV_4500':('SELL',12,791),'VEV_5000':('SELL',12,297),'VEV_5400':('SELL',5,21),'VEV_5500':('SELL',23,7)},
    9300:{'VEV_5000':('SELL',8,295),'VEV_5400':('SELL',26,20),'VEV_5500':('SELL',26,7)},
    9400:{'VEV_4500':('SELL',9,790),'VEV_5400':('SELL',25,20),'VEV_5500':('SELL',25,7)},
    9500:{'VEV_4500':('SELL',12,789),'VEV_5400':('SELL',8,20),'VEV_5500':('SELL',28,7)},
    9600:{'VEV_4500':('SELL',7,789),'VEV_5500':('SELL',8,7)},
    9700:{'HYDROGEL_PACK':('BUY',10,10009),'VEV_4500':('SELL',7,790)},
    9800:{'HYDROGEL_PACK':('BUY',12,10007),'VEV_4500':('SELL',6,789)},
    9900:{'HYDROGEL_PACK':('BUY',14,10004),'VEV_4500':('SELL',11,788)},
    10000:{'HYDROGEL_PACK':('BUY',14,10003),'VEV_4500':('SELL',7,788)},
    10100:{'HYDROGEL_PACK':('BUY',11,10005),'VEV_4500':('SELL',12,788)},
    10200:{'HYDROGEL_PACK':('BUY',14,10002)},
    10300:{'HYDROGEL_PACK':('BUY',12,10006)},
    10400:{'HYDROGEL_PACK':('BUY',11,10008)},
    10500:{'HYDROGEL_PACK':('BUY',11,10006)},
    10600:{'HYDROGEL_PACK':('BUY',13,10009)},
    10700:{'HYDROGEL_PACK':('BUY',13,10007)},
    10800:{'HYDROGEL_PACK':('BUY',10,10004)},
    10900:{'HYDROGEL_PACK':('BUY',13,10001)},
    11000:{'HYDROGEL_PACK':('BUY',13,10003)},
    11100:{'HYDROGEL_PACK':('BUY',11,10005)},
    11200:{'HYDROGEL_PACK':('BUY',11,10007)},
    11300:{'HYDROGEL_PACK':('BUY',13,10008)},
    11400:{'HYDROGEL_PACK':('BUY',11,10005),'VEV_4500':('SELL',9,786)},
    11500:{'HYDROGEL_PACK':('BUY',13,10007),'VEV_4500':('SELL',12,785)},
    11600:{'HYDROGEL_PACK':('BUY',10,10007),'VEV_4500':('SELL',12,785)},
    11700:{'HYDROGEL_PACK':('BUY',14,10007),'VEV_4500':('SELL',12,785)},
    11800:{'HYDROGEL_PACK':('BUY',12,10008),'VEV_4500':('SELL',8,785)},
    11900:{'HYDROGEL_PACK':('BUY',15,10009),'VEV_4500':('SELL',8,785)},
    12000:{'HYDROGEL_PACK':('BUY',13,10011),'VEV_4000':('SELL',9,1284),'VEV_4500':('SELL',8,786)},
    12100:{'HYDROGEL_PACK':('BUY',11,10013),'VEV_4500':('SELL',8,786)},
    12200:{'VEV_4500':('SELL',7,784)},
    12300:{'VEV_4500':('SELL',8,784)},
    13500:{'VEV_4500':('SELL',12,782)},
    13600:{'VEV_4500':('SELL',6,782)},
    13900:{'VEV_4500':('SELL',9,781)},
    14000:{'VEV_4500':('SELL',6,781)},
    14100:{'VEV_4500':('SELL',9,782)},
    14200:{'VEV_4500':('SELL',12,782)},
    14300:{'VEV_4500':('SELL',7,782)},
    14400:{'VEV_4000':('SELL',9,1282),'VEV_4500':('SELL',8,784)},
    14500:{'VEV_4000':('SELL',11,1280),'VEV_4500':('SELL',7,782)},
    14600:{'VEV_4500':('SELL',4,781)},
    14700:{'VEV_4000':('SELL',7,1280)},
    14800:{'VEV_4000':('SELL',9,1281)},
    14900:{'VEV_4000':('SELL',13,1281)},
    15100:{'VEV_4000':('SELL',7,1279)},
    16200:{'VEV_4000':('SELL',13,1278)},
    16300:{'VEV_4000':('SELL',15,1277)},
    16400:{'VEV_4000':('SELL',13,1278)},
    16500:{'VEV_4000':('SELL',11,1278)},
    16600:{'VEV_4000':('SELL',9,1277)},
    16800:{'VEV_4000':('SELL',11,1276)},
    17000:{'VEV_4000':('SELL',11,1276)},
    17600:{'VEV_4000':('SELL',2,1283)},
    18100:{'VEV_4000':('SELL',11,1274)},
    30200:{'HYDROGEL_PACK':('SELL',15,10033)},
    30300:{'HYDROGEL_PACK':('SELL',12,10034)},
    30400:{'HYDROGEL_PACK':('SELL',14,10034)},
    30600:{'HYDROGEL_PACK':('SELL',15,10033)},
    31200:{'HYDROGEL_PACK':('SELL',15,10032)},
    31300:{'HYDROGEL_PACK':('SELL',10,10032)},
    31400:{'HYDROGEL_PACK':('SELL',11,10033),'VELVETFRUIT_EXTRACT':('BUY',7,5264)},
    31500:{'HYDROGEL_PACK':('SELL',10,10035)},
    31600:{'HYDROGEL_PACK':('SELL',13,10036)},
    31700:{'HYDROGEL_PACK':('SELL',12,10036)},
    31800:{'HYDROGEL_PACK':('SELL',15,10036)},
    31900:{'HYDROGEL_PACK':('SELL',15,10034)},
    32000:{'HYDROGEL_PACK':('SELL',12,10034)},
    32100:{'HYDROGEL_PACK':('SELL',12,10037)},
    32200:{'HYDROGEL_PACK':('SELL',15,10036)},
    32300:{'HYDROGEL_PACK':('SELL',11,10038)},
    32400:{'HYDROGEL_PACK':('SELL',13,10039)},
    32500:{'HYDROGEL_PACK':('SELL',11,10037)},
    32600:{'HYDROGEL_PACK':('SELL',10,10035)},
    32700:{'HYDROGEL_PACK':('SELL',11,10035),'VELVETFRUIT_EXTRACT':('SELL',7,5265)},
    32800:{'HYDROGEL_PACK':('SELL',15,10037)},
    32900:{'HYDROGEL_PACK':('SELL',10,10038)},
    33000:{'HYDROGEL_PACK':('SELL',12,10037)},
    33100:{'HYDROGEL_PACK':('SELL',11,10036)},
    33200:{'HYDROGEL_PACK':('SELL',10,10036)},
    33300:{'HYDROGEL_PACK':('SELL',12,10033)},
    33500:{'HYDROGEL_PACK':('SELL',10,10031)},
    34000:{'VEV_4000':('SELL',7,1263)},
    34100:{'VEV_4000':('SELL',9,1263)},
    34200:{'VEV_4000':('SELL',13,1263)},
    34300:{'VEV_4000':('SELL',10,1262)},
    34400:{'VEV_4000':('SELL',14,1262)},
    34500:{'VEV_4000':('SELL',12,1262)},
    34600:{'VEV_4000':('SELL',13,1261)},
    34700:{'VEV_4000':('SELL',14,1262)},
    34800:{'VEV_4000':('SELL',14,1261)},
    34900:{'VEV_4000':('SELL',13,1261)},
    35000:{'VEV_4000':('SELL',6,1263)},
    37400:{'HYDROGEL_PACK':('BUY',15,10030)},
    37800:{'HYDROGEL_PACK':('BUY',13,10027)},
    37900:{'HYDROGEL_PACK':('BUY',13,10027)},
    38000:{'HYDROGEL_PACK':('BUY',10,10029)},
    38100:{'HYDROGEL_PACK':('BUY',10,10030)},
    38400:{'HYDROGEL_PACK':('BUY',13,10032)},
    38500:{'HYDROGEL_PACK':('BUY',14,10029)},
    38600:{'HYDROGEL_PACK':('BUY',12,10030)},
    38700:{'HYDROGEL_PACK':('BUY',15,10027)},
    38800:{'HYDROGEL_PACK':('BUY',12,10028)},
    38900:{'HYDROGEL_PACK':('BUY',15,10028)},
    39000:{'HYDROGEL_PACK':('BUY',15,10028)},
    39100:{'HYDROGEL_PACK':('BUY',14,10027)},
    39200:{'HYDROGEL_PACK':('BUY',10,10025)},
    39300:{'HYDROGEL_PACK':('BUY',11,10028)},
    39400:{'HYDROGEL_PACK':('BUY',15,10030)},
    39500:{'HYDROGEL_PACK':('BUY',10,10030)},
    39600:{'HYDROGEL_PACK':('BUY',14,10033)},
    39800:{'HYDROGEL_PACK':('BUY',14,10035)},
    39900:{'HYDROGEL_PACK':('BUY',11,10035)},
    42300:{'VEV_5200':('BUY',25,87)},
    42400:{'VEV_5200':('BUY',24,87),'VEV_5300':('BUY',9,38)},
    42500:{'VEV_5200':('BUY',33,87),'VEV_5300':('BUY',9,38)},
    42600:{'VELVETFRUIT_EXTRACT':('BUY',54,5248),'VEV_5000':('BUY',8,251),'VEV_5100':('BUY',8,159),'VEV_5200':('BUY',20,86),'VEV_5300':('BUY',26,38)},
    42700:{'VELVETFRUIT_EXTRACT':('BUY',71,5248),'VEV_5000':('BUY',8,251),'VEV_5100':('BUY',8,159),'VEV_5200':('BUY',23,86),'VEV_5300':('BUY',27,38)},
    42800:{'VELVETFRUIT_EXTRACT':('BUY',16,5248),'VEV_5000':('BUY',9,251),'VEV_5100':('BUY',33,160),'VEV_5200':('BUY',33,86),'VEV_5300':('BUY',26,38)},
    42900:{'VELVETFRUIT_EXTRACT':('BUY',66,5249),'VEV_5000':('BUY',25,252),'VEV_5100':('BUY',25,160),'VEV_5200':('BUY',11,86),'VEV_5300':('BUY',25,38)},
    43000:{'VELVETFRUIT_EXTRACT':('BUY',20,5247),'VEV_5000':('BUY',12,250),'VEV_5100':('BUY',25,159),'VEV_5200':('BUY',12,85),'VEV_5300':('BUY',16,37),'VEV_5400':('BUY',16,11)},
    43100:{'VELVETFRUIT_EXTRACT':('BUY',21,5247),'VEV_5000':('BUY',22,251),'VEV_5100':('BUY',22,159),'VEV_5200':('BUY',22,86),'VEV_5300':('BUY',6,37)},
    43200:{'VELVETFRUIT_EXTRACT':('BUY',21,5249),'VEV_5000':('BUY',8,252),'VEV_5100':('BUY',26,161),'VEV_5200':('BUY',26,87),'VEV_5300':('BUY',19,38)},
    44500:{'VELVETFRUIT_EXTRACT':('SELL',25,5251),'VEV_5100':('SELL',7,162)},
    44600:{'VELVETFRUIT_EXTRACT':('SELL',17,5251),'VEV_5100':('SELL',23,162)},
    44900:{'HYDROGEL_PACK':('BUY',13,10039)},
    45100:{'HYDROGEL_PACK':('BUY',9,10033)},
    45300:{'HYDROGEL_PACK':('BUY',9,10031)},
    45400:{'HYDROGEL_PACK':('BUY',10,10040)},
    45600:{'VEV_4000':('BUY',4,1248),'VEV_4500':('BUY',4,748),'VEV_5000':('BUY',4,251),'VEV_5100':('BUY',4,160),'VEV_5200':('BUY',4,86),'VEV_5300':('BUY',4,38)},
    47000:{'VELVETFRUIT_EXTRACT':('BUY',7,5247),'VEV_5100':('BUY',10,161),'VEV_5200':('BUY',10,87)},
    47100:{'HYDROGEL_PACK':('BUY',6,10034)},
    47200:{'VEV_4000':('BUY',3,1249),'VEV_4500':('BUY',3,749),'VEV_5000':('BUY',3,252),'VEV_5100':('BUY',3,160),'VEV_5200':('BUY',3,87),'VEV_5300':('BUY',3,38)},
    47400:{'HYDROGEL_PACK':('BUY',11,10039)},
    48400:{'VELVETFRUIT_EXTRACT':('BUY',11,5249)},
    50900:{'VELVETFRUIT_EXTRACT':('BUY',10,5250)},
    51000:{'VELVETFRUIT_EXTRACT':('BUY',17,5251),'VEV_5000':('BUY',11,254),'VEV_5100':('BUY',11,162),'VEV_5200':('BUY',26,88)},
    52900:{'VEV_5200':('BUY',7,88)},
    53000:{'HYDROGEL_PACK':('BUY',11,10047)},
    53400:{'VELVETFRUIT_EXTRACT':('BUY',71,5251),'VEV_5100':('BUY',31,162),'VEV_5200':('BUY',31,88)},
    53500:{'VEV_5100':('BUY',7,162),'VEV_5200':('BUY',30,88)},
    53600:{'VEV_5200':('BUY',9,88)},
    53700:{'HYDROGEL_PACK':('BUY',7,10049),'VELVETFRUIT_EXTRACT':('BUY',57,5251),'VEV_5000':('BUY',25,254),'VEV_5100':('BUY',25,162),'VEV_5200':('BUY',25,88)},
    53800:{'VEV_5000':('BUY',7,254),'VEV_5100':('BUY',23,162),'VEV_5200':('BUY',23,88)},
    54200:{'VEV_5000':('BUY',7,254),'VEV_5100':('BUY',22,162),'VEV_5200':('BUY',22,88)},
    54300:{'VEV_5100':('BUY',7,162),'VEV_5200':('BUY',28,88)},
    54400:{'VEV_4000':('BUY',2,1249),'VEV_4500':('BUY',2,749),'VEV_5000':('BUY',2,252),'VEV_5100':('BUY',2,160),'VEV_5200':('BUY',2,87),'VEV_5300':('BUY',2,38)},
    54500:{'VEV_5100':('BUY',12,162),'VEV_5200':('BUY',34,88)},
    54800:{'VEV_5200':('BUY',8,88)},
    55100:{'VEV_5100':('BUY',6,162),'VEV_5200':('BUY',6,88)},
    55200:{'VEV_5100':('BUY',10,162),'VEV_5200':('BUY',29,88)},
    57100:{'VELVETFRUIT_EXTRACT':('SELL',58,5255),'VEV_5000':('SELL',30,257),'VEV_5100':('SELL',6,166),'VEV_5200':('SELL',30,91),'VEV_5300':('SELL',8,41)},
    57400:{'VELVETFRUIT_EXTRACT':('SELL',24,5256),'VEV_5000':('SELL',7,258),'VEV_5100':('SELL',25,166),'VEV_5200':('SELL',7,92),'VEV_5300':('SELL',18,41)},
    57500:{'VELVETFRUIT_EXTRACT':('SELL',15,5256),'VEV_5000':('SELL',22,257),'VEV_5100':('SELL',22,166),'VEV_5200':('SELL',22,91),'VEV_5300':('SELL',8,41)},
    57600:{'VELVETFRUIT_EXTRACT':('SELL',10,5257),'VEV_5000':('SELL',6,257),'VEV_5100':('SELL',6,166),'VEV_5200':('SELL',28,91)},
    57700:{'VELVETFRUIT_EXTRACT':('SELL',70,5255),'VEV_5000':('SELL',7,257),'VEV_5100':('SELL',7,166),'VEV_5200':('SELL',28,91)},
    57800:{'VEV_5100':('SELL',20,165),'VEV_5200':('SELL',8,91)},
    57900:{'VELVETFRUIT_EXTRACT':('SELL',51,5255),'VEV_5000':('SELL',12,257),'VEV_5100':('SELL',12,166),'VEV_5200':('SELL',35,91)},
    58000:{'VELVETFRUIT_EXTRACT':('SELL',20,5255),'VEV_5200':('SELL',7,91)},
    58100:{'VELVETFRUIT_EXTRACT':('SELL',6,5257),'VEV_5000':('SELL',6,257),'VEV_5200':('SELL',20,91)},
    58200:{'VELVETFRUIT_EXTRACT':('SELL',62,5255),'VEV_5000':('SELL',33,257),'VEV_5100':('SELL',9,166),'VEV_5200':('SELL',33,91),'VEV_5300':('SELL',5,41)},
    58300:{'VELVETFRUIT_EXTRACT':('SELL',48,5255),'VEV_5000':('SELL',11,257),'VEV_5100':('SELL',11,166),'VEV_5200':('SELL',29,91)},
    58400:{'VELVETFRUIT_EXTRACT':('SELL',19,5256),'VEV_5000':('SELL',17,257),'VEV_5100':('SELL',24,166),'VEV_5200':('SELL',24,91),'VEV_5300':('SELL',5,41)},
    58500:{'VEV_5100':('SELL',8,165)},
    58600:{'VELVETFRUIT_EXTRACT':('SELL',17,5256),'VEV_5100':('SELL',27,166),'VEV_5200':('SELL',27,91),'VEV_5300':('SELL',15,41)},
    58700:{'VEV_5100':('SELL',26,165),'VEV_5200':('SELL',26,91)},
    58800:{'VEV_5100':('SELL',7,166),'VEV_5200':('SELL',24,91)},
    59700:{'VEV_5100':('BUY',11,164)},
    59800:{'VEV_5100':('BUY',12,164)},
    60200:{'HYDROGEL_PACK':('SELL',15,10050),'VEV_5100':('BUY',7,164)},
    60300:{'HYDROGEL_PACK':('SELL',10,10053),'VELVETFRUIT_EXTRACT':('BUY',17,5253),'VEV_5000':('BUY',11,256),'VEV_5100':('BUY',30,164),'VEV_5200':('BUY',30,89)},
    60400:{'VEV_5100':('BUY',10,164),'VEV_5200':('BUY',10,89)},
    60500:{'HYDROGEL_PACK':('SELL',11,10052),'VELVETFRUIT_EXTRACT':('BUY',16,5253),'VEV_5000':('BUY',9,256),'VEV_5100':('BUY',25,164),'VEV_5200':('BUY',25,89)},
    60600:{'HYDROGEL_PACK':('SELL',12,10052),'VELVETFRUIT_EXTRACT':('BUY',19,5252),'VEV_5000':('BUY',9,255),'VEV_5100':('BUY',25,163),'VEV_5200':('BUY',25,89),'VEV_5300':('BUY',18,39)},
    60700:{'HYDROGEL_PACK':('SELL',13,10050),'VELVETFRUIT_EXTRACT':('BUY',54,5252),'VEV_5000':('BUY',25,255),'VEV_5100':('BUY',25,163),'VEV_5200':('BUY',25,88),'VEV_5300':('BUY',22,39)},
    60800:{'HYDROGEL_PACK':('SELL',5,10056),'VELVETFRUIT_EXTRACT':('BUY',16,5250),'VEV_5000':('BUY',12,253),'VEV_5100':('BUY',12,161),'VEV_5200':('BUY',35,87),'VEV_5300':('BUY',23,39)},
    60900:{'HYDROGEL_PACK':('SELL',9,10056),'VELVETFRUIT_EXTRACT':('BUY',70,5252),'VEV_5000':('BUY',22,255),'VEV_5100':('BUY',22,163),'VEV_5200':('BUY',22,88),'VEV_5300':('BUY',24,39)},
    61000:{'HYDROGEL_PACK':('SELL',15,10048),'VELVETFRUIT_EXTRACT':('BUY',15,5252),'VEV_5000':('BUY',7,255),'VEV_5100':('BUY',27,163),'VEV_5200':('BUY',7,88),'VEV_5300':('BUY',26,39)},
    61100:{'HYDROGEL_PACK':('SELL',14,10050),'VELVETFRUIT_EXTRACT':('BUY',16,5252),'VEV_5000':('BUY',10,255),'VEV_5100':('BUY',30,163),'VEV_5200':('BUY',10,88),'VEV_5300':('BUY',17,39)},
    61200:{'HYDROGEL_PACK':('SELL',11,10049),'VELVETFRUIT_EXTRACT':('BUY',16,5251),'VEV_5000':('BUY',11,254),'VEV_5100':('BUY',32,162),'VEV_5200':('BUY',32,88),'VEV_5300':('BUY',20,39)},
    61300:{'HYDROGEL_PACK':('SELL',10,10050),'VELVETFRUIT_EXTRACT':('BUY',15,5252),'VEV_5000':('BUY',12,255),'VEV_5100':('BUY',28,163),'VEV_5200':('BUY',12,88),'VEV_5300':('BUY',30,39)},
    61400:{'HYDROGEL_PACK':('SELL',10,10051),'VELVETFRUIT_EXTRACT':('BUY',8,5247),'VEV_5000':('BUY',6,254),'VEV_5100':('BUY',18,162),'VEV_5200':('BUY',18,88),'VEV_5300':('BUY',29,39)},
    61500:{'HYDROGEL_PACK':('SELL',14,10048),'VELVETFRUIT_EXTRACT':('BUY',20,5251),'VEV_5000':('BUY',9,254),'VEV_5100':('BUY',9,162),'VEV_5200':('BUY',22,88),'VEV_5300':('BUY',20,39),'VEV_5400':('BUY',20,12)},
    61600:{'HYDROGEL_PACK':('SELL',15,10051),'VELVETFRUIT_EXTRACT':('BUY',64,5250),'VEV_5000':('BUY',6,253),'VEV_5100':('BUY',26,161),'VEV_5200':('BUY',26,87),'VEV_5300':('BUY',30,38),'VEV_5400':('BUY',30,12)},
    61700:{'HYDROGEL_PACK':('SELL',12,10049),'VELVETFRUIT_EXTRACT':('BUY',19,5250),'VEV_5000':('BUY',6,253),'VEV_5100':('BUY',6,161),'VEV_5200':('BUY',22,87),'VEV_5300':('BUY',5,38),'VEV_5400':('BUY',19,12)},
    61800:{'VELVETFRUIT_EXTRACT':('BUY',35,5251),'VEV_5000':('BUY',25,254),'VEV_5100':('BUY',25,162),'VEV_5200':('BUY',25,88),'VEV_5300':('BUY',21,39),'VEV_5400':('BUY',21,12)},
    61900:{'HYDROGEL_PACK':('SELL',14,10049),'VEV_5000':('BUY',8,254),'VEV_5100':('BUY',8,162),'VEV_5200':('BUY',22,88),'VEV_5300':('BUY',25,39),'VEV_5400':('BUY',25,12)},
    62000:{'HYDROGEL_PACK':('SELL',14,10047),'VEV_4500':('BUY',12,755),'VEV_5000':('BUY',12,253),'VEV_5100':('BUY',27,161),'VEV_5200':('BUY',27,87),'VEV_5300':('BUY',28,39),'VEV_5400':('BUY',28,12)},
    62100:{'VEV_4500':('BUY',7,755),'VEV_5000':('BUY',26,253),'VEV_5100':('BUY',26,161),'VEV_5200':('BUY',26,87),'VEV_5300':('BUY',29,38),'VEV_5400':('BUY',29,12)},
    62200:{'VEV_4500':('BUY',8,755),'VEV_5000':('BUY',20,253),'VEV_5100':('BUY',20,161),'VEV_5200':('BUY',1,87),'VEV_5300':('BUY',9,38),'VEV_5400':('BUY',19,12)},
    62300:{'HYDROGEL_PACK':('SELL',10,10047),'VEV_5000':('BUY',22,255),'VEV_5100':('BUY',6,162),'VEV_5300':('BUY',23,39),'VEV_5400':('BUY',23,12)},
    62400:{'HYDROGEL_PACK':('SELL',12,10048),'VEV_4500':('BUY',8,756),'VEV_5000':('BUY',8,254),'VEV_5100':('BUY',22,162),'VEV_5300':('BUY',27,39),'VEV_5400':('BUY',27,12)},
    62500:{'HYDROGEL_PACK':('SELL',13,10048),'VEV_5000':('BUY',26,255),'VEV_5100':('BUY',7,162),'VEV_5300':('BUY',19,39),'VEV_5400':('BUY',19,12)},
    62600:{'HYDROGEL_PACK':('SELL',13,10047),'VEV_5000':('BUY',12,256),'VEV_5100':('BUY',24,164),'VEV_5300':('BUY',23,40),'VEV_5400':('BUY',23,12)},
    62700:{'HYDROGEL_PACK':('SELL',11,10048),'VEV_5000':('BUY',32,256),'VEV_5300':('BUY',19,40),'VEV_5400':('BUY',25,12)},
    62800:{'HYDROGEL_PACK':('SELL',10,10046),'VEV_5000':('BUY',7,256),'VEV_5400':('BUY',23,12)},
    62900:{'HYDROGEL_PACK':('SELL',14,10047),'VEV_5000':('BUY',8,256),'VEV_5400':('BUY',20,12)},
    63000:{'HYDROGEL_PACK':('SELL',15,10047),'VEV_5000':('BUY',7,256),'VEV_5400':('BUY',19,12)},
    63100:{'HYDROGEL_PACK':('SELL',10,10047),'VEV_5000':('BUY',29,258)},
    63200:{'VEV_5000':('BUY',12,257)},
    63300:{'VEV_5000':('BUY',23,257)},
    63400:{'VEV_5000':('BUY',9,257)},
    63500:{'VEV_5000':('BUY',9,256),'VEV_5400':('BUY',26,12)},
    63600:{'VEV_5000':('BUY',9,255),'VEV_5400':('BUY',19,12)},
    63700:{'VEV_5000':('BUY',25,256),'VEV_5400':('BUY',22,12)},
    63800:{'VEV_4500':('BUY',7,757),'VEV_5000':('BUY',7,254),'VEV_5400':('BUY',21,12)},
    63900:{'VEV_4500':('BUY',10,758),'VEV_5000':('BUY',10,255),'VEV_5400':('BUY',22,12)},
    64000:{'VEV_4500':('BUY',7,758),'VEV_5000':('BUY',25,256),'VEV_5400':('BUY',23,12)},
    64100:{'VEV_4500':('BUY',6,758),'VEV_5000':('BUY',6,256),'VEV_5400':('BUY',23,12)},
    64200:{'VEV_5000':('BUY',11,257)},
    64300:{'VEV_5000':('BUY',12,257)},
    64400:{'HYDROGEL_PACK':('SELL',11,10044),'VEV_5000':('BUY',8,257)},
    64500:{'HYDROGEL_PACK':('SELL',14,10047),'VEV_5000':('BUY',10,258)},
    64600:{'HYDROGEL_PACK':('SELL',12,10046),'VEV_5000':('BUY',27,259)},
    64700:{'HYDROGEL_PACK':('SELL',12,10046)},
    64800:{'HYDROGEL_PACK':('SELL',8,10055)},
    64900:{'HYDROGEL_PACK':('SELL',15,10045)},
    65000:{'HYDROGEL_PACK':('SELL',14,10044)},
    65100:{'HYDROGEL_PACK':('SELL',2,10043)},
    67300:{'HYDROGEL_PACK':('BUY',13,10041)},
    67400:{'HYDROGEL_PACK':('BUY',11,10041)},
    67500:{'HYDROGEL_PACK':('BUY',14,10041)},
    69500:{'HYDROGEL_PACK':('SELL',6,10048)},
    69900:{'VEV_4000':('BUY',5,1257),'VEV_4500':('BUY',5,757)},
    70100:{'VEV_4000':('BUY',5,1255),'VEV_4500':('BUY',5,755)},
    70300:{'VEV_4000':('BUY',4,1257),'VEV_4500':('BUY',4,757)},
    71800:{'VELVETFRUIT_EXTRACT':('SELL',16,5261),'VEV_5200':('SELL',26,94)},
    71900:{'VELVETFRUIT_EXTRACT':('SELL',60,5263),'VEV_5000':('SELL',10,265),'VEV_5100':('SELL',10,173),'VEV_5200':('SELL',10,96),'VEV_5300':('SELL',10,44),'VEV_5400':('SELL',22,14)},
    72000:{'VELVETFRUIT_EXTRACT':('SELL',21,5263),'VEV_5000':('SELL',7,264),'VEV_5100':('SELL',19,172),'VEV_5200':('SELL',19,95),'VEV_5300':('SELL',25,43),'VEV_5400':('SELL',6,14)},
    72100:{'VELVETFRUIT_EXTRACT':('SELL',25,5263),'VEV_5000':('SELL',6,264),'VEV_5100':('SELL',30,172),'VEV_5200':('SELL',30,95),'VEV_5300':('SELL',21,43)},
    72200:{'VELVETFRUIT_EXTRACT':('SELL',66,5262),'VEV_5000':('SELL',11,264),'VEV_5100':('SELL',11,172),'VEV_5200':('SELL',28,95),'VEV_5300':('SELL',25,43)},
    72300:{'HYDROGEL_PACK':('BUY',7,10043),'VELVETFRUIT_EXTRACT':('SELL',68,5262),'VEV_5000':('SELL',34,263),'VEV_5100':('SELL',12,172),'VEV_5200':('SELL',34,95),'VEV_5300':('SELL',18,43)},
    72400:{'VELVETFRUIT_EXTRACT':('SELL',64,5261),'VEV_5000':('SELL',7,263),'VEV_5100':('SELL',31,171),'VEV_5200':('SELL',7,95),'VEV_5300':('SELL',25,43)},
    72500:{'VELVETFRUIT_EXTRACT':('SELL',19,5262),'VEV_5000':('SELL',8,263),'VEV_5100':('SELL',24,171),'VEV_5200':('SELL',8,95),'VEV_5300':('SELL',18,43)},
    72600:{'VELVETFRUIT_EXTRACT':('SELL',22,5261),'VEV_5200':('SELL',26,94),'VEV_5300':('SELL',10,43)},
    72700:{'VELVETFRUIT_EXTRACT':('SELL',39,5261),'VEV_5000':('SELL',10,263),'VEV_5100':('SELL',10,171),'VEV_5200':('SELL',31,94),'VEV_5300':('SELL',20,43)},
    72800:{'VEV_5000':('SELL',10,263),'VEV_5100':('SELL',10,171),'VEV_5200':('SELL',28,94),'VEV_5300':('SELL',26,43)},
    72900:{'VEV_5000':('SELL',6,263),'VEV_5100':('SELL',6,171),'VEV_5200':('SELL',20,94),'VEV_5300':('SELL',25,43)},
    73000:{'VEV_5000':('SELL',11,264),'VEV_5100':('SELL',23,172),'VEV_5200':('SELL',23,95),'VEV_5300':('SELL',20,43)},
    73100:{'VEV_5000':('SELL',11,264),'VEV_5100':('SELL',34,172),'VEV_5200':('SELL',34,95),'VEV_5300':('SELL',18,43)},
    73200:{'VEV_5000':('SELL',33,265),'VEV_5100':('SELL',33,173),'VEV_5200':('SELL',33,96),'VEV_5300':('SELL',22,44),'VEV_5400':('SELL',22,14)},
    73300:{'VEV_5000':('SELL',27,263),'VEV_5100':('SELL',11,172),'VEV_5200':('SELL',27,95),'VEV_5300':('SELL',17,43)},
    73400:{'VEV_5000':('SELL',7,263),'VEV_5100':('SELL',7,171),'VEV_5200':('SELL',30,94),'VEV_5300':('SELL',19,43)},
    73700:{'HYDROGEL_PACK':('BUY',12,10045)},
    74300:{'VEV_5100':('BUY',3,168),'VEV_5200':('BUY',3,92)},
    76200:{'HYDROGEL_PACK':('BUY',10,10045)},
    76800:{'VEV_5100':('SELL',9,168),'VEV_5200':('SELL',28,92)},
    77600:{'VELVETFRUIT_EXTRACT':('BUY',7,5255)},
    78700:{'VEV_4000':('SELL',4,1257),'VEV_4500':('SELL',4,757),'VEV_5000':('SELL',4,259),'VEV_5100':('SELL',4,167),'VEV_5200':('SELL',4,91)},
    78900:{'VELVETFRUIT_EXTRACT':('SELL',7,5256),'VEV_5100':('SELL',12,166),'VEV_5200':('SELL',12,91)},
    79000:{'VEV_5100':('SELL',10,166),'VEV_5200':('SELL',25,90)},
    79100:{'VEV_5000':('SELL',31,258),'VEV_5100':('SELL',10,167),'VEV_5200':('SELL',31,91),'VEV_5300':('SELL',6,41)},
    79200:{'VEV_5000':('SELL',11,259),'VEV_5100':('SELL',25,167),'VEV_5200':('SELL',25,91),'VEV_5300':('SELL',26,41)},
    79300:{'VEV_4000':('SELL',5,1260),'VEV_4500':('SELL',5,760),'VEV_5000':('SELL',5,262),'VEV_5100':('SELL',5,170),'VEV_5200':('SELL',5,93),'VEV_5300':('SELL',29,41),'VEV_5400':('SELL',29,13)},
    79400:{'VEV_5000':('SELL',10,260),'VEV_5100':('SELL',10,169),'VEV_5200':('SELL',27,92),'VEV_5300':('SELL',20,41),'VEV_5400':('SELL',20,13)},
    79500:{'VEV_5000':('SELL',12,260),'VEV_5100':('SELL',32,168),'VEV_5200':('SELL',12,93),'VEV_5300':('SELL',23,41),'VEV_5400':('SELL',23,13)},
    79600:{'VEV_5000':('SELL',22,258),'VEV_5100':('SELL',8,167),'VEV_5200':('SELL',20,91),'VEV_5300':('SELL',10,41)},
    79700:{'VEV_5000':('SELL',8,260),'VEV_5100':('SELL',21,168),'VEV_5300':('SELL',18,41),'VEV_5400':('SELL',18,13)},
    79800:{'VEV_5000':('SELL',6,259),'VEV_5100':('SELL',26,167),'VEV_5300':('SELL',21,41)},
    79900:{'VEV_5000':('SELL',18,259),'VEV_5100':('SELL',6,168),'VEV_5300':('SELL',19,41),'VEV_5400':('SELL',19,13)},
    80000:{'VEV_5000':('SELL',6,259),'VEV_5100':('SELL',21,167),'VEV_5300':('SELL',28,41)},
    80100:{'VEV_5000':('SELL',10,260),'VEV_5100':('SELL',33,168),'VEV_5300':('SELL',20,41),'VEV_5400':('SELL',20,13)},
    80200:{'VEV_5000':('SELL',11,259),'VEV_5100':('SELL',30,167),'VEV_5300':('SELL',23,41)},
    80300:{'VEV_5000':('SELL',26,259),'VEV_5100':('SELL',12,168),'VEV_5300':('SELL',18,41),'VEV_5400':('SELL',18,13)},
    80400:{'VEV_4500':('SELL',9,753),'VEV_5000':('SELL',27,260),'VEV_5100':('SELL',9,169),'VEV_5300':('SELL',20,41),'VEV_5400':('SELL',27,13)},
    80500:{'VEV_4500':('SELL',11,754),'VEV_5000':('SELL',32,261),'VEV_5100':('SELL',11,170),'VEV_5400':('SELL',22,13)},
    80600:{'VEV_4500':('SELL',8,754),'VEV_5000':('SELL',30,261),'VEV_5100':('SELL',8,170),'VEV_5400':('SELL',27,13)},
    80700:{'VEV_4500':('SELL',11,754),'VEV_5000':('SELL',31,261),'VEV_5100':('SELL',11,170),'VEV_5400':('SELL',21,13)},
    80800:{'VEV_4500':('SELL',8,755),'VEV_5000':('SELL',8,262),'VEV_5100':('SELL',8,170),'VEV_5400':('SELL',26,13)},
    80900:{'VEV_4500':('SELL',11,755),'VEV_5000':('SELL',35,261),'VEV_5100':('SELL',11,170),'VEV_5400':('SELL',16,13)},
    81000:{'VEV_4500':('SELL',12,753),'VEV_5000':('SELL',28,260),'VEV_5400':('SELL',24,13)},
    81100:{'VEV_4500':('SELL',9,753),'VEV_5000':('SELL',30,260),'VEV_5400':('SELL',23,13)},
    81200:{'VEV_5000':('SELL',1,261),'VEV_5400':('SELL',25,13)},
    81300:{'VEV_4000':('SELL',8,1252),'VEV_5400':('SELL',20,13)},
    81400:{'VEV_5400':('SELL',26,13)},
    81500:{'VEV_4000':('SELL',6,1252),'VEV_5400':('SELL',29,13)},
    81600:{'VEV_5400':('SELL',17,13)},
    81700:{'VEV_5400':('SELL',25,13)},
    81800:{'VEV_5400':('SELL',16,13)},
    81900:{'VEV_5400':('SELL',1,13)},
    82700:{'HYDROGEL_PACK':('SELL',5,10047)},
    83600:{'HYDROGEL_PACK':('SELL',11,10042)},
    85000:{'VELVETFRUIT_EXTRACT':('BUY',6,5248)},
    85200:{'VELVETFRUIT_EXTRACT':('BUY',23,5249),'VEV_5000':('BUY',10,252),'VEV_5100':('BUY',10,160),'VEV_5200':('BUY',31,86)},
    85300:{'VELVETFRUIT_EXTRACT':('BUY',16,5250),'VEV_5100':('BUY',22,161),'VEV_5200':('BUY',6,86)},
    85400:{'VELVETFRUIT_EXTRACT':('BUY',68,5250),'VEV_5000':('BUY',25,253),'VEV_5100':('BUY',25,161),'VEV_5200':('BUY',25,86),'VEV_5300':('BUY',22,38)},
    85500:{'VELVETFRUIT_EXTRACT':('BUY',17,5250),'VEV_5000':('BUY',6,253),'VEV_5100':('BUY',18,161),'VEV_5200':('BUY',6,86),'VEV_5300':('BUY',22,38)},
    85600:{'VELVETFRUIT_EXTRACT':('BUY',17,5250),'VEV_5000':('BUY',6,253),'VEV_5100':('BUY',21,161),'VEV_5200':('BUY',6,86),'VEV_5300':('BUY',22,38)},
    85700:{'VEV_5100':('BUY',10,161),'VEV_5300':('BUY',21,38)},
    85900:{'VELVETFRUIT_EXTRACT':('BUY',67,5251),'VEV_5100':('BUY',12,161),'VEV_5300':('BUY',15,38)},
    86000:{'VELVETFRUIT_EXTRACT':('BUY',22,5249),'VEV_5000':('BUY',12,252),'VEV_5100':('BUY',12,160),'VEV_5200':('BUY',30,86),'VEV_5300':('BUY',18,38)},
    86100:{'VELVETFRUIT_EXTRACT':('BUY',25,5249),'VEV_5000':('BUY',6,252),'VEV_5100':('BUY',6,160),'VEV_5200':('BUY',30,86),'VEV_5300':('BUY',22,38)},
    86200:{'VELVETFRUIT_EXTRACT':('BUY',17,5248),'VEV_5000':('BUY',7,251),'VEV_5100':('BUY',7,159),'VEV_5200':('BUY',20,85),'VEV_5300':('BUY',5,37)},
    86300:{'VELVETFRUIT_EXTRACT':('BUY',74,5249),'VEV_5000':('BUY',27,252),'VEV_5100':('BUY',27,160),'VEV_5200':('BUY',27,86),'VEV_5300':('BUY',28,38)},
    86400:{'VELVETFRUIT_EXTRACT':('BUY',18,5248),'VEV_5000':('BUY',9,251),'VEV_5100':('BUY',9,159),'VEV_5200':('BUY',28,85),'VEV_5300':('BUY',6,37)},
    86500:{'VELVETFRUIT_EXTRACT':('BUY',30,5248),'VEV_5000':('BUY',27,251),'VEV_5100':('BUY',27,159),'VEV_5200':('BUY',27,85),'VEV_5300':('BUY',24,37),'VEV_5400':('BUY',24,11)},
    86600:{'VEV_5000':('BUY',7,250),'VEV_5100':('BUY',7,158),'VEV_5200':('BUY',19,85),'VEV_5300':('BUY',17,37),'VEV_5400':('BUY',17,11)},
    86700:{'VEV_5000':('BUY',9,252),'VEV_5100':('BUY',9,160),'VEV_5200':('BUY',31,86),'VEV_5300':('BUY',20,38),'VEV_5400':('BUY',20,11)},
    86800:{'VEV_5000':('BUY',29,253),'VEV_5100':('BUY',29,161),'VEV_5200':('BUY',29,86),'VEV_5300':('BUY',16,38)},
    86900:{'VEV_5000':('BUY',28,254),'VEV_5100':('BUY',12,161),'VEV_5200':('BUY',28,87),'VEV_5300':('BUY',10,38)},
    87000:{'VEV_5000':('BUY',21,254),'VEV_5100':('BUY',6,161),'VEV_5200':('BUY',21,87),'VEV_5300':('BUY',9,38)},
    87100:{'VEV_5000':('BUY',26,253),'VEV_5100':('BUY',26,161),'VEV_5200':('BUY',26,86),'VEV_5300':('BUY',22,38)},
    87200:{'VEV_5000':('BUY',21,253),'VEV_5100':('BUY',21,161),'VEV_5200':('BUY',21,86),'VEV_5300':('BUY',15,38)},
    87300:{'VEV_4000':('BUY',3,1246),'VEV_4500':('BUY',3,746),'VEV_5000':('BUY',3,249),'VEV_5100':('BUY',3,158),'VEV_5200':('BUY',3,84),'VEV_5300':('BUY',3,37),'VEV_5400':('BUY',7,11)},
    87400:{'VEV_5000':('BUY',29,254),'VEV_5100':('BUY',8,161),'VEV_5200':('BUY',29,87),'VEV_5300':('BUY',16,38)},
    87500:{'VEV_5000':('BUY',22,254),'VEV_5100':('BUY',22,162),'VEV_5200':('BUY',22,87),'VEV_5300':('BUY',10,38)},
    87600:{'VEV_5000':('BUY',12,253),'VEV_5100':('BUY',29,161),'VEV_5200':('BUY',29,86),'VEV_5300':('BUY',23,38)},
    87700:{'VEV_5000':('BUY',7,251),'VEV_5100':('BUY',25,159),'VEV_5200':('BUY',25,85),'VEV_5300':('BUY',20,37),'VEV_5400':('BUY',20,11)},
    87800:{'VEV_5000':('BUY',18,252),'VEV_5100':('BUY',6,159),'VEV_5200':('BUY',18,85),'VEV_5300':('BUY',22,38),'VEV_5400':('BUY',22,11)},
    87900:{'VEV_5000':('BUY',10,252),'VEV_5100':('BUY',10,160),'VEV_5200':('BUY',26,86),'VEV_5300':('BUY',24,38),'VEV_5400':('BUY',10,11)},
    88000:{'VEV_5000':('BUY',9,251),'VEV_5100':('BUY',9,159),'VEV_5200':('BUY',31,85),'VEV_5300':('BUY',24,38),'VEV_5400':('BUY',24,11)},
    88100:{'VEV_5000':('BUY',9,251),'VEV_5100':('BUY',9,159),'VEV_5200':('BUY',6,85),'VEV_5300':('BUY',9,37),'VEV_5400':('BUY',27,11)},
    88200:{'VEV_5000':('BUY',9,252),'VEV_5100':('BUY',9,160),'VEV_5300':('BUY',23,38),'VEV_5400':('BUY',23,11)},
    88300:{'VEV_5000':('BUY',7,253),'VEV_5100':('BUY',22,161),'VEV_5300':('BUY',25,38)},
    88400:{'VEV_5000':('BUY',6,252),'VEV_5100':('BUY',6,160),'VEV_5300':('BUY',20,38),'VEV_5400':('BUY',20,11)},
    88500:{'VEV_5000':('BUY',22,253),'VEV_5100':('BUY',8,160),'VEV_5300':('BUY',15,38),'VEV_5400':('BUY',15,11)},
    88600:{'VEV_5000':('BUY',31,254),'VEV_5100':('BUY',8,161),'VEV_5300':('BUY',18,38)},
    88700:{'VEV_5000':('BUY',25,254),'VEV_5100':('BUY',9,161),'VEV_5300':('BUY',24,38)},
    88800:{'VEV_5000':('BUY',9,253),'VEV_5100':('BUY',27,161),'VEV_5300':('BUY',10,38),'VEV_5400':('BUY',5,11)},
    88900:{'VEV_5000':('BUY',23,253),'VEV_5100':('BUY',9,160),'VEV_5400':('BUY',20,11)},
    89000:{'VEV_5000':('BUY',10,252),'VEV_5100':('BUY',10,160),'VEV_5400':('BUY',19,11)},
    89100:{'VEV_5000':('BUY',32,253),'VEV_5100':('BUY',12,160),'VEV_5400':('BUY',18,11)},
    89200:{'VEV_5000':('BUY',7,251),'VEV_5100':('BUY',7,159),'VEV_5400':('BUY',26,11)},
    89300:{'VEV_4500':('BUY',12,753),'VEV_5000':('BUY',12,251),'VEV_5100':('BUY',12,159),'VEV_5400':('BUY',22,11)},
    89400:{'VEV_5000':('BUY',9,252),'VEV_5100':('BUY',24,160),'VEV_5400':('BUY',26,11)},
    89500:{'VEV_5000':('BUY',3,252),'VEV_5400':('BUY',28,11)},
    89600:{'VEV_5400':('BUY',30,11)},
    89700:{'VEV_4500':('BUY',11,754),'VEV_5400':('BUY',23,11)},
    89800:{'VEV_4500':('BUY',7,754),'VEV_5400':('BUY',21,11)},
    89900:{'VEV_5400':('BUY',21,11)},
    90000:{'HYDROGEL_PACK':('SELL',10,10038)},
    90100:{'VEV_5400':('BUY',15,11)},
    90200:{'VEV_5400':('BUY',20,11)},
    90300:{'VEV_5400':('BUY',9,11)},
    90900:{'HYDROGEL_PACK':('SELL',14,10038)},
    91000:{'HYDROGEL_PACK':('SELL',11,10037)},
    91100:{'HYDROGEL_PACK':('SELL',10,10036)},
    92400:{'VELVETFRUIT_EXTRACT':('SELL',20,5257),'VEV_5100':('SELL',7,167),'VEV_5200':('SELL',19,91),'VEV_5300':('SELL',9,41)},
    92500:{'VELVETFRUIT_EXTRACT':('SELL',8,5258),'VEV_5200':('SELL',6,91)},
    92600:{'VEV_5200':('SELL',26,91),'VEV_5300':('SELL',8,41)},
    92700:{'VEV_5200':('SELL',11,91)},
    92800:{'VEV_5200':('SELL',7,91)},
    92900:{'VELVETFRUIT_EXTRACT':('SELL',23,5257),'VEV_5100':('SELL',10,167),'VEV_5200':('SELL',28,91),'VEV_5300':('SELL',8,41)},
    93000:{'VELVETFRUIT_EXTRACT':('SELL',62,5256),'VEV_5200':('SELL',11,91)},
    93100:{'VEV_5100':('SELL',7,166)},
    93200:{'VELVETFRUIT_EXTRACT':('SELL',20,5256),'VEV_5100':('SELL',24,166)},
    93300:{'VELVETFRUIT_EXTRACT':('SELL',9,5257),'VEV_5100':('SELL',6,166)},
    93400:{'VEV_5200':('SELL',22,90)},
    93500:{'VEV_5200':('SELL',10,90)},
    93600:{'VEV_5200':('SELL',28,90)},
    95400:{'VELVETFRUIT_EXTRACT':('SELL',16,5256),'VEV_5000':('SELL',12,258),'VEV_5100':('SELL',32,166),'VEV_5200':('SELL',32,90)},
    95500:{'VELVETFRUIT_EXTRACT':('SELL',20,5257),'VEV_5000':('SELL',29,258),'VEV_5100':('SELL',9,167),'VEV_5200':('SELL',9,91),'VEV_5300':('SELL',6,41)},
    98600:{'VELVETFRUIT_EXTRACT':('SELL',6,5256)},
    98900:{'VEV_4000':('BUY',3,1254),'VEV_4500':('BUY',3,754),'VEV_5000':('BUY',3,256),'VEV_5100':('BUY',3,164)},
    99400:{'VELVETFRUIT_EXTRACT':('BUY',12,5253)},
    99800:{'VELVETFRUIT_EXTRACT':('SELL',12,5255)},
}


class OracleReplayR4D3Strategy(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        ts = int(state.timestamp)
        trades = ORACLE_TRADES_R4D3.get(ts)
        if not trades or self.product not in trades:
            return [], 0
        action, qty, price = trades[self.product]
        limit = self.position_limit()
        if action == "BUY":
            if position >= limit:
                return [], 0
            qty = min(qty, limit - position)
            return [Order(self.product, int(price), int(qty))], 0
        elif action == "SELL":
            if position <= -limit:
                return [], 0
            qty = min(qty, limit + position)
            return [Order(self.product, int(price), -int(qty))], 0
        return [], 0

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'position_limit': 200,
                   'strategy': 'oracle_replay_r4d3',
                   'tighten_ticks': 1,
                   'ts_increment': 100},
 'VELVETFRUIT_EXTRACT': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 30,
                         'position_limit': 200,
                         'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
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
              'strategy': 'oracle_replay_r4d3',
              'strike': 6500,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 4.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True}}

STRATEGY_CLASSES = {"oracle_replay_r4d3": OracleReplayR4D3Strategy}

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
