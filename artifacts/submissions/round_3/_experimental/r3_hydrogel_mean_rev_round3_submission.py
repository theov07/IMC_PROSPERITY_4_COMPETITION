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


# ── prosperity/strategies/round_3/hydrogel_mean_rev_taker.py ──────────────────────

class HydrogelMeanRevTakerStrategy(BaseStrategy):
    """Mean-rev taker + passive MM overlay, tuned for wide-spread HYDROGEL_PACK."""

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

        p = self._read_params()
        mid = 0.5 * (book.best_bid + book.best_ask)

        # EWMA mean + variance (incremental)
        alpha = 2.0 / (p["window"] + 1)
        mean_prev = memory.get("_ewma_mean", mid)
        var_prev = memory.get("_ewma_var", 0.0)
        tick_count = memory.get("_tick_count", 0) + 1
        delta = mid - mean_prev
        new_mean = mean_prev + alpha * delta
        # Variance: Welford-style EWMA
        new_var = (1 - alpha) * (var_prev + alpha * delta * delta)
        memory["_ewma_mean"] = new_mean
        memory["_ewma_var"] = new_var
        memory["_tick_count"] = tick_count

        std = (new_var ** 0.5) if new_var > 0 else 0.0
        z = (mid - new_mean) / std if std > 1e-6 else 0.0
        memory["_z"] = z
        memory["_ewma_std"] = std

        limit = self.position_limit()
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        orders: List[Order] = []
        mode = "warmup"

        # Only use signal after warmup
        if tick_count >= p["min_samples"] and std > 1e-6:
            abs_z = abs(z)

            # ── Entry / taker mode ──
            # Only fires if taker_size_base > 0 AND |z| >= entry_z.
            taker_position = memory.get("_taker_position", 0)
            if p["taker_size_base"] > 0 and abs_z >= p["entry_z"]:
                mode = "taker_entry"
                target_qty = int(p["taker_size_base"] + p["taker_size_per_z"] * max(0, abs_z - 1.0))
                if z > 0 and sell_cap > 0 and taker_position > -p["max_taker_position"]:
                    bid_px = book.best_bid
                    max_sell = min(sell_cap, p["max_taker_position"] + taker_position, target_qty)
                    avail = order_depth.buy_orders.get(bid_px, 0)
                    qty = min(max_sell, avail)
                    if qty > 0:
                        orders.append(Order(self.product, bid_px, -qty))
                        sell_cap -= qty
                        memory["_taker_position"] = taker_position - qty
                elif z < 0 and buy_cap > 0 and taker_position < p["max_taker_position"]:
                    ask_px = book.best_ask
                    max_buy = min(buy_cap, p["max_taker_position"] - taker_position, target_qty)
                    avail = -order_depth.sell_orders.get(ask_px, 0)
                    qty = min(max_buy, avail)
                    if qty > 0:
                        orders.append(Order(self.product, ask_px, qty))
                        buy_cap -= qty
                        memory["_taker_position"] = taker_position + qty

            # ── Exit mode: flatten ONLY the taker_position (not passive fills) ──
            # If z is back near 0 and we have an active taker position, unwind it.
            elif p["taker_size_base"] > 0 and abs_z <= p["exit_z"] and taker_position != 0:
                mode = "exit"
                if taker_position > 0 and sell_cap > 0:
                    bid_px = book.best_bid
                    avail = order_depth.buy_orders.get(bid_px, 0)
                    qty = min(sell_cap, taker_position, avail, p["exit_chunk_size"])
                    if qty > 0:
                        orders.append(Order(self.product, bid_px, -qty))
                        sell_cap -= qty
                        memory["_taker_position"] = taker_position - qty
                elif taker_position < 0 and buy_cap > 0:
                    ask_px = book.best_ask
                    avail = -order_depth.sell_orders.get(ask_px, 0)
                    qty = min(buy_cap, -taker_position, avail, p["exit_chunk_size"])
                    if qty > 0:
                        orders.append(Order(self.product, ask_px, qty))
                        buy_cap -= qty
                        memory["_taker_position"] = taker_position + qty

            else:
                mode = "neutral"

        # ── Passive MM overlay (always on by default) ──
        # NEW: z-score skew — if mid is above rolling mean (z>0, "rich"), shrink
        # bid and grow ask (fade upward excursion passively, no spread cost).
        if p["enable_passive_mm"] and buy_cap > 0 and sell_cap > 0:
            # Inventory aversion
            inv_bid_mult = 1.0 - max(0.0, p["inventory_aversion"] * position / max(1, limit))
            inv_ask_mult = 1.0 - max(0.0, p["inventory_aversion"] * (-position) / max(1, limit))
            # z-score passive skew (|z| large → asymmetric sizes)
            z_clamp = max(-3.0, min(3.0, z))
            z_skew_gain = p["z_passive_skew_gain"]
            # Long delta in market (z>0 = we think it will fall):
            #   grow ask_size (sell more when market is high), shrink bid
            z_bid_mult = max(0.0, 1.0 - z_skew_gain * max(0.0, z_clamp))
            z_ask_mult = max(0.0, 1.0 + z_skew_gain * max(0.0, z_clamp))
            # z<0 (market low, should rise): grow bid, shrink ask
            z_bid_mult *= max(0.0, 1.0 + z_skew_gain * max(0.0, -z_clamp))
            z_ask_mult *= max(0.0, 1.0 - z_skew_gain * max(0.0, -z_clamp))

            bid_l1 = book.best_bid + 1
            ask_l1 = book.best_ask - 1
            if bid_l1 < book.best_ask:
                q = int(round(p["passive_l1_size"] * inv_bid_mult * z_bid_mult))
                q = min(q, buy_cap)
                if q > 0:
                    orders.append(Order(self.product, bid_l1, q))
            if ask_l1 > book.best_bid:
                q = int(round(p["passive_l1_size"] * inv_ask_mult * z_ask_mult))
                q = min(q, sell_cap)
                if q > 0:
                    orders.append(Order(self.product, ask_l1, -q))

        memory["_mode"] = mode
        return orders, 0

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "window": int(params.get("window", 500)),
            "entry_z": float(params.get("entry_z", 2.0)),
            "exit_z": float(params.get("exit_z", 0.5)),
            "taker_size_base": int(params.get("taker_size_base", 20)),
            "taker_size_per_z": int(params.get("taker_size_per_z", 10)),
            "max_taker_position": int(params.get("max_taker_position", 150)),
            "exit_chunk_size": int(params.get("exit_chunk_size", 30)),
            "passive_l1_size": int(params.get("passive_l1_size", 30)),
            "inventory_aversion": float(params.get("inventory_aversion", 0.5)),
            "enable_passive_mm": bool(params.get("enable_passive_mm", True)),
            "min_samples": int(params.get("min_samples", 100)),
            "z_passive_skew_gain": float(params.get("z_passive_skew_gain", 0.25)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("_ewma_mean")) is not None:
            out["ewma_mean"] = m
        if (s := memory.get("_ewma_std")) is not None:
            out["ewma_std"] = s
        if (z := memory.get("_z")) is not None:
            out["z"] = z
        if (mo := memory.get("_mode")) is not None:
            out["mode_code"] = {"warmup": 0, "neutral": 1, "taker_entry": 2, "exit": 3}.get(mo, -1)
        return out

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'HYDROGEL_PACK': {'enable_passive_mm': True,
                   'entry_z': 99.0,
                   'exit_chunk_size': 30,
                   'exit_z': 0.5,
                   'inventory_aversion': 0.5,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'maker_size': 30,
                   'max_taker_position': 0,
                   'min_samples': 100,
                   'passive_l1_size': 30,
                   'position_limit': 200,
                   'strategy': 'hydrogel_mean_rev_taker',
                   'taker_size_base': 0,
                   'taker_size_per_z': 0,
                   'tighten_ticks': 1,
                   'ts_increment': 100,
                   'window': 500,
                   'z_passive_skew_gain': 3.0}}

STRATEGY_CLASSES = {"hydrogel_mean_rev_taker": HydrogelMeanRevTakerStrategy}

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
