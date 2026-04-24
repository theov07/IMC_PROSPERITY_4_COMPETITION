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


# ── prosperity/strategies/round_3/hydrogel_exhaustion_taker.py ────────────────────

class HydrogelExhaustionTakerStrategy(BaseStrategy):
    """Contrarian taker on large HYDROGEL displacements."""

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
        mid = float(book.mid_price)
        ts = int(state.timestamp)
        self._update_mid_history(memory, ts, mid, p["history_keep_ts"])

        disp_fast = self._displacement(memory, ts, mid, p["fast_lookback_ts"])
        disp_slow = self._displacement(memory, ts, mid, p["slow_lookback_ts"])
        warm = disp_fast is not None and disp_slow is not None

        target = position
        mode = "warmup"
        if warm:
            target, mode = self._target_position(
                position=position,
                disp_fast=float(disp_fast),
                disp_slow=float(disp_slow),
                params=p,
            )
            entry_ts = memory.get("_het_entry_ts")
            if position != 0 and entry_ts is not None and ts - int(entry_ts) >= p["max_hold_ts"]:
                target = 0
                mode = "timeout_exit"
            elif position == 0 and target != 0:
                memory["_het_entry_ts"] = ts

        orders: List[Order] = []
        next_action_ts = int(memory.get("_het_next_action_ts", -1))
        if warm and target != position and ts >= next_action_ts:
            qty_needed = abs(target - position)
            if target > position:
                orders.extend(self._buy_orders(book, order_depth, position, qty_needed, p, mode))
            else:
                orders.extend(self._sell_orders(book, order_depth, position, qty_needed, p, mode))
            if orders:
                memory["_het_next_action_ts"] = ts + p["cooldown_ts"]
                if target == 0:
                    memory["_het_entry_ts"] = None

        memory["_het_mid"] = mid
        memory["_het_disp_fast"] = float(disp_fast) if disp_fast is not None else 0.0
        memory["_het_disp_slow"] = float(disp_slow) if disp_slow is not None else 0.0
        memory["_het_target"] = float(target)
        memory["_het_mode_code"] = float(
            {
                "warmup": 0,
                "hold": 1,
                "long_exhaustion": 2,
                "short_exhaustion": 3,
                "neutral_exit": 4,
                "timeout_exit": 5,
            }.get(mode, -1)
        )
        return orders, 0

    def _target_position(
        self,
        *,
        position: int,
        disp_fast: float,
        disp_slow: float,
        params: Dict[str, Any],
    ) -> Tuple[int, str]:
        max_pos = min(params["max_position"], self.position_limit())
        weak_pos = min(params["base_target"], max_pos)
        strong_pos = min(params["strong_target"], max_pos)

        if disp_fast <= -params["entry_fast_ticks"] or disp_slow <= -params["entry_slow_ticks"]:
            target = strong_pos if disp_slow <= -params["strong_slow_ticks"] else weak_pos
            return target, "long_exhaustion"
        if disp_fast >= params["entry_fast_ticks"] or disp_slow >= params["entry_slow_ticks"]:
            target = -strong_pos if disp_slow >= params["strong_slow_ticks"] else -weak_pos
            return target, "short_exhaustion"

        if abs(disp_fast) <= params["exit_fast_ticks"] and abs(disp_slow) <= params["exit_slow_ticks"]:
            return 0, "neutral_exit"

        return position, "hold"

    def _buy_orders(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        qty_needed: int,
        params: Dict[str, Any],
        mode: str,
    ) -> List[Order]:
        buy_cap = self.buy_capacity(position)
        if buy_cap <= 0:
            return []
        price, available = self._take_price_and_available(order_depth.sell_orders, is_buy=True, params=params, mode=mode)
        qty = min(qty_needed, buy_cap, params["taker_size"], available)
        if price is None or qty <= 0:
            return []
        return [Order(self.product, price, qty)]

    def _sell_orders(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        qty_needed: int,
        params: Dict[str, Any],
        mode: str,
    ) -> List[Order]:
        sell_cap = self.sell_capacity(position)
        if sell_cap <= 0:
            return []
        price, available = self._take_price_and_available(order_depth.buy_orders, is_buy=False, params=params, mode=mode)
        qty = min(qty_needed, sell_cap, params["taker_size"], available)
        if price is None or qty <= 0:
            return []
        return [Order(self.product, price, -qty)]

    def _take_price_and_available(
        self,
        side_book: Dict[int, int],
        *,
        is_buy: bool,
        params: Dict[str, Any],
        mode: str,
    ) -> Tuple[int | None, int]:
        if not side_book:
            return None, 0
        allow_l2 = bool(params["allow_l2"]) and mode in {"long_exhaustion", "short_exhaustion"}
        levels = sorted(side_book.items(), key=lambda item: item[0], reverse=not is_buy)
        selected = levels[:2] if allow_l2 and len(levels) > 1 else levels[:1]
        if not selected:
            return None, 0
        price = selected[-1][0]
        available = 0
        for _, qty in selected:
            available += abs(int(qty))
        return int(price), int(available)

    @staticmethod
    def _update_mid_history(memory: Dict[str, Any], ts: int, mid: float, keep_ts: int) -> None:
        hist: List[Tuple[int, float]] = memory.setdefault("_het_mid_hist", [])
        hist.append((ts, mid))
        min_ts = ts - keep_ts
        while hist and hist[0][0] < min_ts:
            del hist[0]

    @staticmethod
    def _displacement(memory: Dict[str, Any], ts: int, mid: float, lookback_ts: int) -> float | None:
        target_ts = ts - lookback_ts
        hist: List[Tuple[int, float]] = memory.get("_het_mid_hist", [])
        if not hist or hist[0][0] > target_ts:
            return None
        past = hist[0][1]
        for h_ts, h_mid in hist:
            if h_ts <= target_ts:
                past = h_mid
            else:
                break
        return mid - past

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        slow_lookback = int(params.get("slow_lookback_ts", 20000))
        return {
            "fast_lookback_ts": int(params.get("fast_lookback_ts", 10000)),
            "slow_lookback_ts": slow_lookback,
            "history_keep_ts": int(params.get("history_keep_ts", slow_lookback + 1000)),
            "entry_fast_ticks": float(params.get("entry_fast_ticks", 40.0)),
            "entry_slow_ticks": float(params.get("entry_slow_ticks", 40.0)),
            "strong_slow_ticks": float(params.get("strong_slow_ticks", 55.0)),
            "exit_fast_ticks": float(params.get("exit_fast_ticks", 10.0)),
            "exit_slow_ticks": float(params.get("exit_slow_ticks", 15.0)),
            "base_target": int(params.get("base_target", 80)),
            "strong_target": int(params.get("strong_target", 120)),
            "max_position": int(params.get("max_position", 120)),
            "taker_size": int(params.get("taker_size", 15)),
            "cooldown_ts": int(params.get("cooldown_ts", 1000)),
            "max_hold_ts": int(params.get("max_hold_ts", 30000)),
            "allow_l2": bool(params.get("allow_l2", False)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for key in (
            "_het_mid",
            "_het_disp_fast",
            "_het_disp_slow",
            "_het_target",
            "_het_mode_code",
        ):
            if (value := memory.get(key)) is not None:
                out[key.removeprefix("_het_")] = float(value)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'allow_l2': False,
                   'base_target': 80,
                   'cooldown_ts': 1000,
                   'entry_fast_ticks': 40.0,
                   'entry_slow_ticks': 40.0,
                   'exit_fast_ticks': 10.0,
                   'exit_slow_ticks': 15.0,
                   'fast_lookback_ts': 10000,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'max_hold_ts': 30000,
                   'max_position': 120,
                   'position_limit': 200,
                   'slow_lookback_ts': 20000,
                   'strategy': 'hydrogel_exhaustion_taker',
                   'strong_slow_ticks': 55.0,
                   'strong_target': 120,
                   'taker_size': 15,
                   'tighten_ticks': 1,
                   'ts_increment': 100}}

STRATEGY_CLASSES = {"hydrogel_exhaustion_taker": HydrogelExhaustionTakerStrategy}

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
