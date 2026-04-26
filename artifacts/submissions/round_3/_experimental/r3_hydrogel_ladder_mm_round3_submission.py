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


# ── prosperity/strategies/round_3/hydrogel_ladder_mm.py ───────────────────────────

class HydrogelLadderMMStrategy(BaseStrategy):
    """Multi-level passive ladder inside spread, with inventory control."""

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

        p = self._read_params()
        spread = book.spread or 0
        # Need at least 2-tick spread to ladder inside; otherwise fall back to
        # joining best.
        if spread < p["min_spread_for_ladder"]:
            return self._narrow_fallback(book, position, p), 0

        mid = float(book.mid_price)
        best_bid = int(book.best_bid)
        best_ask = int(book.best_ask)

        # EWMA mean (for optional logging only — no signal-driven asym in v1)
        alpha = 2.0 / (p["window"] + 1)
        mean_prev = memory.get("_ewma_mean", mid)
        new_mean = mean_prev + alpha * (mid - mean_prev)
        memory["_ewma_mean"] = new_mean
        memory["_mid"] = mid

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Hard position cap blocks one side
        hard_cap = p["hard_pos_cap"]
        block_bid = position >= hard_cap
        block_ask = position <= -hard_cap

        # Build ladder prices (clipped so no level crosses mid)
        num_levels = p["num_levels"]
        step = p["level_step"]
        bid_prices = []
        ask_prices = []
        for i in range(num_levels):
            bp = best_bid + 1 + i * step
            ap = best_ask - 1 - i * step
            # Clip: bid stays strictly below mid, ask strictly above
            if bp < mid - 0.5:
                bid_prices.append(bp)
            if ap > mid + 0.5:
                ask_prices.append(ap)

        # Ensure we don't accidentally overlap (highest bid < lowest ask)
        if bid_prices and ask_prices and max(bid_prices) >= min(ask_prices):
            # Shrink to maintain at least 1 tick gap
            while bid_prices and ask_prices and max(bid_prices) >= min(ask_prices):
                # Drop the most aggressive (highest) bid and (lowest) ask
                bid_prices = [p for p in bid_prices if p < min(ask_prices)]
                ask_prices = [p for p in ask_prices if p > max(bid_prices) if bid_prices] or ask_prices[1:]

        # Sizing: pyramid (decreasing from best to outer) or uniform
        size_mode = p["size_mode"]
        total_per_side = p["total_size_per_side"]
        bid_sizes = self._level_sizes(len(bid_prices), total_per_side, size_mode)
        ask_sizes = self._level_sizes(len(ask_prices), total_per_side, size_mode)

        # Inventory skew: shrink wrong side, grow unwind side
        reduce_per = p["inventory_reduce_per_unit"]
        unwind_per = p["inventory_unwind_per_unit"]
        unwind_max = p["unwind_boost_max"]
        if position > 0:
            shrink = int(position * reduce_per)
            grow = min(unwind_max, int(position * unwind_per))
            bid_sizes = [max(0, s - shrink // max(1, len(bid_sizes))) for s in bid_sizes]
            ask_sizes = [s + grow // max(1, len(ask_sizes)) for s in ask_sizes]
        elif position < 0:
            shrink = int(-position * reduce_per)
            grow = min(unwind_max, int(-position * unwind_per))
            ask_sizes = [max(0, s - shrink // max(1, len(ask_sizes))) for s in ask_sizes]
            bid_sizes = [s + grow // max(1, len(bid_sizes)) for s in bid_sizes]

        if block_bid:
            bid_sizes = [0] * len(bid_sizes)
        if block_ask:
            ask_sizes = [0] * len(ask_sizes)

        orders: List[Order] = []
        # Place bids (highest price first → fills first)
        for price, size in zip(bid_prices, bid_sizes):
            if size <= 0 or buy_cap <= 0:
                continue
            qty = min(size, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, price, qty))
                buy_cap -= qty
        # Place asks (lowest price first → fills first)
        for price, size in zip(ask_prices, ask_sizes):
            if size <= 0 or sell_cap <= 0:
                continue
            qty = min(size, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, price, -qty))
                sell_cap -= qty

        memory["_num_bid_levels"] = len(bid_prices)
        memory["_num_ask_levels"] = len(ask_prices)
        memory["_total_bid_size"] = sum(bid_sizes)
        memory["_total_ask_size"] = sum(ask_sizes)
        return orders, 0

    # ── Narrow-spread fallback: just penny-improve single level ─────────────

    def _narrow_fallback(
        self, book: BookSnapshot, position: int, p: Dict[str, Any]
    ) -> List[Order]:
        # When spread < min_spread_for_ladder, use single-level penny-improve.
        size = p["fallback_size"]
        bid_price = int(book.best_bid) + 1 if book.spread and book.spread >= 2 else int(book.best_bid)
        ask_price = int(book.best_ask) - 1 if book.spread and book.spread >= 2 else int(book.best_ask)
        # Make sure not crossing
        if bid_price >= ask_price:
            bid_price = int(book.best_bid)
            ask_price = int(book.best_ask)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        hard_cap = p["hard_pos_cap"]
        out: List[Order] = []
        if position < hard_cap and buy_cap > 0:
            out.append(Order(self.product, bid_price, min(size, buy_cap)))
        if position > -hard_cap and sell_cap > 0:
            out.append(Order(self.product, ask_price, -min(size, sell_cap)))
        return out

    # ── Level-size distribution ─────────────────────────────────────────────

    def _level_sizes(self, n: int, total: int, mode: str) -> List[int]:
        if n <= 0:
            return []
        if mode == "uniform":
            base = total // n
            rem = total - base * n
            return [base + (1 if i < rem else 0) for i in range(n)]
        # pyramid: more at level 0 (closest to best, fills fastest)
        # weights = n, n-1, ..., 1
        if mode == "pyramid":
            weights = list(range(n, 0, -1))
            tot_w = sum(weights)
            sizes = [int(total * w / tot_w) for w in weights]
            # adjust rounding to match total
            diff = total - sum(sizes)
            for i in range(diff):
                sizes[i % n] += 1
            return sizes
        # inverted_pyramid: more at outer levels (fewer fills, less inventory churn)
        if mode == "inverted_pyramid":
            weights = list(range(1, n + 1))
            tot_w = sum(weights)
            sizes = [int(total * w / tot_w) for w in weights]
            diff = total - sum(sizes)
            for i in range(diff):
                sizes[-(i % n + 1)] += 1
            return sizes
        # default uniform
        base = total // n
        rem = total - base * n
        return [base + (1 if i < rem else 0) for i in range(n)]

    # ── Params ──────────────────────────────────────────────────────────────

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "num_levels": int(params.get("num_levels", 4)),
            "level_step": int(params.get("level_step", 1)),
            "total_size_per_side": int(params.get("total_size_per_side", 40)),
            "size_mode": str(params.get("size_mode", "pyramid")),
            "min_spread_for_ladder": int(params.get("min_spread_for_ladder", 4)),
            "fallback_size": int(params.get("fallback_size", 8)),
            "inventory_reduce_per_unit": float(params.get("inventory_reduce_per_unit", 0.5)),
            "inventory_unwind_per_unit": float(params.get("inventory_unwind_per_unit", 0.3)),
            "unwind_boost_max": int(params.get("unwind_boost_max", 30)),
            "hard_pos_cap": int(params.get("hard_pos_cap", 60)),
            "window": int(params.get("window", 500)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ewma_mean", "_mid", "_total_bid_size", "_total_ask_size"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = float(v)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'fallback_size': 8,
                   'hard_pos_cap': 60,
                   'inventory_reduce_per_unit': 0.5,
                   'inventory_unwind_per_unit': 0.3,
                   'last_ts_value': 999900,
                   'level_step': 1,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'min_spread_for_ladder': 4,
                   'num_levels': 4,
                   'position_limit': 200,
                   'size_mode': 'pyramid',
                   'strategy': 'hydrogel_ladder_mm',
                   'tighten_ticks': 1,
                   'total_size_per_side': 40,
                   'ts_increment': 100,
                   'unwind_boost_max': 30,
                   'window': 500}}

STRATEGY_CLASSES = {"hydrogel_ladder_mm": HydrogelLadderMMStrategy}

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
