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


# ── prosperity/strategies/base.py ─────────────────────────────────────────────────

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
        if not self.runtime_trace_enabled():
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
           "log": [[ts, side, price, qty], ...]}
        """
        if not self.runtime_trace_enabled():
            return

        taker_log = memory.setdefault("_taker_log", [])
        taker_log.append([int(state.timestamp), side, price, quantity])

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


# ── prosperity/strategies/naive_tight_mm_v7.py ────────────────────────────────────

class NaiveTightMarketMakerV7Strategy(BaseStrategy):

    def _take_absurd_orders(
        self, order_depth: OrderDepth, mid: float, buy_cap: int, sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        take_edge = float(self.params.get("take_edge", 1.0))

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > mid - take_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < mid + take_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_price, -qty))
                sell_cap -= qty

        return orders, buy_cap, sell_cap

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        asym_strength = float(self.params.get("asym_strength", 0.0))
        spread_min_frac = float(self.params.get("spread_min_frac", 1.0))
        flow_window = int(self.params.get("flow_window", 0))
        cooldown_ticks = int(self.params.get("cooldown_ticks", 0))
        pj_detect = int(self.params.get("pj_detect", 0))
        pj_size_frac = float(self.params.get("pj_size_frac", 1.0))
        pj_qty_threshold = int(self.params.get("pj_qty_threshold", 0))
        qty_join_threshold = int(self.params.get("qty_join_threshold", 0))
        join_size_frac = float(self.params.get("join_size_frac", 1.0))
        level2_ticks = int(self.params.get("level2_ticks", 0))
        level2_frac = float(self.params.get("level2_frac", 0.0))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        # ── Sweep absurd orders ──
        take_orders, buy_cap, sell_cap = self._take_absurd_orders(
            order_depth, mid, buy_cap, sell_cap,
        )
        orders.extend(take_orders)

        # ── Clean book after sweep ──
        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}

        real_best_ask = book.best_ask
        for ask_p, _ in book.ask_levels:
            if ask_p not in swept_ask_prices:
                real_best_ask = ask_p
                break

        real_best_bid = book.best_bid
        for bid_p, _ in book.bid_levels:
            if bid_p not in swept_bid_prices:
                real_best_bid = bid_p
                break

        spread = real_best_ask - real_best_bid

        # ── Feature 4: Cooldown post-fill ──
        prev_position = memory.get("prev_position", 0)
        filled = position != prev_position
        memory["prev_position"] = position

        if cooldown_ticks > 0:
            if filled:
                memory["cooldown_remaining"] = cooldown_ticks
            remaining = memory.get("cooldown_remaining", 0)
            if remaining > 0:
                memory["cooldown_remaining"] = remaining - 1
                return orders, 0  # skip passive quoting, only keep take orders

        # ── Read previous tick's book (used by flow + pj_detect) ──
        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")

        # ── Feature 5: Penny jump detection ──
        do_tighten = True
        bid_jumped = False
        ask_jumped = False
        if pj_detect and prev_best_bid is not None and prev_best_ask is not None:
            bid_jumped = (real_best_bid == prev_best_bid + 1)
            ask_jumped = (real_best_ask == prev_best_ask - 1)
            if bid_jumped or ask_jumped:
                # 5c: qty threshold — re-tighten if jumper posted a large order
                if pj_qty_threshold > 0:
                    qty_at_bid = order_depth.buy_orders.get(real_best_bid, 0)
                    qty_at_ask = abs(order_depth.sell_orders.get(real_best_ask, 0))
                    large_bid = bid_jumped and qty_at_bid > pj_qty_threshold
                    large_ask = ask_jumped and qty_at_ask > pj_qty_threshold
                    if large_bid or large_ask:
                        do_tighten = True   # large wall → go in front
                    else:
                        do_tighten = False  # small order → join
                else:
                    do_tighten = False  # original behaviour: always join

        memory["prev_best_bid"] = real_best_bid
        memory["prev_best_ask"] = real_best_ask

        # ── Price: top of book ──
        # Feature 6: queue-aware quoting — per-side join vs tighten based on qty at best
        if qty_join_threshold > 0:
            qty_at_bid = order_depth.buy_orders.get(real_best_bid, 0)
            qty_at_ask = abs(order_depth.sell_orders.get(real_best_ask, 0))
            tighten_bid = spread >= 2 and do_tighten and qty_at_bid > qty_join_threshold
            tighten_ask = spread >= 2 and do_tighten and qty_at_ask > qty_join_threshold
        else:
            tighten_bid = spread >= 2 and do_tighten
            tighten_ask = spread >= 2 and do_tighten

        bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1) if tighten_bid else real_best_bid
        ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1) if tighten_ask else real_best_ask

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Sizing: start from full capacity ──
        buy_size = buy_cap
        sell_size = sell_cap

        # ── Feature 1: Asymmetric sizing ──
        if asym_strength > 0.0:
            limit = self.position_limit()
            if limit > 0:
                inv_ratio = position / limit  # -1 to +1
                # When long (inv_ratio > 0): reduce buy, keep sell
                # When short (inv_ratio < 0): reduce sell, keep buy
                reduce_buy = max(0.0, inv_ratio * asym_strength)   # 0 to 1
                reduce_sell = max(0.0, -inv_ratio * asym_strength)  # 0 to 1
                buy_size = max(1, int(buy_cap * (1.0 - reduce_buy)))
                sell_size = max(1, int(sell_cap * (1.0 - reduce_sell)))

        # ── Feature 2: Spread-dependent sizing ──
        if spread_min_frac < 1.0:
            # Scale from spread_min_frac (at spread=1) to 1.0 (at spread>=3)
            spread_factor = min(1.0, spread_min_frac + (1.0 - spread_min_frac) * (spread - 1) / 2.0)
            buy_size = max(1, int(buy_size * spread_factor))
            sell_size = max(1, int(sell_size * spread_factor))

        # ── Feature 5b: Penny jump adverse-side size reduction ──
        if pj_size_frac < 1.0 and (bid_jumped or ask_jumped):
            if bid_jumped:
                sell_size = max(1, int(sell_size * pj_size_frac))  # bid jumped → price rising → reduce ask
            if ask_jumped:
                buy_size = max(1, int(buy_size * pj_size_frac))    # ask jumped → price falling → reduce bid

        # ── Feature 3: Trade flow detection (price-vs-book inference) ──
        if flow_window > 0:
            flow_history = memory.setdefault("flow_history", [])
            trades = state.market_trades.get(self.product, [])
            if trades and prev_best_bid is not None and prev_best_ask is not None:
                for t in trades:
                    if t.price >= prev_best_ask:
                        flow_history.append(t.quantity)   # aggressive buy
                    elif t.price <= prev_best_bid:
                        flow_history.append(-t.quantity)  # aggressive sell
            if len(flow_history) > flow_window:
                del flow_history[:-flow_window]

            if flow_history:
                net = sum(flow_history)
                total = sum(abs(x) for x in flow_history)
                if total > 0:
                    flow_strength = net / total
                    if flow_strength > 0.3:
                        sell_size = max(1, sell_size // 2)
                    elif flow_strength < -0.3:
                        buy_size = max(1, buy_size // 2)

        # ── Orders ──
        if join_size_frac < 1.0:
            if not tighten_bid and buy_size > 0:
                buy_size = max(1, int(buy_size * join_size_frac))
            if not tighten_ask and sell_size > 0:
                sell_size = max(1, int(sell_size * join_size_frac))

        bid_orders: List[Tuple[int, int]] = []
        ask_orders: List[Tuple[int, int]] = []

        def _split_level_size(total: int) -> Tuple[int, int]:
            if total <= 1 or level2_frac <= 0.0:
                return total, 0
            secondary = int(round(total * level2_frac))
            secondary = max(0, min(secondary, total - 1))
            return total - secondary, secondary

        can_two_level = (
            level2_frac > 0.0
            and level2_ticks > tighten_ticks
            and spread >= (2 * level2_ticks + 1)
        )
        level2_bid_price = min(real_best_bid + level2_ticks, real_best_ask - 1)
        level2_ask_price = max(real_best_ask - level2_ticks, real_best_bid + 1)

        primary_buy_size, secondary_buy_size = _split_level_size(buy_size) if (can_two_level and tighten_bid) else (buy_size, 0)
        primary_sell_size, secondary_sell_size = _split_level_size(sell_size) if (can_two_level and tighten_ask) else (sell_size, 0)

        if primary_buy_size > 0:
            bid_orders.append((bid_price, primary_buy_size))
        if secondary_buy_size > 0 and level2_bid_price > bid_price and level2_bid_price < ask_price:
            bid_orders.append((level2_bid_price, secondary_buy_size))

        if primary_sell_size > 0:
            ask_orders.append((ask_price, primary_sell_size))
        if secondary_sell_size > 0 and level2_ask_price < ask_price and level2_ask_price > bid_price:
            ask_orders.append((level2_ask_price, secondary_sell_size))

        for price, size in bid_orders:
            orders.append(Order(self.product, price, size))
        for price, size in ask_orders:
            orders.append(Order(self.product, price, -size))

        # ── logging ──
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
            },
        )

        return orders, 0

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'ASH_COATED_OSMIUM': {'asym_strength': 0.0,
                       'cooldown_ticks': 0,
                       'flow_window': 0,
                       'join_size_frac': 1.0,
                       'last_ts_value': 999900,
                       'level2_frac': 0.0,
                       'level2_ticks': 0,
                       'log_flush_ts': 1000,
                       'maker_size': 80,
                       'pj_detect': 0,
                       'pj_qty_threshold': 0,
                       'pj_size_frac': 1.0,
                       'position_limit': 80,
                       'qty_join_threshold': 0,
                       'spread_min_frac': 1.0,
                       'strategy': 'naive_tight_mm_v7',
                       'take_edge': 1.0,
                       'tighten_ticks': 1,
                       'ts_increment': 100},
 'INTARIAN_PEPPER_ROOT': {'asym_strength': 0.0,
                          'cooldown_ticks': 0,
                          'flow_window': 0,
                          'join_size_frac': 1.0,
                          'last_ts_value': 999900,
                          'level2_frac': 0.0,
                          'level2_ticks': 0,
                          'log_flush_ts': 1000,
                          'maker_size': 80,
                          'pj_detect': 0,
                          'pj_qty_threshold': 0,
                          'pj_size_frac': 1.0,
                          'position_limit': 80,
                          'qty_join_threshold': 0,
                          'spread_min_frac': 1.0,
                          'strategy': 'naive_tight_mm_v7',
                          'take_edge': 1.0,
                          'tighten_ticks': 1,
                          'ts_increment': 100}}

STRATEGY_CLASSES = {"naive_tight_mm_v7": NaiveTightMarketMakerV7Strategy}

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
        result = {}
        total_conversions = 0
        for product, strategy in self.strategies.items():
            if product not in state.order_depths:
                continue
            memory = product_memories.setdefault(product, {})
            orders, conversions = strategy.on_tick(state, memory)
            result[product] = orders
            total_conversions += conversions
        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)
