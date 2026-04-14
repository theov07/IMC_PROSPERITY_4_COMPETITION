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


# ── prosperity/strategies/naive_tight_mm_v6.py ────────────────────────────────────

class NaiveTightMarketMakerV6Strategy(BaseStrategy):

    def _take_absurd_orders(
        self, order_depth: OrderDepth, mid: float, buy_cap: int, sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Sweep mispriced orders before passive quoting."""
        orders: List[Order] = []
        take_edge = float(self.params.get("take_edge", 1.0))

        # Buy cheap asks (someone selling below mid - take_edge)
        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > mid - take_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty

        # Sell to expensive bids (someone buying above mid + take_edge)
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

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        # ── Step 1: sweep absurd orders ──
        take_orders, buy_cap, sell_cap = self._take_absurd_orders(
            order_depth, mid, buy_cap, sell_cap,
        )
        orders.extend(take_orders)

        # ── Step 2: find the REAL best bid/ask after removing swept levels ──
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

        # ── Step 3: quote at top of book on the clean book ──
        spread = real_best_ask - real_best_bid

        if spread >= 2:
            bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1)
            ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1)
        else:
            bid_price = real_best_bid
            ask_price = real_best_ask

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Orders: full remaining capacity ──
        if buy_cap > 0:
            orders.append(Order(self.product, bid_price, buy_cap))
        if sell_cap > 0:
            orders.append(Order(self.product, ask_price, -sell_cap))

        # ── logging ──
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        memory["takes"] = len(take_orders)

        flush_ts = int(self.params.get("log_flush_ts", 10000))
        last_tick_ts = int(self.params.get("total_ticks", 199900) - 100)

        log = memory.setdefault("_log", [])
        log.append([state.timestamp, bid_price, ask_price, position, len(take_orders)])

        end_of_sim = state.timestamp >= last_tick_ts
        checkpoint = flush_ts > 0 and (state.timestamp % flush_ts) == (flush_ts - 100)
        if end_of_sim or checkpoint:
            print(json.dumps({
                "product": self.product,
                "chunk_end": state.timestamp,
                "columns": ["timestamp", "bid_price", "ask_price", "position", "takes"],
                "log": log,
            }))
            memory["_log"] = []

        return orders, 0

# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'EMERALDS': {'anchor_price': 10000.0,
              'anchor_weight': 0.92,
              'ema_alpha': 0.08,
              'fair_mode': 'anchored_microprice',
              'improve_ticks': 1,
              'inventory_aversion': 1.2,
              'join_best': True,
              'log_flush_ts': 1000,
              'maker_size': 16,
              'max_inventory_bias_ticks': 4,
              'position_limit': 80,
              'quote_half_spread': 2,
              'strategy': 'naive_tight_mm_v6',
              'take_edge': 1.0,
              'tighten_ticks': 1,
              'total_ticks': 200000},
 'TOMATOES': {'anchor_price': None,
              'anchor_weight': 0.0,
              'ema_alpha': 0.18,
              'fair_mode': 'microprice_ema',
              'improve_ticks': 1,
              'inventory_aversion': 1.5,
              'join_best': True,
              'log_flush_ts': 1000,
              'maker_size': 14,
              'max_inventory_bias_ticks': 5,
              'position_limit': 80,
              'quote_half_spread': 2,
              'strategy': 'naive_tight_mm_v6',
              'take_edge': 1.0,
              'tighten_ticks': 1,
              'total_ticks': 200000}}

STRATEGY_CLASSES = {"naive_tight_mm_v6": NaiveTightMarketMakerV6Strategy}

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
