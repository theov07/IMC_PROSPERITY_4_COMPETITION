from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Tuple
from typing import List, Tuple
import json

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
        flush_ts = int(self.params.get("log_flush_ts", 10000))
        last_tick_ts = int(self.params.get("total_ticks", 199900) - 100)

        log = memory.setdefault("_log", [])
        log.append([state.timestamp, bid_price, ask_price, position, buy_size, sell_size])

        end_of_sim = state.timestamp >= last_tick_ts
        checkpoint = flush_ts > 0 and (state.timestamp % flush_ts) == (flush_ts - 100)
        if end_of_sim or checkpoint:
            print(json.dumps({
                "product": self.product,
                "chunk_end": state.timestamp,
                "columns": ["timestamp", "bid", "ask", "position", "buy_size", "sell_size"],
                "log": log,
            }))
            memory["_log"] = []

        return orders, 0

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'EMERALDS': {'anchor_price': 10000.0,
              'anchor_weight': 0.92,
              'asym_strength': 0.0,
              'cooldown_ticks': 0,
              'ema_alpha': 0.08,
              'fair_mode': 'anchored_microprice',
              'flow_window': 0,
              'improve_ticks': 1,
              'inventory_aversion': 1.2,
              'join_best': True,
              'log_flush_ts': 1000,
              'maker_size': 16,
              'max_inventory_bias_ticks': 4,
              'pj_detect': 0,
              'pj_qty_threshold': 0,
              'pj_size_frac': 1.0,
              'position_limit': 80,
              'qty_join_threshold': 5,
              'quote_half_spread': 2,
              'spread_min_frac': 1.0,
              'strategy': 'naive_tight_mm_v7',
              'take_edge': 1.0,
              'tighten_ticks': 1,
              'total_ticks': 200000},
 'TOMATOES': {'anchor_price': None,
              'anchor_weight': 0.0,
              'asym_strength': 0.0,
              'cooldown_ticks': 0,
              'ema_alpha': 0.18,
              'fair_mode': 'microprice_ema',
              'flow_window': 0,
              'improve_ticks': 1,
              'inventory_aversion': 1.5,
              'join_best': True,
              'log_flush_ts': 1000,
              'maker_size': 14,
              'max_inventory_bias_ticks': 5,
              'pj_detect': 0,
              'pj_qty_threshold': 0,
              'pj_size_frac': 1.0,
              'position_limit': 80,
              'qty_join_threshold': 0,
              'quote_half_spread': 2,
              'spread_min_frac': 1.0,
              'strategy': 'naive_tight_mm_v7',
              'take_edge': 1.0,
              'tighten_ticks': 1,
              'total_ticks': 200000}}

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
